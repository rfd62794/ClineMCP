"""Cline subprocess management — runner.py from SDD §6."""

import asyncio
import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any

from clinemcp.sessions import SessionStore

logger = logging.getLogger("clinemcp.runner")

CLINE_PATH = os.environ.get("CLINE_PATH", "cline")
DEFAULT_TIMEOUT = int(os.environ.get("CLINE_TIMEOUT_SECONDS", "300"))

# Track active subprocesses for cancellation
_active_processes: dict[str, asyncio.subprocess.Process] = {}


def ensure_cline_hub_healthy() -> None:
    """Kill stale hub and restart clean on ClineMCP startup."""
    result = subprocess.run([CLINE_PATH, "doctor"], capture_output=True, text=True)
    if "hub healthy yes" not in result.stdout:
        # Kill stale hub process
        subprocess.run([CLINE_PATH, "doctor", "fix"], capture_output=True)
        # Find and kill the stale process
        netstat = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
        for line in netstat.stdout.splitlines():
            if "25463" in line and "LISTENING" in line:
                parts = line.strip().split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
        # Start fresh hub
        subprocess.Popen([CLINE_PATH, "hub", "start"])


def get_hub_port() -> int | None:
    """Return port Cline Hub is listening on, or None if not found."""
    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if "LISTENING" in line and "127.0.0.1" in line:
            parts = line.strip().split()
            addr = parts[1]
            port = int(addr.split(":")[-1])
            if 25000 <= port <= 30000:
                pid_str = parts[-1]
                return int(pid_str)
    return None


async def hub_watchdog(interval_seconds: int = 60) -> None:
    """Background task. Checks hub health every interval_seconds.
    If unhealthy: kills stale process, starts fresh hub."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            result = subprocess.run(
                [CLINE_PATH, "doctor"],
                capture_output=True, text=True, timeout=10
            )
            if "hub healthy yes" not in result.stdout:
                logger.warning("hub_watchdog.unhealthy — attempting recovery")
                ensure_cline_hub_healthy()
                logger.info("hub_watchdog.recovery_complete")
            else:
                logger.debug("hub_watchdog.healthy")
        except Exception as e:
            logger.error(f"hub_watchdog.error: {e}")


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
    logger.info(f"Starting session {session_id} with task: {task[:50]}...")
    
    # Mark session as running
    started_at = datetime.now(timezone.utc).isoformat()
    await sessions.update_session(
        session_id, status="running", started_at=started_at
    )
    logger.info(f"Session {session_id} marked as running")

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
        "--hooks-dir", "C:\\Users\\cheat\\.cline\\hooks",
    ]

    logger.info(f"Command: {' '.join(cmd)}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _active_processes[session_id] = proc
        logger.info(f"Subprocess started with PID: {proc.pid}")

        try:
            logger.info(f"Waiting for subprocess {session_id} to complete...")
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=DEFAULT_TIMEOUT + 30
            )
            output = stdout.decode("utf-8", errors="replace") + stderr.decode(
                "utf-8", errors="replace"
            )
            exit_code = proc.returncode
            status = "complete" if exit_code == 0 else "failed"
            logger.info(f"Subprocess {session_id} completed with exit code: {exit_code}, status: {status}")

            # Parse JSON output for enriched session data
            parsed = _parse_json_output(output)
            logger.info(f"Parsed output: iterations={parsed.get('iterations')}, tokens={parsed.get('input_tokens')}/{parsed.get('output_tokens')}")

        except asyncio.TimeoutError:
            logger.error(f"Session {session_id} timed out")
            proc.kill()
            output = "Session timed out"
            exit_code = -1
            status = "failed"
            parsed = {}

        except Exception as e:
            logger.error(f"Exception during subprocess execution for {session_id}: {e}")
            completed_at = datetime.now(timezone.utc).isoformat()
            await sessions.update_session(
                session_id,
                status="failed",
                output=str(e),
                exit_code=-1,
                error=str(e),
                completed_at=completed_at,
            )
            return

        completed_at = datetime.now(timezone.utc).isoformat()
        await sessions.update_session(
            session_id,
            status=status,
            output=output,
            exit_code=exit_code,
            completed_at=completed_at,
            iterations=parsed.get("iterations"),
            answer=parsed.get("answer"),
            duration_ms=parsed.get("duration_ms"),
            input_tokens=parsed.get("input_tokens"),
            output_tokens=parsed.get("output_tokens"),
        )
        logger.info(f"Session {session_id} updated in database with status: {status}")

    except Exception as e:
        logger.error(f"Exception in start_session for {session_id}: {e}")
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
        logger.info(f"Session {session_id} cleaned up from active processes")


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


def _parse_json_output(output: str) -> dict[str, Any]:
    """Parse newline-delimited JSON output from Cline.

    Extracts:
    - iterations: count of iteration_start events
    - answer: text from done event (stripped of code blocks)
    - duration_ms: from run_result
    - input_tokens/output_tokens: from run_result usage
    - error: from error events
    """
    result: dict[str, Any] = {
        "iterations": 0,
        "answer": None,
        "duration_ms": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "error": None,
    }

    for line in output.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type", "")

        # Error events
        if event_type == "error":
            result["error"] = event.get("message", "Unknown error")

        # Agent events (iteration tracking and answer extraction)
        elif event_type == "agent_event":
            agent_event = event.get("event", {})
            agent_event_type = agent_event.get("type", "")

            if agent_event_type == "iteration_start":
                result["iterations"] = result.get("iterations", 0) + 1

            elif agent_event_type == "done":
                text = agent_event.get("text", "")
                # Strip code blocks if present
                if text.startswith("```") and text.endswith("```"):
                    # Remove first and last line (code block markers)
                    lines = text.split("\n")
                    if len(lines) > 2:
                        text = "\n".join(lines[1:-1])
                result["answer"] = text.strip() if text else None

        # Run result (duration and token counts)
        elif event_type == "run_result":
            result["duration_ms"] = event.get("durationMs")
            usage = event.get("usage", {})
            result["input_tokens"] = usage.get("inputTokens", 0)
            result["output_tokens"] = usage.get("outputTokens", 0)
            # Also update iterations if provided
            if "iterations" in event:
                result["iterations"] = event["iterations"]

    return result
