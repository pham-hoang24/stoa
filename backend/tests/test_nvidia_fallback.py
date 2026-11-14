import json
import os
from types import SimpleNamespace

import httpx2 as httpx
import openai
import pytest

from stoa.lanes import llm

NVIDIA_BASE = 'https://integrate.api.nvidia.com/v1'
NVIDIA_MODEL = 'nvidia/nemotron-3.5-super-vl-120b-a12b'
MODAL_MODEL = 'Qwen/Qwen3.8-Max-VL-Thinking'


@pytest.fixture
def sdk(monkeypatch, tmp_path):
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    for name in list(os.environ):
        if name.startswith('STOA_LLM_') or name.startswith('STOA_NVIDIA_') or name.startswith('STOA_MODAL_'):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('NVIDIA_API_KEY', 'controlled-nvidia-key')
    monkeypatch.setenv('MODAL_API_KEY', 'controlled-modal-key')
    monkeypatch.setenv('STOA_LLM_API_KEY', 'controlled-featherless-key')
    monkeypatch.setenv('STOA_LLM_MODEL', 'featherless-model')
    monkeypatch.setattr(llm, '_env', lambda: None)
    monkeypatch.setattr(llm, 'CACHE', tmp_path/'cache')
    llm.reset_usage()
    state = SimpleNamespace(calls=[], handler=lambda config, request: 'ok')

    def client(**config):
        def create(**request):
            state.calls.append({'config': config, 'request': request})
            content = state.handler(config, request)
            return SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(openai, 'OpenAI', client)
    return state


def messages():
    return [{'role': 'user', 'content': 'Controlled fallback test'}]


def timeout():
    return openai.APITimeoutError(request=httpx.Request('POST', NVIDIA_BASE+'/chat/completions'))


def fail_nvidia(config, request):
    if config['base_url'] == NVIDIA_BASE:
        raise timeout()
    return 'secondary answer'


def test_nvidia_is_default_with_its_own_model_key_and_configurable_timeout(sdk, monkeypatch):
    monkeypatch.setenv('STOA_LLM_TIMEOUT_SECONDS', '12.5')
    reply = llm.chat(messages())
    call = sdk.calls[0]
    assert call['config']['base_url'] == NVIDIA_BASE
    assert call['config']['api_key'] == 'controlled-nvidia-key'
    assert call['request']['model'] == NVIDIA_MODEL
    assert call['config']['timeout'] == 12.5 and call['config']['max_retries'] == 0
    assert reply.provenance['provider'] == 'nvidia'


def test_nvidia_model_and_endpoint_can_be_overridden_without_changing_keys(sdk, monkeypatch):
    monkeypatch.setenv('STOA_NVIDIA_MODEL','custom-nvidia-model')
    monkeypatch.setenv('STOA_NVIDIA_BASE_URL','https://nvidia.example/')
    llm.chat(messages())
    assert sdk.calls[0]['request']['model']=='custom-nvidia-model'
    assert sdk.calls[0]['config']['base_url']=='https://nvidia.example/v1'
    assert sdk.calls[0]['config']['api_key']=='controlled-nvidia-key'


@pytest.mark.parametrize('value',['0','-1','nan','inf','slow'])
def test_invalid_timeout_is_rejected_before_any_request(sdk, monkeypatch, value):
    monkeypatch.setenv('STOA_LLM_TIMEOUT_SECONDS',value)
    with pytest.raises(llm.LLMError,match='STOA_LLM_TIMEOUT_SECONDS'):
        llm.chat(messages())
    assert not sdk.calls


@pytest.mark.parametrize('secondary,key,model', [
    ('modal','controlled-modal-key',MODAL_MODEL),
    ('featherless','controlled-featherless-key','featherless-model'),
])
def test_timeout_falls_through_once_to_chosen_provider_with_accurate_provenance(sdk, monkeypatch, secondary, key, model):
    monkeypatch.setenv('STOA_LLM_FALLBACK', secondary)
    sdk.handler = fail_nvidia
    reply = llm.chat(messages())
    assert str(reply) == 'secondary answer' and len(sdk.calls) == 2
    assert sdk.calls[1]['config']['api_key'] == key
    assert sdk.calls[1]['request']['model'] == model
    assert reply.provenance == {'provider':secondary,'model':model,'cached':False,
                                'fallback_from':'nvidia','fallback_reason':'timeout'}
    assert '2 calls' in llm.usage()


@pytest.mark.parametrize('status,error_class', [(401,openai.AuthenticationError), (429,openai.RateLimitError), (503,openai.InternalServerError)])
def test_non_timeout_api_errors_do_not_fall_through(sdk, status, error_class):
    def fail(config, request):
        raise error_class('controlled failure', response=httpx.Response(status,request=httpx.Request('POST', NVIDIA_BASE)),body={})
    sdk.handler = fail
    with pytest.raises(llm.LLMError):
        llm.chat(messages())
    assert len(sdk.calls) == 1


@pytest.mark.parametrize('status', [408,504])
def test_http_timeout_status_can_use_secondary(sdk, status):
    def fail(config, request):
        if config['base_url'] == NVIDIA_BASE:
            raise openai.APIStatusError('controlled timeout',response=httpx.Response(status,request=httpx.Request('POST', NVIDIA_BASE)),body={})
        return 'secondary answer'
    sdk.handler = fail
    assert llm.chat(messages()) == 'secondary answer'
    assert len(sdk.calls) == 2


