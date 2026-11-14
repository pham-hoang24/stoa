from types import SimpleNamespace
import os

import pytest

from stoa.lanes import llm

ENV_LOADER = llm._env


@pytest.fixture
def transport(monkeypatch, tmp_path):
    import openai
    # dotenv adds variables directly; keep those additions local to this test.
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    for name in ('STOA_LLM_PROVIDER', 'MODAL_API_KEY', 'STOA_MODAL_BASE_URL', 'STOA_MODAL_MODEL',
                 'STOA_LLM_MODEL', 'STOA_LLM_BASE_URL', 'FEATHERLESS_API_KEY', 'STOA_LLM_MAX_REQUESTS',
                 'NVIDIA_API_KEY', 'STOA_NVIDIA_MODEL', 'STOA_NVIDIA_BASE_URL', 'STOA_LLM_FALLBACK', 'STOA_LLM_TIMEOUT_SECONDS'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('STOA_LLM_API_KEY', 'controlled-featherless-key')
    monkeypatch.setattr(llm, '_env', lambda: None)
    monkeypatch.setattr(llm, 'CACHE', tmp_path / 'cache')
    llm.reset_usage()
    calls = []

    def client(**config):
        def create(**request):
            calls.append({'config': config, 'request': request})
            return SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(openai, 'OpenAI', client)
    return calls


def messages():
    return [{'role': 'user', 'content': 'Configuration test.'}]


def test_modal_preset_uses_modal_key_model_and_endpoint_not_featherless_config(transport, monkeypatch):
    monkeypatch.setenv('STOA_LLM_PROVIDER', 'modal')
    monkeypatch.setenv('MODAL_API_KEY', 'controlled-modal-key')
    monkeypatch.setenv('STOA_LLM_MODEL', 'old-featherless-model')
    monkeypatch.setenv('STOA_LLM_BASE_URL', 'https://featherless.example/v1')
    assert llm.chat(messages()) == '{"ok":true}'
    assert transport[0]['config']['base_url'] == 'https://uknowme1928--ep-stoa-server.us-west.modal.direct/v1'
    assert transport[0]['config']['api_key'] == 'controlled-modal-key'
    assert transport[0]['request']['model'] == 'Qwen/Qwen3.8-Max-VL-Thinking'
    assert transport[0]['config']['max_retries'] == 0


def test_modal_requires_its_own_key_even_if_featherless_key_exists(transport, monkeypatch):
    monkeypatch.setenv('STOA_LLM_PROVIDER', 'modal')
    with pytest.raises(llm.LLMError, match='MODAL_API_KEY'):
        llm.chat(messages())
    assert not transport


def test_modal_overrides_are_read_at_call_time_and_normalize_api_prefix(transport, monkeypatch):
    monkeypatch.setenv('STOA_LLM_PROVIDER', 'modal')
    monkeypatch.setenv('MODAL_API_KEY', 'controlled-modal-key')
    monkeypatch.setenv('STOA_MODAL_BASE_URL', 'https://modal.example/')
    monkeypatch.setenv('STOA_MODAL_MODEL', 'custom-model')
    llm.chat(messages())
    assert transport[0]['config']['base_url'] == 'https://modal.example/v1'
    assert transport[0]['request']['model'] == 'custom-model'
    monkeypatch.setenv('STOA_MODAL_BASE_URL', 'https://modal.example/v1/')
    llm.chat(messages())
    assert len(transport) == 1


def test_cache_is_separated_by_provider_and_endpoint(transport, monkeypatch):
    monkeypatch.setenv('STOA_LLM_PROVIDER', 'modal')
    monkeypatch.setenv('MODAL_API_KEY', 'controlled-modal-key')
    monkeypatch.setenv('STOA_MODAL_MODEL', 'same-model')
    monkeypatch.setenv('STOA_LLM_MODEL', 'same-model')
    llm.chat(messages())
    monkeypatch.setenv('STOA_MODAL_BASE_URL', 'https://another-modal.example/v1')
    llm.chat(messages())
    monkeypatch.setenv('STOA_LLM_PROVIDER', 'featherless')
    llm.chat(messages())
    assert len(transport) == 3
    monkeypatch.setenv('STOA_LLM_PROVIDER', 'modal')
    llm.chat(messages())
    assert len(transport) == 3


def test_unknown_provider_is_a_clear_configuration_error(transport, monkeypatch):
    monkeypatch.setenv('STOA_LLM_PROVIDER', 'typo')
    with pytest.raises(llm.LLMError, match='provider'):
        llm.chat(messages())
    assert not transport


def test_quoted_modal_key_from_dotenv_and_explicit_provider_precedence(transport, monkeypatch, tmp_path):
    monkeypatch.setattr(llm, '_env', ENV_LOADER)
    monkeypatch.setattr(llm, 'REPO', tmp_path)
    (tmp_path / '.env').write_text("STOA_LLM_PROVIDER=modal\nMODAL_API_KEY='controlled-quoted-key'\n")
    llm.chat(messages())
    assert transport[0]['config']['api_key'] == 'controlled-quoted-key'
    monkeypatch.setenv('STOA_LLM_PROVIDER', 'featherless')
    assert llm.settings()['provider'] == 'featherless'
