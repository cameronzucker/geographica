"""Tests for keyring client — mock the socket layer."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

import keyring_client


def _mock_request(response: dict):
    """Return a patch that makes _request return the given response."""
    return patch.object(keyring_client, "_request", return_value=response)


class TestStoreCredential:
    def test_store_sends_correct_request(self):
        with _mock_request({"ok": True}) as mock:
            result = keyring_client.store_credential("m2m", "username", "testuser")
        assert result is True
        mock.assert_called_once_with({
            "action": "store", "type": "m2m", "key": "username", "value": "testuser"
        })

    def test_store_returns_false_on_error(self):
        with _mock_request({"ok": False, "error": "failed"}):
            result = keyring_client.store_credential("m2m", "username", "x")
        assert result is False


class TestLookupCredential:
    def test_lookup_returns_value(self):
        with _mock_request({"ok": True, "value": "my_secret"}) as mock:
            result = keyring_client.lookup_credential("m2m", "token")
        assert result == "my_secret"
        mock.assert_called_once_with({
            "action": "lookup", "type": "m2m", "key": "token"
        })

    def test_lookup_returns_none_on_error(self):
        with _mock_request({"ok": False, "error": "not_found"}):
            result = keyring_client.lookup_credential("m2m", "token")
        assert result is None


class TestGetStatus:
    def test_status_returns_configured(self):
        with _mock_request({"ok": True, "m2m_configured": True,
                           "copernicus_configured": False, "keyring_available": True}):
            result = keyring_client.get_status()
        assert result["m2m_configured"] is True
        assert result["copernicus_configured"] is False
        assert result["keyring_available"] is True

    def test_status_agent_unavailable(self):
        with _mock_request({"ok": False, "error": "agent_unavailable"}):
            result = keyring_client.get_status()
        assert result["keyring_available"] is False
        assert result["m2m_configured"] is False
        assert result["copernicus_configured"] is False


class TestPrepareSecrets:
    def test_prepare_returns_path(self):
        with _mock_request({"ok": True, "path": "/run/geographica/secrets/abc.json"}) as mock:
            path = keyring_client.prepare_secrets(["m2m"], "abc")
        assert path == "/run/geographica/secrets/abc.json"
        mock.assert_called_once_with({
            "action": "prepare_secrets", "types": ["m2m"], "session_id": "abc"
        })

    def test_prepare_returns_none_on_error(self):
        with _mock_request({"ok": False, "error": "no credentials"}):
            path = keyring_client.prepare_secrets(["m2m"], "abc")
        assert path is None


class TestCleanupSecrets:
    def test_cleanup_sends_correct_request(self):
        with _mock_request({"ok": True}) as mock:
            keyring_client.cleanup_secrets("abc")
        mock.assert_called_once_with({"action": "cleanup_secrets", "session_id": "abc"})


class TestDeleteCredentials:
    def test_delete_sends_correct_request(self):
        with _mock_request({"ok": True}) as mock:
            result = keyring_client.delete_credentials("m2m")
        assert result is True
        mock.assert_called_once_with({"action": "delete", "type": "m2m"})

    def test_delete_returns_false_on_error(self):
        with _mock_request({"ok": False, "error": "failed"}):
            result = keyring_client.delete_credentials("m2m")
        assert result is False
