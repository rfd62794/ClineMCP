"""Tests for MCP tool handlers — 10 tests from SDD §11."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clinemcp.mcp.tools import cline_cancel, cline_complete, cline_output, cline_start, cline_status


class TestClineStart:
    """Tests for cline_start tool."""

    @pytest.mark.asyncio
    async def test_cline_start_returns_session_id(self):
        """Verify cline_start returns valid session_id."""
        with patch("clinemcp.sessions.SessionStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.get_active_session = AsyncMock(return_value=None)
            mock_store.create_session = AsyncMock()
            mock_store_class.return_value = mock_store

            result = await cline_start("echo hello", "qwen2.5-coder:7b")
            data = json.loads(result)

            assert data["session_id"] is not None
            assert len(data["session_id"]) == 36  # UUID length
            assert data["status"] == "running"
            assert data["error"] is None

    @pytest.mark.asyncio
    async def test_cline_start_errors_when_session_already_running(self):
        """Verify error when session already running."""
        with patch("clinemcp.sessions.SessionStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.get_active_session = AsyncMock(
                return_value={"session_id": "existing-123"}
            )
            mock_store_class.return_value = mock_store

            result = await cline_start("echo hello", "qwen2.5-coder:7b")
            data = json.loads(result)

            assert data["error"] == "Session already running: existing-123"
            assert data["session_id"] is None


class TestClineStatus:
    """Tests for cline_status tool."""

    @pytest.mark.asyncio
    async def test_cline_status_returns_running_for_active(self):
        """Verify status returned for active session."""
        with patch("clinemcp.sessions.SessionStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.get_session = AsyncMock(
                return_value={
                    "session_id": "test-123",
                    "status": "running",
                    "started_at": "2024-01-01T00:00:00+00:00",
                    "output": "some output",
                    "error": None,
                }
            )
            mock_store_class.return_value = mock_store

            result = await cline_status("test-123")
            data = json.loads(result)

            assert data["session_id"] == "test-123"
            assert data["status"] == "running"
            assert "elapsed_seconds" in data

    @pytest.mark.asyncio
    async def test_cline_status_returns_not_found_for_unknown(self):
        """Verify not_found status for unknown session."""
        with patch("clinemcp.sessions.SessionStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.get_session = AsyncMock(return_value=None)
            mock_store_class.return_value = mock_store

            result = await cline_status("unknown-id")
            data = json.loads(result)

            assert data["status"] == "not_found"
            assert data["error"] == "Session not found"


class TestClineComplete:
    """Tests for cline_complete tool."""

    @pytest.mark.asyncio
    async def test_cline_complete_marks_session_completion_signaled(self):
        """Verify session marked completion_signaled."""
        with patch("clinemcp.sessions.SessionStore") as mock_store_class, patch(
            "clinemcp.telegram.send_message", return_value=True
        ):
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.update_session = AsyncMock(return_value=True)
            mock_store_class.return_value = mock_store

            result = await cline_complete("test-123", 5, "42/0/0")
            data = json.loads(result)

            assert data["success"] is True
            assert data["step_id"] == 5
            assert data["floor_result"] == "42/0/0"

    @pytest.mark.asyncio
    async def test_cline_complete_sends_telegram(self):
        """Verify Telegram message sent on complete."""
        with patch("clinemcp.sessions.SessionStore") as mock_store_class, patch(
            "clinemcp.telegram.send_message", return_value=True
        ) as mock_send:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.update_session = AsyncMock(return_value=True)
            mock_store_class.return_value = mock_store

            result = await cline_complete("test-123", 3, "100/0/0")
            data = json.loads(result)

            assert data["telegram_sent"] is True
            mock_send.assert_called_once()
            call_args = mock_send.call_args[0][0]
            assert "Step 3 complete" in call_args
            assert "100/0/0" in call_args


class TestClineCancel:
    """Tests for cline_cancel tool."""

    @pytest.mark.asyncio
    async def test_cline_cancel_returns_cancelled_true(self):
        """Verify cancel returns cancelled: true."""
        with patch("clinemcp.sessions.SessionStore") as mock_store_class, patch(
            "clinemcp.runner.cancel_session", return_value=True
        ):
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store_class.return_value = mock_store

            result = await cline_cancel("test-123")
            data = json.loads(result)

            assert data["cancelled"] is True
            assert data["was_running"] is True

    @pytest.mark.asyncio
    async def test_cline_cancel_returns_false_when_not_running(self):
        """Verify cancel returns was_running: false when not active."""
        with patch("clinemcp.sessions.SessionStore") as mock_store_class, patch(
            "clinemcp.runner.cancel_session", return_value=False
        ):
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store_class.return_value = mock_store

            result = await cline_cancel("test-123")
            data = json.loads(result)

            assert data["cancelled"] is True
            assert data["was_running"] is False


class TestClineOutput:
    """Tests for cline_output tool."""

    @pytest.mark.asyncio
    async def test_cline_output_returns_full_output(self):
        """Verify full output returned."""
        with patch("clinemcp.sessions.SessionStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.get_session = AsyncMock(
                return_value={
                    "session_id": "test-123",
                    "status": "complete",
                    "output": "full output here",
                    "exit_code": 0,
                    "floor_result": "50/0/0",
                }
            )
            mock_store_class.return_value = mock_store

            result = await cline_output("test-123")
            data = json.loads(result)

            assert data["output"] == "full output here"
            assert data["exit_code"] == 0
            assert data["floor_result"] == "50/0/0"

    @pytest.mark.asyncio
    async def test_cline_output_returns_error_for_unknown_session(self):
        """Verify error for unknown session."""
        with patch("clinemcp.sessions.SessionStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.get_session = AsyncMock(return_value=None)
            mock_store_class.return_value = mock_store

            result = await cline_output("unknown-id")
            data = json.loads(result)

            assert data["status"] == "not_found"
            assert data["output"] == ""
