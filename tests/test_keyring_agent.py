"""Tests for keyring agent protocol handlers."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "keyring-agent"))

from agent import handle_request


class TestStoreHandler:
    @patch("agent.subprocess.run")
    def test_store_calls_secret_tool(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = handle_request({"action": "store", "type": "m2m", "key": "username", "value": "testuser"})
        assert result["ok"] is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "secret-tool"
        assert "store" in cmd

    @patch("agent.subprocess.run")
    def test_store_passes_value_via_stdin(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        handle_request({"action": "store", "type": "m2m", "key": "token", "value": "secret123"})
        kwargs = mock_run.call_args[1]
        assert kwargs["input"] == "secret123"

    @patch("agent.subprocess.run")
    def test_store_includes_correct_attributes(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        handle_request({"action": "store", "type": "copernicus", "key": "password", "value": "pw"})
        cmd = mock_run.call_args[0][0]
        # Check attribute pairs
        assert "application" in cmd and "geographica" in cmd
        assert "credential_type" in cmd and "copernicus" in cmd
        assert "key" in cmd and "password" in cmd

    @patch("agent.subprocess.run")
    def test_store_missing_fields_returns_error(self, mock_run):
        result = handle_request({"action": "store", "type": "m2m"})
        assert result["ok"] is False
        assert "error" in result
        mock_run.assert_not_called()

    @patch("agent.subprocess.run")
    def test_store_unknown_type_returns_error(self, mock_run):
        result = handle_request({"action": "store", "type": "invalid", "key": "x", "value": "y"})
        assert result["ok"] is False
        assert "unknown" in result["error"]
        mock_run.assert_not_called()

    @patch("agent.subprocess.run")
    def test_store_failure_returns_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        result = handle_request({"action": "store", "type": "m2m", "key": "username", "value": "x"})
        assert result["ok"] is False


class TestLookupHandler:
    @patch("agent.subprocess.run")
    def test_lookup_returns_value(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="my_secret_value")
        result = handle_request({"action": "lookup", "type": "m2m", "key": "token"})
        assert result["ok"] is True
        assert result["value"] == "my_secret_value"

    @patch("agent.subprocess.run")
    def test_lookup_strips_trailing_newline(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="value\n")
        result = handle_request({"action": "lookup", "type": "m2m", "key": "token"})
        assert result["value"] == "value"

    @patch("agent.subprocess.run")
    def test_lookup_not_found(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="No such secret")
        result = handle_request({"action": "lookup", "type": "m2m", "key": "token"})
        assert result["ok"] is False
        assert result["error"] == "not_found"

    @patch("agent.subprocess.run")
    def test_lookup_missing_fields(self, mock_run):
        result = handle_request({"action": "lookup", "type": "m2m"})
        assert result["ok"] is False
        mock_run.assert_not_called()


class TestDeleteHandler:
    @patch("agent.subprocess.run")
    def test_delete_calls_clear_for_all_keys(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = handle_request({"action": "delete", "type": "m2m"})
        assert result["ok"] is True
        # m2m has username + token, so 2 calls
        assert mock_run.call_count == 2

    @patch("agent.subprocess.run")
    def test_delete_copernicus_clears_two_keys(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = handle_request({"action": "delete", "type": "copernicus"})
        assert result["ok"] is True
        assert mock_run.call_count == 2

    @patch("agent.subprocess.run")
    def test_delete_invalid_type(self, mock_run):
        result = handle_request({"action": "delete", "type": "bogus"})
        assert result["ok"] is False
        mock_run.assert_not_called()


class TestStatusHandler:
    @patch("agent.subprocess.run")
    def test_status_detects_configured(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="value")
        result = handle_request({"action": "status"})
        assert result["ok"] is True
        assert result["m2m_configured"] is True
        assert result["copernicus_configured"] is True
        assert result["keyring_available"] is True

    @patch("agent.subprocess.run")
    def test_status_detects_not_configured(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="No such secret")
        result = handle_request({"action": "status"})
        assert result["ok"] is True
        assert result["m2m_configured"] is False
        assert result["copernicus_configured"] is False

    @patch("agent.subprocess.run")
    def test_status_detects_keyring_locked(self, mock_run):
        mock_run.side_effect = Exception("Cannot autolaunch D-Bus")
        result = handle_request({"action": "status"})
        assert result["ok"] is False
        assert result["error"] == "keyring_unavailable"
        assert result["keyring_available"] is False


class TestPrepareSecrets:
    @patch("agent.subprocess.run")
    def test_prepare_writes_tmpfs_file(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="test_value")
        with patch("agent.SECRETS_DIR", tmp_path):
            result = handle_request({"action": "prepare_secrets", "types": ["m2m"], "session_id": "test123"})
        assert result["ok"] is True
        secret_file = tmp_path / "test123.json"
        assert secret_file.exists()
        creds = json.loads(secret_file.read_text())
        assert "m2m_username" in creds
        assert "m2m_token" in creds

    @patch("agent.subprocess.run")
    def test_prepare_sets_restrictive_permissions(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="val")
        with patch("agent.SECRETS_DIR", tmp_path):
            handle_request({"action": "prepare_secrets", "types": ["m2m"], "session_id": "perm_test"})
        secret_file = tmp_path / "perm_test.json"
        perms = oct(secret_file.stat().st_mode & 0o777)
        assert perms == "0o600"

    @patch("agent.subprocess.run")
    def test_prepare_missing_session_id(self, mock_run):
        result = handle_request({"action": "prepare_secrets", "types": ["m2m"]})
        assert result["ok"] is False

    @patch("agent.subprocess.run")
    def test_prepare_multiple_types(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="val")
        with patch("agent.SECRETS_DIR", tmp_path):
            result = handle_request({"action": "prepare_secrets", "types": ["m2m", "copernicus"], "session_id": "multi"})
        assert result["ok"] is True
        creds = json.loads((tmp_path / "multi.json").read_text())
        assert "m2m_username" in creds
        assert "copernicus_username" in creds

    @patch("agent.subprocess.run")
    def test_cleanup_deletes_file(self, mock_run, tmp_path):
        secret_file = tmp_path / "test123.json"
        secret_file.write_text('{"m2m_username": "x"}')
        with patch("agent.SECRETS_DIR", tmp_path):
            result = handle_request({"action": "cleanup_secrets", "session_id": "test123"})
        assert result["ok"] is True
        assert not secret_file.exists()

    @patch("agent.subprocess.run")
    def test_cleanup_nonexistent_file_succeeds(self, mock_run, tmp_path):
        with patch("agent.SECRETS_DIR", tmp_path):
            result = handle_request({"action": "cleanup_secrets", "session_id": "nonexistent"})
        assert result["ok"] is True

    @patch("agent.subprocess.run")
    def test_cleanup_missing_session_id(self, mock_run):
        result = handle_request({"action": "cleanup_secrets"})
        assert result["ok"] is False


class TestUnknownAction:
    def test_unknown_action_returns_error(self):
        result = handle_request({"action": "nonexistent"})
        assert result["ok"] is False

    def test_missing_action_returns_error(self):
        result = handle_request({})
        assert result["ok"] is False


class TestMigration:
    @patch("agent.subprocess.run")
    def test_migrate_imports_and_deletes(self, mock_run, tmp_path):
        from agent import _migrate_json_credentials
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps({"m2m_username": "user1", "m2m_token": "tok1"}))
        mock_run.return_value = MagicMock(returncode=0)
        with patch("agent._MIGRATION_PATHS", [creds_file]):
            _migrate_json_credentials()
        # Should have called secret-tool store twice (username + token)
        assert mock_run.call_count == 2
        # File should be deleted
        assert not creds_file.exists()

    @patch("agent.subprocess.run")
    def test_migrate_skips_missing_file(self, mock_run, tmp_path):
        from agent import _migrate_json_credentials
        nonexistent = tmp_path / ".credentials.json"
        with patch("agent._MIGRATION_PATHS", [nonexistent]):
            _migrate_json_credentials()
        mock_run.assert_not_called()
