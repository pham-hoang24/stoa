"""Every public-API test substitutes the external provider; no live billing."""
import pytest


@pytest.fixture(autouse=True)
def controlled_provider(monkeypatch):
    from stoa.lanes import llm
    def unavailable(*args, **kwargs):
        raise llm.LLMError('no API key: controlled test provider')
    monkeypatch.setattr(llm, 'chat', unavailable)
