"""Cline subprocess management — runner.py from SDD §6."""

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

from clinemcp.sessions import SessionStore

CLINE_PATH = os.environ.get("CLINE_PATH", "cline")
DEFAULT_TIMEOUT = int(os.environ.get("CLINE_TIMEOUT_SECONDS", "300"))

# Track active subprocesses for cancellation
_active_processes: dict[str, asyncio.subprocess.Process] = {}


async def start_session(
    session_id: str,
    task: str,
    model: str,
    cwd: str,
    sessions: SessionStore,
) -> None:
    """Spawn Cline, capture output, update session on completion.

    Runs as background task — fire and forget.
    """
    # Mark session as running
    started_at = datetime.now(timezone.utc).isoformat()
    await sessions.update_session(
        session_id, status="running", started_at=started_at
    )

    # Build command (asyncio.create_subprocess_exec only — never shell=True)
    cmd = [
        CLINE_PATH,
        task,
        "--provider", "ollama",
        "--model", model,
        "--auto-approve", "true",
        "--cwd", cwd,
        "--timeout", str(DEFAULT_TIMEOUT),
        "--json",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _active_processes[session_id] = proc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=DEFAULT_TIMEOUT + 30
            )
            output = stdout.decode("utf-8", errors="replace") + stderr.decode(
                "utf-8", errors="replace"
            )
            exit_code = proc.returncode
            status = "complete" if exit_code == 0 else "failed"
        except asyncio.TimeoutError:
            proc.kill()
            output = "Session timed out"
            exit_code = -1
            status = "failed"

        completed_at = datetime.now(timezone.utc).isoformat()
        await sessions.update_session(
            session_id,
            status=status,
            output=output,
            exit_code=exit_code,
            completed_at=completed_at,
        )

    except Exception as e:
        completed_at = datetime.now(timezone.utc).isoformat()
        await sessions.update_session(
            session_id,
            status="failed",
            output=str(e),
            exit_code=-1,
            error=str(e),
            completed_at=completed_at,
        )

    finally:
        _active_processes.pop(session_id, None)


async def cancel_session(session_id: str, sessions: SessionStore) -> bool:
    """Kill active subprocess. Returns True if was running."""
    proc = _active_processes.get(session_id)
    if proc is None:
        # Check if session exists and is running in DB
        session = await sessions.get_session(session_id)
        if session and session.get("status") == "running":
            # Mark as cancelled even if process not tracked
            await sessions.update_session(
                session_id,
                status="cancelled",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            return True
        return False

    try:
        proc.kill()
        await proc.wait()
    except Exception:
        pass

    _active_processes.pop(session_id, None)

    await sessions.update_session(
        session_id,
        status="cancelled",
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    return True


def get_active_process(session_id: str) -> asyncio.subprocess.Process | None:
    """Get active process for session (for testing)."""
    return _active_processes.get(session_id)


def clear_active_processes() -> None:
    """Clear active process tracking (for testing)."""
    _active_processes.clear()
