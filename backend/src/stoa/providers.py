"""Provider presets and credential boundaries for the shared LLM transport."""
import os
from urllib.parse import urlsplit

MODAL_BASE = 'https://uknowme1928--ep-stoa-server.us-west.modal.direct/v1'
MODAL_MODEL = 'Qwen/Qwen3.8-Max-VL-Thinking'


def configuration(default_model, default_base, default_max_requests):
    """Resolve the selected provider from the environment at call time.

    Generic STOA_LLM_* endpoint/model/key overrides retain their existing
    Featherless behavior. Modal uses its own namespace so an existing .env
    cannot accidentally send a Featherless credential or model to Modal.
    """
    provider = os.environ.get('STOA_LLM_PROVIDER', 'featherless').strip().lower()
    if provider == 'modal':
        base = os.environ.get('STOA_MODAL_BASE_URL', MODAL_BASE).rstrip('/')
        parsed = urlsplit(base)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            raise ValueError('STOA_MODAL_BASE_URL must be an HTTP(S) endpoint')
        if not parsed.path:
            base += '/v1'
        model = os.environ.get('STOA_MODAL_MODEL', MODAL_MODEL)
        key = os.environ.get('MODAL_API_KEY')
        key_env = 'MODAL_API_KEY'
    elif provider == 'featherless':
        base = os.environ.get('STOA_LLM_BASE_URL', default_base)
        model = os.environ.get('STOA_LLM_MODEL', default_model)
        key = os.environ.get('STOA_LLM_API_KEY') or os.environ.get('FEATHERLESS_API_KEY')
        key_env = 'STOA_LLM_API_KEY or FEATHERLESS_API_KEY'
    else:
        raise ValueError(f'Unknown LLM provider {provider!r}; choose featherless or modal')
    return {'provider': provider, 'base_url': base, 'model': model, 'api_key': key,
            'api_key_env': key_env,
            'max_requests': int(os.environ.get('STOA_LLM_MAX_REQUESTS', default_max_requests))}
