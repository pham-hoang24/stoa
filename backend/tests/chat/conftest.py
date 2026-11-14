"""Every public-API test substitutes the external provider; no live billing."""
import pytest


@pytest.fixture(autouse=True)
def controlled_provider(monkeypatch):
    from stoa.lanes import llm
    def unavailable(*args, **kwargs):
        raise llm.LLMError('no API key: controlled test provider')
    monkeypatch.setattr(llm, 'chat', unavailable)


@pytest.fixture(autouse=True)
def ocr_off_by_default(monkeypatch):
    """The chat suite is engine-independent; OCR tests opt in explicitly."""
    monkeypatch.setenv('STOA_OCR', 'off')
