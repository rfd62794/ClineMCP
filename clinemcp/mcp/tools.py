"""MCP tool handlers — 5 tools from SDD §5."""

import asyncio
import json
import uuid
from datetime import datetime, timezone

from mcp.types import Tool

from clinemcp.runner import cancel_session, start_session
from clinemcp.sessions import SessionStore
from clinemcp.telegram import send_message


async def handle_cline_start(arguments: dict) -> str:
    """Spawn Cline session, return session_id."""
    import os
    task = arguments.get("task", "")
    model = arguments.get("model", "qwen2.5-coder:7b")
    cwd = arguments.get("cwd", os.environ.get("CLINE_DEFAULT_CWD", os.getcwd()))

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
                    "model": {"type": "string", "description": "Ollama model"},
                    "cwd": {"type": "string", "description": "Working directory"},
                },
                "required": ["task", "model"],
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
    ]
