"""Tests for sessions.py — 10 tests."""

import asyncio
import os
import sqlite3
from datetime import datetime, timezone

import pytest

from clinemcp.sessions import SessionStore, VALID_STATES


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_sessions.db"
    store = SessionStore(str(db_path))
    # Run init_db synchronously for setup
    asyncio.run(store.init_db())
    return store


class TestCreateSession:
    """test_create_session_stores_pending_status"""

    @pytest.mark.asyncio
    async def test_create_session_stores_pending_status(self, temp_db):
        session = await temp_db.create_session(
            session_id="test-123",
            task="echo hello",
            model="qwen2.5-coder:7b",
            cwd="C:\\Github\\DuggerBot",
        )
        assert session["session_id"] == "test-123"
        assert session["status"] == "pending"
        assert session["task"] == "echo hello"
        assert session["model"] == "qwen2.5-coder:7b"
        assert session["cwd"] == "C:\\Github\\DuggerBot"
        assert "created_at" in session


class TestUpdateSession:
    """Tests for update operations."""

    @pytest.mark.asyncio
    async def test_update_session_status_to_running(self, temp_db):
        await temp_db.create_session("test-456", "task", "model", "cwd")
        result = await temp_db.update_session("test-456", status="running")
        assert result is True
        session = await temp_db.get_session("test-456")
        assert session["status"] == "running"

    @pytest.mark.asyncio
    async def test_update_to_complete_with_output(self, temp_db):
        await temp_db.create_session("test-complete", "task", "model", "cwd")
        await temp_db.update_session("test-complete", status="running")
        result = await temp_db.update_session(
            "test-complete",
            status="complete",
            output="hello world",
            exit_code=0,
        )
        assert result is True
        session = await temp_db.get_session("test-complete")
        assert session["status"] == "complete"
        assert session["output"] == "hello world"
        assert session["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_update_to_failed_with_error(self, temp_db):
        await temp_db.create_session("test-fail", "task", "model", "cwd")
        result = await temp_db.update_session(
            "test-fail",
            status="failed",
            error="Command not found",
            exit_code=127,
        )
        assert result is True
        session = await temp_db.get_session("test-fail")
        assert session["status"] == "failed"
        assert session["error"] == "Command not found"
        assert session["exit_code"] == 127

    @pytest.mark.asyncio
    async def test_update_to_cancelled(self, temp_db):
        await temp_db.create_session("test-cancel", "task", "model", "cwd")
        await temp_db.update_session("test-cancel", status="running")
        result = await temp_db.update_session("test-cancel", status="cancelled")
        assert result is True
        session = await temp_db.get_session("test-cancel")
        assert session["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_update_invalid_status_raises(self, temp_db):
        with pytest.raises(ValueError, match="Invalid status"):
            await temp_db.update_session("any-id", status="invalid_status")


class TestGetSession:
    """Tests for get_session."""

    @pytest.mark.asyncio
    async def test_get_session_returns_correct_fields(self, temp_db):
        await temp_db.create_session("test-get", "my task", "my model", "my cwd")
        session = await temp_db.get_session("test-get")
        assert session is not None
        assert session["session_id"] == "test-get"
        assert session["task"] == "my task"
        assert session["model"] == "my model"
        assert session["cwd"] == "my cwd"
        assert session["status"] == "pending"

    @pytest.mark.asyncio
    async def test_session_not_found_returns_none(self, temp_db):
        session = await temp_db.get_session("nonexistent-id")
        assert session is None


class TestGetActiveSession:
    """Tests for get_active_session."""

    @pytest.mark.asyncio
    async def test_get_active_session_returns_running(self, temp_db):
        await temp_db.create_session("active-1", "task", "model", "cwd")
        await temp_db.update_session("active-1", status="running")
        active = await temp_db.get_active_session()
        assert active is not None
        assert active["session_id"] == "active-1"
        assert active["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_active_session_returns_none_when_idle(self, temp_db):
        await temp_db.create_session("complete-1", "task", "model", "cwd")
        await temp_db.update_session("complete-1", status="complete")
        active = await temp_db.get_active_session()
        assert active is None


class TestStartupCleanup:
    """Tests for startup cleanup."""

    @pytest.mark.asyncio
    async def test_on_startup_marks_running_sessions_failed(self, temp_db):
        # Create running sessions
        await temp_db.create_session("running-1", "t", "m", "c")
        await temp_db.create_session("running-2", "t", "m", "c")
        await temp_db.update_session("running-1", status="running")
        await temp_db.update_session("running-2", status="running")

        # Create a complete session (should not be affected)
        await temp_db.create_session("complete-1", "t", "m", "c")
        await temp_db.update_session("complete-1", status="complete")

        # Run startup cleanup
        count = await temp_db.mark_running_as_failed_on_startup()
        assert count == 2

        # Verify states
        s1 = await temp_db.get_session("running-1")
        s2 = await temp_db.get_session("running-2")
        s3 = await temp_db.get_session("complete-1")

        assert s1["status"] == "failed"
        assert s1["error"] == "ClineMCP restarted"
        assert s2["status"] == "failed"
        assert s2["error"] == "ClineMCP restarted"
        assert s3["status"] == "complete"


class TestAppendOutput:
    """Tests for append_output function."""

    @pytest.mark.asyncio
    async def test_append_output_writes_to_db(self, temp_db):
        """Verify single line appended — retrieved output contains that line."""
        await temp_db.create_session("test-append", "task", "model", "cwd")
        await temp_db.append_output("test-append", "line1\n")
        
        session = await temp_db.get_session("test-append")
        assert session["output"] == "line1\n"

    @pytest.mark.asyncio
    async def test_append_output_accumulates_lines(self, temp_db):
        """Verify multiple append_output calls — output contains all lines in order."""
        await temp_db.create_session("test-accumulate", "task", "model", "cwd")
        await temp_db.append_output("test-accumulate", "line1\n")
        await temp_db.append_output("test-accumulate", "line2\n")
        await temp_db.append_output("test-accumulate", "line3\n")
        
        session = await temp_db.get_session("test-accumulate")
        assert session["output"] == "line1\nline2\nline3\n"
