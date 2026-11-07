import socket

import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Réseau interdit dans les tests de sécurité")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    for name in (
        "HAI_API_KEY",
        "HAI_API_KEY_2",
        "LINKUP_API_KEY",
        "LINKUP_API_KEY_2",
        "GLADIA_API_KEY",
        "GLADIA_API_KEY_2",
        "RUNAI_MODE",
        "RUNAI_DEMO",
    ):
        monkeypatch.delenv(name, raising=False)
