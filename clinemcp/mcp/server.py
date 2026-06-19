"""FastAPI + MCP SSE server (adapted from TOBOR)."""

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent

from clinemcp.mcp.auth import verify_token_dependency
from clinemcp.runner import hub_watchdog
from clinemcp.sessions import SessionStore

logger = logging.getLogger(__name__)

# Get configuration from environment
MCP_PORT = int(os.environ.get("MCP_PORT", "8003"))
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
INSTANCE_ROLE = os.environ.get("INSTANCE_ROLE", "development")
SERVER_NAME = "clinemcp"

# Active MCP sessions for SSE endpoint validation
ACTIVE_SESSIONS: set[str] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Server lifespan — init DB and cleanup on startup/shutdown."""
    # Startup
    store = SessionStore()
    await store.init_db()

    # Mark any stale running sessions as failed
    count = await store.mark_running_as_failed_on_startup()
    if count > 0:
        print(f"Marked {count} stale sessions as failed")

    # Create MCP server
    mcp_server = Server(SERVER_NAME)
    sse_transport = SseServerTransport("/messages/")

    # Import tool handlers
    from clinemcp.mcp.tools import (
        handle_cline_cancel,
        handle_cline_complete,
        handle_cline_output,
        handle_cline_start,
        handle_cline_status,
        handle_ensure_clinerules,
        handle_cline_tail,
    )

    @mcp_server.list_tools()
    async def list_tools():
        from clinemcp.mcp.tools import get_tool_list
        return get_tool_list()

    @mcp_server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        handlers = {
            "cline_start": handle_cline_start,
            "cline_status": handle_cline_status,
            "cline_complete": handle_cline_complete,
            "cline_cancel": handle_cline_cancel,
            "cline_output": handle_cline_output,
            "ensure_clinerules": handle_ensure_clinerules,
            "cline_tail": handle_cline_tail,
        }
        handler = handlers.get(name)
        if not handler:
            raise ValueError(f"Unknown tool: {name}")
        result = await handler(arguments)
        return [TextContent(type="text", text=result)]

    app.state.mcp_server = mcp_server
    app.state.sse_transport = sse_transport

    # Start hub watchdog
    watchdog_task = asyncio.create_task(hub_watchdog(interval_seconds=60))
    logger.info("hub_watchdog.started")

    yield

    # Shutdown
    watchdog_task.cancel()
    try:
        await watchdog_task
    except asyncio.CancelledError:
        pass
    logger.info("hub_watchdog.stopped")


def create_app() -> FastAPI:
    """Create and configure FastAPI app with MCP."""
    app = FastAPI(
        title="ClineMCP",
        description="Standalone MCP server for managing Cline CLI sessions",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict:
        """Health check endpoint."""
        return {"status": "ok", "role": INSTANCE_ROLE}

    @app.get("/sse", dependencies=[Depends(verify_token_dependency)])
    async def sse_endpoint(request: Request):
        """MCP SSE endpoint with auth and session management."""
        logger.info(f"SSE endpoint accessed from {request.client.host if request.client else 'unknown'}")
        try:
            # Check for existing session ID
            session_id = request.headers.get("Mcp-Session-Id")

            if session_id is not None:
                # Stale session check
                if session_id not in ACTIVE_SESSIONS:
                    return JSONResponse({"error": "session_expired"}, status_code=404)
            else:
                # New connection — issue session ID
                session_id = str(uuid.uuid4())
                ACTIVE_SESSIONS.add(session_id)

            sse_transport = request.app.state.sse_transport
            mcp_server = request.app.state.mcp_server

            logger.info(f"Starting SSE connection for session {session_id}")
            logger.info(f"Request scope: {request.scope}")
            logger.info(f"Request receive: {request.receive}")
            logger.info(f"Request send: {getattr(request, '_send', 'not available')}")
            
            # Use the proper send function from the scope
            async def send(message):
                await request._send(message)
            
            async with sse_transport.connect_sse(
                request.scope, request.receive, send
            ) as (read_stream, write_stream):
                await mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp_server.create_initialization_options(),
                )

            # Return session ID in response header
            return Response(headers={"Mcp-Session-Id": session_id})
        except Exception as e:
            logger.error(f"SSE endpoint error: {e}", exc_info=True)
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/messages/", dependencies=[Depends(verify_token_dependency)])
    async def messages_endpoint(request: Request):
        """MCP messages endpoint with auth."""
        logger.info(f"Messages endpoint accessed from {request.client.host if request.client else 'unknown'}")
        sse_transport = request.app.state.sse_transport
        return await sse_transport.handle_post_message(
            request.scope, request.receive, request._send
        )

    return app