def test_connection_failure_is_not_a_timeout(sdk):
    def fail(config, request):
        raise openai.APIConnectionError(request=httpx.Request('POST', NVIDIA_BASE))
    sdk.handler = fail
    with pytest.raises(llm.LLMError):
        llm.chat(messages())
    assert len(sdk.calls) == 1


def test_secondary_timeout_stops_after_two_attempts(sdk):
    sdk.handler = lambda *args: (_ for _ in ()).throw(timeout())
    with pytest.raises(llm.LLMError, match='timed out'):
        llm.chat(messages())
    assert len(sdk.calls) == 2


@pytest.mark.parametrize('provider,secondary', [('nvidia','none'),('modal','featherless')])
def test_disabled_or_non_nvidia_primary_does_not_fall_through(sdk, monkeypatch, provider, secondary):
    monkeypatch.setenv('STOA_LLM_PROVIDER',provider)
    monkeypatch.setenv('STOA_LLM_FALLBACK',secondary)
    sdk.handler = lambda *args: (_ for _ in ()).throw(timeout())
    with pytest.raises(llm.LLMError, match='timed out'):
        llm.chat(messages())
    assert len(sdk.calls) == 1


def test_fallback_respects_shared_live_request_cap(sdk, monkeypatch):
    monkeypatch.setenv('STOA_LLM_MAX_REQUESTS','1')
    sdk.handler = fail_nvidia
    with pytest.raises(llm.LLMError, match='request cap'):
        llm.chat(messages())
    assert len(sdk.calls) == 1


def test_cached_secondary_remains_free_after_primary_timeout(sdk, monkeypatch):
    monkeypatch.setenv('STOA_LLM_PROVIDER','modal')
    assert llm.chat(messages()) == 'ok'
    monkeypatch.setenv('STOA_LLM_PROVIDER','nvidia')
    monkeypatch.setenv('STOA_LLM_MAX_REQUESTS','1')
    llm.reset_usage()
    sdk.handler = fail_nvidia
    reply=llm.chat(messages())
    assert reply == 'ok' and reply.provenance['provider'] == 'modal' and reply.provenance['cached']
    assert len(sdk.calls) == 2 and '1 calls' in llm.usage()


def test_fallback_cache_never_masquerades_as_nvidia_and_nvidia_cache_is_free(sdk):
    sdk.handler=fail_nvidia
    assert llm.chat(messages()).provenance['provider']=='modal'
    sdk.handler=lambda *args:'nvidia recovered'
    reply=llm.chat(messages())
    assert reply=='nvidia recovered' and reply.provenance['provider']=='nvidia'
    assert len(sdk.calls)==3
    assert llm.chat(messages()).provenance['cached']
    assert len(sdk.calls)==3


def test_completion_remains_compatible_with_legacy_answer_export(sdk):
    from dataclasses import asdict
    from stoa.answer import Answer
    sdk.handler=fail_nvidia
    reply=llm.chat(messages())
    exported=asdict(Answer(reply))['value']
    assert exported=='secondary answer'
    assert exported.provenance==reply.provenance


def test_missing_nvidia_key_does_not_use_another_provider_key_or_fallback(sdk, monkeypatch):
    monkeypatch.delenv('NVIDIA_API_KEY')
    with pytest.raises(llm.LLMError,match='NVIDIA_API_KEY'):
        llm.chat(messages())
    assert not sdk.calls


def test_missing_secondary_key_is_explicit_after_timeout(sdk, monkeypatch):
    monkeypatch.delenv('MODAL_API_KEY')
    sdk.handler=fail_nvidia
    with pytest.raises(llm.LLMError,match='MODAL_API_KEY'):
        llm.chat(messages())
    assert len(sdk.calls)==1


def test_fallback_provider_metadata_persists_through_chat_api(sdk, tmp_path):
    from chat.test_chat_api import running, request, png
    def extract(config, completion):
        if config['base_url']==NVIDIA_BASE:
            raise timeout()
        payload=json.loads(completion['messages'][-1]['content'][0]['text'])
        return json.dumps({'operation':'text','complete':True,'coverage':payload['required_coverage'],
                           'facts':[{'kind':'text','value':'TEST','page_ref':payload['pages'][0]['id'],'bbox':[1,1,8,8]}]})
    sdk.handler=extract
    with running(tmp_path/'chat') as base:
        path='/chats/'+request(base,'/chats','POST',{})[1]['id']
        drawing=request(base,path+'/uploads?filename=generated.png','POST',png())[1]
        answer=request(base,path+'/questions','POST',{'question':'What word is printed?','drawing_ids':[drawing['id']]})[1]['answer']
        assert answer['value']=='TEST'
        provenance=answer['model_provenance']
        assert provenance['provider']=='modal' and provenance['model']==MODAL_MODEL
        assert provenance['fallback_from']=='nvidia' and provenance['fallback_reason']=='timeout'
        assert request(base,path)[1]['messages'][-1]['answer']['model_provenance']==provenance
