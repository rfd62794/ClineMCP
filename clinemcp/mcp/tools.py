"""MCP tool schemas — 5 tools from SDD §5."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ClineMCP")


@mcp.tool()
async def cline_start(task: str, model: str, cwd: str = "C:\\Github\\DuggerBot") -> str:
    """Spawn Cline session, return session_id.

    Args:
        task: Full task description passed to Cline
        model: Ollama model (e.g., "qwen2.5-coder:7b", "qwen3:4b")
        cwd: Working directory, default "C:\\Github\\DuggerBot"

    Returns:
        JSON with session_id, status, started_at
    """
    import asyncio
    import json
    import uuid
    from datetime import datetime, timezone

    from clinemcp.runner import start_session
    from clinemcp.sessions import SessionStore

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


@mcp.tool()
async def cline_status(session_id: str) -> str:
    """Return current status, elapsed time, output preview.

    Args:
        session_id: Session ID to check

    Returns:
        JSON with status, elapsed_seconds, output_preview
    """
    import json
    from datetime import datetime, timezone

    from clinemcp.sessions import SessionStore

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

    return json.dumps({
        "session_id": session_id,
        "status": session["status"],
        "elapsed_seconds": elapsed,
        "output_preview": preview,
        "error": session.get("error"),
    })


@mcp.tool()
async def cline_complete(session_id: str, step_id: int, floor_result: str) -> str:
    """Mark complete, send Telegram.

    Args:
        session_id: Session to mark complete
        step_id: Directive step being completed
        floor_result: Actual floor (e.g., "249/0/0")

    Returns:
        JSON with success, telegram_sent, step_id, floor_result
    """
    import json

    from clinemcp.sessions import SessionStore
    from clinemcp.telegram import send_message

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


@mcp.tool()
async def cline_cancel(session_id: str) -> str:
    """Kill active subprocess.

    Args:
        session_id: Session to cancel

    Returns:
        JSON with cancelled, was_running
    """
    import json

    from clinemcp.runner import cancel_session
    from clinemcp.sessions import SessionStore

    store = SessionStore()
    await store.init_db()

    was_running = await cancel_session(session_id, store)

    return json.dumps({
        "session_id": session_id,
        "cancelled": True,
        "was_running": was_running,
    })


@mcp.tool()
async def cline_output(session_id: str) -> str:
    """Return full session output.

    Args:
        session_id: Session to get output from

    Returns:
        JSON with full output, exit_code, status
    """
    import json

    from clinemcp.sessions import SessionStore

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


def get_mcp() -> FastMCP:
    """Return configured MCP instance."""
    return mcp
