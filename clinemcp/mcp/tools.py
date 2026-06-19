"""MCP tool handlers — 5 tools from SDD §5."""

import asyncio
import json
import uuid
from datetime import datetime, timezone

from mcp.types import Tool

from clinemcp.clinerules import ensure_clinerules as _ensure_clinerules, resolve_model
from clinemcp.runner import cancel_session, start_session
from clinemcp.sessions import SessionStore
from clinemcp.telegram import send_message


async def handle_cline_start(arguments: dict) -> str:
    """Spawn Cline session, return session_id.

    Model resolution order:
    1. If model explicitly provided → use it
    2. Else if agent_type provided → look up in agent_routing.yaml
    3. Else → use default from agent_routing.yaml
    """
    import os
    task = arguments.get("task", "")
    explicit_model = arguments.get("model")
    agent_type = arguments.get("agent_type")
    cwd = arguments.get("cwd", os.environ.get("CLINE_DEFAULT_CWD", os.getcwd()))
    model = resolve_model(model=explicit_model, agent_type=agent_type)

    # Check for active session (MVP: one at a time)
    store = SessionStore()
    await store.init_db()

    active = await store.get_active_session()
    if active:
        return json.dumps({
            "error": f"Session already running: {active['session_id']}",
            "session_id": None,
            "status": None,
            "started_at": None,
        })

    session_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    # Persist before starting background task
    await store.create_session(session_id, task, model, cwd)

    # Fire-and-forget background task
    asyncio.create_task(start_session(session_id, task, model, cwd, store))

    return json.dumps({
        "session_id": session_id,
        "status": "running",
        "started_at": started_at,
        "error": None,
    })


async def handle_cline_status(arguments: dict) -> str:
    """Return current status, elapsed time, output preview."""
    session_id = arguments.get("session_id", "")

    store = SessionStore()
    await store.init_db()

    session = await store.get_session(session_id)
    if not session:
        return json.dumps({
            "session_id": session_id,
            "status": "not_found",
            "elapsed_seconds": 0,
            "output_preview": "",
            "error": "Session not found",
        })

    # Calculate elapsed time
    elapsed = 0
    if session.get("started_at"):
        start = datetime.fromisoformat(session["started_at"])
        elapsed = int((datetime.now(timezone.utc) - start).total_seconds())

    output = session.get("output", "") or ""
    preview = output[:500] if len(output) > 500 else output

    result = {
        "session_id": session_id,
        "status": session["status"],
        "elapsed_seconds": elapsed,
        "output_preview": preview,
        "error": session.get("error"),
    }

    # Include parsed fields when available
    if session.get("iterations") is not None:
        result["iterations"] = session["iterations"]
    if session.get("answer"):
        result["answer"] = session["answer"]
    if session.get("duration_ms") is not None:
        result["duration_ms"] = session["duration_ms"]
    if session.get("input_tokens") is not None:
        result["input_tokens"] = session["input_tokens"]
    if session.get("output_tokens") is not None:
        result["output_tokens"] = session["output_tokens"]

    return json.dumps(result)


async def handle_cline_complete(arguments: dict) -> str:
    """Mark complete, send Telegram."""
    session_id = arguments.get("session_id", "")
    step_id = arguments.get("step_id", 0)
    floor_result = arguments.get("floor_result", "")

    store = SessionStore()
    await store.init_db()

    # Update session
    success = await store.update_session(
        session_id, status="completion_signaled", step_id=step_id, floor_result=floor_result
    )

    telegram_sent = False
    if success:
        # Send Telegram notification
        text = f"✅ Cline Step {step_id} complete\nFloor: {floor_result}\nSession: {session_id[:8]}"
        telegram_sent = await send_message(text)

    return json.dumps({
        "session_id": session_id,
        "success": success,
        "telegram_sent": telegram_sent,
        "step_id": step_id,
        "floor_result": floor_result,
    })


