"""Pre-Phase-6 audit S2: regression tests for ``MackolikClient`` resource cleanup.

The client owns a ``requests.Session``; long-lived scrape jobs that
forgot ``with`` were leaking sockets. We now expose ``close()`` and
the context-manager protocol.
"""
from __future__ import annotations

from unittest.mock import patch

from scraper.mackolik import MackolikClient


def test_close_closes_session():
    client = MackolikClient()
    with patch.object(client._session, "close") as mock_close:
        client.close()
    mock_close.assert_called_once()


def test_close_is_idempotent():
    client = MackolikClient()
    client.close()
    # Second call must not raise.
    client.close()


def test_context_manager_closes_on_exit():
    closed: list[bool] = []
    with MackolikClient() as client:
        original_close = client._session.close

        def _track():
            closed.append(True)
            original_close()

        client._session.close = _track  # type: ignore[assignment]
    assert closed == [True], "session.close() must fire on context-manager exit"


def test_context_manager_returns_self():
    with MackolikClient() as client:
        assert isinstance(client, MackolikClient)
