"""Tests for MCP tool handlers — 10 tests from SDD §11."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clinemcp.mcp.tools import (
    handle_cline_cancel,
    handle_cline_complete,
    handle_cline_output,
    handle_cline_start,
    handle_cline_status,
    handle_cline_tail,
)


class TestClineStart:
    """Tests for cline_start tool."""

    @pytest.mark.asyncio
    async def test_cline_start_returns_session_id(self):
        """Verify cline_start returns valid session_id."""
        with patch("clinemcp.mcp.tools.SessionStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.get_active_session = AsyncMock(return_value=None)
            mock_store.create_session = AsyncMock()
            mock_store_class.return_value = mock_store

            result = await handle_cline_start({
                "task": "echo hello",
                "model": "qwen2.5-coder:7b",
            })
            data = json.loads(result)

            assert data["session_id"] is not None
            assert len(data["session_id"]) == 36  # UUID length
            assert data["status"] == "running"
            assert data["error"] is None

    @pytest.mark.asyncio
    async def test_cline_start_errors_when_session_already_running(self):
        """Verify error when session already running."""
        with patch("clinemcp.mcp.tools.SessionStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.get_active_session = AsyncMock(
                return_value={"session_id": "existing-123"}
            )
            mock_store_class.return_value = mock_store

            result = await handle_cline_start({
                "task": "echo hello",
                "model": "qwen2.5-coder:7b",
            })
            data = json.loads(result)

            assert data["error"] == "Session already running: existing-123"
            assert data["session_id"] is None


class TestClineStatus:
    """Tests for cline_status tool."""

    @pytest.mark.asyncio
    async def test_cline_status_returns_running_for_active(self):
        """Verify status returned for active session."""
        with patch("clinemcp.mcp.tools.SessionStore") as mock_store_class:
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

            result = await handle_cline_status({"session_id": "test-123"})
            data = json.loads(result)

            assert data["session_id"] == "test-123"
            assert data["status"] == "running"
            assert "elapsed_seconds" in data

    @pytest.mark.asyncio
    async def test_cline_status_returns_not_found_for_unknown(self):
        """Verify not_found status for unknown session."""
        with patch("clinemcp.mcp.tools.SessionStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.get_session = AsyncMock(return_value=None)
            mock_store_class.return_value = mock_store

            result = await handle_cline_status({"session_id": "unknown-id"})
            data = json.loads(result)

            assert data["status"] == "not_found"
            assert data["error"] == "Session not found"


class TestClineComplete:
    """Tests for cline_complete tool."""

    @pytest.mark.asyncio
    async def test_cline_complete_marks_session_completion_signaled(self):
        """Verify session marked completion_signaled."""
        with patch("clinemcp.mcp.tools.SessionStore") as mock_store_class, patch(
            "clinemcp.mcp.tools.send_message", return_value=True
        ):
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.update_session = AsyncMock(return_value=True)
            mock_store_class.return_value = mock_store

            result = await handle_cline_complete({
                "session_id": "test-123",
                "step_id": 5,
                "floor_result": "42/0/0",
            })
            data = json.loads(result)

            assert data["success"] is True
            assert data["step_id"] == 5
            assert data["floor_result"] == "42/0/0"

    @pytest.mark.asyncio
    async def test_cline_complete_sends_telegram(self):
        """Verify Telegram message sent on complete."""
        with patch("clinemcp.mcp.tools.SessionStore") as mock_store_class, patch(
            "clinemcp.mcp.tools.send_message", return_value=True
        ) as mock_send:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.update_session = AsyncMock(return_value=True)
            mock_store_class.return_value = mock_store

            result = await handle_cline_complete({
                "session_id": "test-123",
                "step_id": 3,
                "floor_result": "100/0/0",
            })
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
        with patch("clinemcp.mcp.tools.SessionStore") as mock_store_class, patch(
            "clinemcp.mcp.tools.cancel_session", return_value=True
        ):
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store_class.return_value = mock_store

            result = await handle_cline_cancel({"session_id": "test-123"})
            data = json.loads(result)

            assert data["cancelled"] is True
            assert data["was_running"] is True

    @pytest.mark.asyncio
    async def test_cline_cancel_returns_false_when_not_running(self):
        """Verify cancel returns was_running: false when not active."""
        with patch("clinemcp.mcp.tools.SessionStore") as mock_store_class, patch(
            "clinemcp.mcp.tools.cancel_session", return_value=False
        ):
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store_class.return_value = mock_store

            result = await handle_cline_cancel({"session_id": "test-123"})
            data = json.loads(result)

            assert data["cancelled"] is True
            assert data["was_running"] is False


class TestClineOutput:
    """Tests for cline_output tool."""

    @pytest.mark.asyncio
    async def test_cline_output_returns_full_output(self):
        """Verify full output returned."""
        with patch("clinemcp.mcp.tools.SessionStore") as mock_store_class:
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

            result = await handle_cline_output({"session_id": "test-123"})
            data = json.loads(result)

            assert data["output"] == "full output here"
            assert data["exit_code"] == 0
            assert data["floor_result"] == "50/0/0"

    @pytest.mark.asyncio
    async def test_cline_output_returns_error_for_unknown_session(self):
        """Verify error for unknown session."""
        with patch("clinemcp.mcp.tools.SessionStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.get_session = AsyncMock(return_value=None)
            mock_store_class.return_value = mock_store

            result = await handle_cline_output({"session_id": "unknown-id"})
            data = json.loads(result)

            assert data["status"] == "not_found"
            assert data["output"] == ""

    @pytest.mark.asyncio
    async def test_cline_status_includes_iterations_when_available(self):
        """Verify cline_status includes parsed fields when available."""
        with patch("clinemcp.mcp.tools.SessionStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.get_session = AsyncMock(
                return_value={
                    "session_id": "test-123",
                    "status": "complete",
                    "started_at": "2024-01-01T00:00:00+00:00",
                    "iterations": 5,
                    "answer": "The answer is 42",
                    "duration_ms": 15000,
                    "input_tokens": 1000,
                    "output_tokens": 500,
                }
            )
            mock_store_class.return_value = mock_store

            result = await handle_cline_status({"session_id": "test-123"})
            data = json.loads(result)

            assert data["status"] == "complete"
            assert data["iterations"] == 5
            assert data["answer"] == "The answer is 42"
            assert data["duration_ms"] == 15000
            assert data["input_tokens"] == 1000
            assert data["output_tokens"] == 500


class TestClineTail:
    """Tests for cline_tail tool."""

    @pytest.mark.asyncio
    async def test_cline_tail_returns_last_n_lines(self):
        """Verify session with 30 lines output — lines=10 returns last 10."""
        with patch("clinemcp.sessions.SessionStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            # Create 30 lines of output
            output_lines = [f"line{i}" for i in range(30)]
            output = "\n".join(output_lines)
            mock_store.get_session = AsyncMock(
                return_value={
                    "session_id": "test-123",
                    "status": "complete",
                    "output": output,
                    "error": None,
                    "exit_code": 0,
                    "floor_result": None,
                }
            )
            mock_store_class.return_value = mock_store

            result = await handle_cline_tail({"session_id": "test-123", "lines": 10})
            data = json.loads(result)

            assert data["session_id"] == "test-123"
            assert data.get("status") == "complete"
            assert data["total_lines"] == 30
            # Should return last 10 lines
            tail_lines = data["tail"].split("\n")
            assert len(tail_lines) == 10
            assert tail_lines[0] == "line20"
            assert tail_lines[-1] == "line29"

    @pytest.mark.asyncio
    async def test_cline_tail_returns_error_for_unknown_session(self):
        """Verify unknown session_id — error field set, tail empty."""
        with patch("clinemcp.sessions.SessionStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store.init_db = AsyncMock()
            mock_store.get_session = AsyncMock(return_value=None)
            mock_store_class.return_value = mock_store

            result = await handle_cline_tail({"session_id": "unknown-id"})
            data = json.loads(result)

            assert data["session_id"] == "unknown-id"
            assert data["tail"] == ""
            assert data["error"] == "session not found"
