"""Suite-wide guards."""
import pytest

from app.services import sofascore

# The real ones, for the tests that exercise them against a fake store.
REAL_SAVE_BREAKER = sofascore._save_breaker


@pytest.fixture(autouse=True)
def _sofascore_breaker_in_memory(monkeypatch):
    """The 403 breaker mirrors itself into app_settings. A test driving _get
    must not read or write whatever database the environment points at."""
    monkeypatch.setattr(sofascore, "_breaker_loaded", True)

    async def _no_save(cooldown):
        return None
    monkeypatch.setattr(sofascore, "_save_breaker", _no_save)
