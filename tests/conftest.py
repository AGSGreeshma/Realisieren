"""Shared pytest configuration.

The important thing here is the no_network fixture: it makes every test in the
suite fail loudly if it tries to open a socket. That is what lets us claim the
test suite is genuinely offline, rather than merely believing it is.
"""

from __future__ import annotations

import pathlib
import socket

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class NetworkBlockedError(RuntimeError):
    """Raised when a test tries to reach the network."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block all real socket connections for the duration of every test.

    autouse=True means no test has to ask for this; it applies to the whole
    suite. monkeypatch undoes it automatically when the test finishes, so the
    patch cannot leak into other processes or later sessions.
    """

    def blocked(*args, **kwargs):
        raise NetworkBlockedError(
            "This test tried to use the network. Tests must run offline - "
            "use a fixture from tests/fixtures/ or a mock instead."
        )

    # Everything in requests/urllib3 eventually calls one of these
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def fixtures_dir() -> pathlib.Path:
    """Path to the saved HTML fixtures."""
    return FIXTURES


def load_fixture(name: str) -> str:
    """Read one saved HTML fixture as text."""
    return (FIXTURES / name).read_text(encoding="utf-8")
