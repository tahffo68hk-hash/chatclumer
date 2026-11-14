import pytest


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setenv("DEMO_CHUNK_DELAY", "0")
    monkeypatch.delenv("ALLOW_PAID_PROVIDERS", raising=False)
