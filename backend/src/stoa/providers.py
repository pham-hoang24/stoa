"""Provider presets and credential boundaries for the shared LLM transport."""
import os
import math
from urllib.parse import urlsplit

MODAL_BASE = 'https://uknowme1928--ep-stoa-server.us-west.modal.direct/v1'
MODAL_MODEL = 'Qwen/Qwen3.8-Max-VL-Thinking'
NVIDIA_BASE = 'https://integrate.api.nvidia.com/v1'
NVIDIA_MODEL = 'nvidia/nemotron-3.5-super-vl-120b-a12b'


def _api_base(value, variable):
    base = value.rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError(f'{variable} must be an HTTP(S) endpoint')
    return base if parsed.path else base + '/v1'


def configuration(default_model, default_base, default_max_requests, provider=None):
    """Resolve the selected provider from the environment at call time.

    NVIDIA is the default. Provider-specific namespaces prevent a configured
    Featherless credential or model from being sent to NVIDIA or Modal.
    """
    provider = (provider or os.environ.get('STOA_LLM_PROVIDER', 'nvidia')).strip().lower()
    if provider == 'nvidia':
        base = _api_base(os.environ.get('STOA_NVIDIA_BASE_URL', NVIDIA_BASE), 'STOA_NVIDIA_BASE_URL')
        model = os.environ.get('STOA_NVIDIA_MODEL', NVIDIA_MODEL)
        key = os.environ.get('NVIDIA_API_KEY')
        key_env = 'NVIDIA_API_KEY'
    elif provider == 'modal':
        base = _api_base(os.environ.get('STOA_MODAL_BASE_URL', MODAL_BASE), 'STOA_MODAL_BASE_URL')
        model = os.environ.get('STOA_MODAL_MODEL', MODAL_MODEL)
        key = os.environ.get('MODAL_API_KEY')
        key_env = 'MODAL_API_KEY'
    elif provider == 'featherless':
        base = os.environ.get('STOA_LLM_BASE_URL', default_base)
        model = os.environ.get('STOA_LLM_MODEL', default_model)
        key = os.environ.get('STOA_LLM_API_KEY') or os.environ.get('FEATHERLESS_API_KEY')
        key_env = 'STOA_LLM_API_KEY or FEATHERLESS_API_KEY'
    else:
        raise ValueError(f'Unknown LLM provider {provider!r}; choose nvidia, featherless or modal')
    try:
        timeout = float(os.environ.get('STOA_LLM_TIMEOUT_SECONDS', '60'))
    except ValueError as exc:
        raise ValueError('STOA_LLM_TIMEOUT_SECONDS must be positive and finite') from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('STOA_LLM_TIMEOUT_SECONDS must be positive and finite')
    fallback = None
    if provider == 'nvidia':
        fallback = os.environ.get('STOA_LLM_FALLBACK', 'modal').strip().lower()
        if fallback not in {'modal', 'featherless', 'none'}:
            raise ValueError('STOA_LLM_FALLBACK must be modal, featherless or none')
        if fallback == 'none':
            fallback = None
    return {'provider': provider, 'base_url': base, 'model': model, 'api_key': key,
            'api_key_env': key_env, 'timeout_seconds': timeout, 'fallback_provider': fallback,
            'max_requests': int(os.environ.get('STOA_LLM_MAX_REQUESTS', default_max_requests))}