async def handle_cline_cancel(arguments: dict) -> str:
    """Kill active subprocess."""
    session_id = arguments.get("session_id", "")

    store = SessionStore()
    await store.init_db()

    was_running = await cancel_session(session_id, store)

    return json.dumps({
        "session_id": session_id,
        "cancelled": True,
        "was_running": was_running,
    })


async def handle_cline_output(arguments: dict) -> str:
    """Return full session output."""
    session_id = arguments.get("session_id", "")

    store = SessionStore()
    await store.init_db()

    session = await store.get_session(session_id)
    if not session:
        return json.dumps({
            "session_id": session_id,
            "status": "not_found",
            "output": "",
            "exit_code": None,
            "floor_result": None,
        })

    return json.dumps({
        "session_id": session_id,
        "status": session["status"],
        "output": session.get("output", "") or "",
        "exit_code": session.get("exit_code"),
        "floor_result": session.get("floor_result"),
    })


async def handle_ensure_clinerules(arguments: dict) -> str:
    """Check for .clinerules in repo and generate if missing."""
    repo_path = arguments.get("repo_path", "")
    agent_type = arguments.get("agent_type")
    result = _ensure_clinerules(repo_path, agent_type=agent_type)
    return json.dumps(result)


async def handle_cline_tail(arguments: dict) -> str:
    """Return the last N lines of a running or completed session's output."""
    from clinemcp.sessions import SessionStore

    session_id = arguments.get("session_id", "")
    lines = arguments.get("lines", 20)

    store = SessionStore()
    await store.init_db()

    session = await store.get_session(session_id)
    if not session:
        return json.dumps({
            "session_id": session_id,
            "tail": "",
            "error": "session not found"
        })

    output = session.get("output") or ""
    tail_lines = output.splitlines()[-lines:]
    return json.dumps({
        "session_id": session_id,
        "status": session.get("status"),
        "tail": "\n".join(tail_lines),
        "total_lines": len(output.splitlines()),
        "error": None
    })


def get_tool_list() -> list[Tool]:
    """Return list of MCP tool definitions."""
    return [
        Tool(
            name="cline_start",
            description="Spawn Cline session, return session_id",
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Full task description"},
                    "model": {"type": "string", "description": "Explicit model override (highest priority)"},
                    "agent_type": {"type": "string", "description": "Agent type for routing lookup (e.g. code_transformation)"},
                    "cwd": {"type": "string", "description": "Working directory"},
                },
                "required": ["task"],
            },
        ),
        Tool(
            name="cline_status",
            description="Return current status, elapsed time, output preview",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID to check"},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="cline_complete",
            description="Mark complete, send Telegram",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session to mark complete"},
                    "step_id": {"type": "integer", "description": "Directive step"},
                    "floor_result": {"type": "string", "description": "Floor result (e.g., 249/0/0)"},
                },
                "required": ["session_id", "step_id", "floor_result"],
            },
        ),
        Tool(
            name="cline_cancel",
            description="Kill active subprocess",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session to cancel"},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="cline_output",
            description="Return full session output",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session to get output"},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="ensure_clinerules",
            description=(
                "Check for .clinerules in a repo and generate one if missing. "
                "If agent_type is provided, merges per-type template with existing repo rules. "
                "Template content comes first, repo rules append below --- separator."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Absolute path to the repo root directory."
                    },
                    "agent_type": {
                        "type": "string",
                        "description": "Agent type for template selection (e.g. code_transformation)"
                    }
                },
                "required": ["repo_path"]
            }
        ),
        Tool(
            name="cline_tail",
            description=(
                "Return the last N lines of a running or completed session's output. "
                "Poll every 1-3 seconds during active sessions for near real-time visibility. "
                "Returns empty string if no output yet."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID returned by cline_start."
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of lines to return from the end. Default 20.",
                        "default": 20
                    }
                },
                "required": ["session_id"]
            }
        ),
    ]
