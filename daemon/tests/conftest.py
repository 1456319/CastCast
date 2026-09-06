"""Tests must not start an external SSH tunnel."""
import pytest


@pytest.fixture(autouse=True)
def disable_external_tunnel(monkeypatch):
    monkeypatch.setenv("CASTCAST_DISABLE_TUNNEL", "1")
