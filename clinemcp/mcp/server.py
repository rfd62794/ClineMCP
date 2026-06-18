"""FastAPI + MCP SSE server (adapted from TOBOR)."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from mcp.server.sse import SseServerTransport

from clinemcp.mcp.auth import verify_token
from clinemcp.mcp.tools import get_mcp
from clinemcp.sessions import SessionStore

# Get configuration from environment
MCP_PORT = int(os.environ.get("MCP_PORT", "8003"))
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
INSTANCE_ROLE = os.environ.get("INSTANCE_ROLE", "development")


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

    yield

    # Shutdown (nothing special needed)


def create_app() -> FastAPI:
    """Create and configure FastAPI app with MCP."""
    app = FastAPI(
        title="ClineMCP",
        description="Standalone MCP server for managing Cline CLI sessions",
        version="0.1.0",
        lifespan=lifespan,
    )

    mcp = get_mcp()
    transport = SseServerTransport("/messages/")

    @app.get("/health")
    async def health() -> dict:
        """Health check endpoint."""
        return {"status": "ok", "role": INSTANCE_ROLE}

    @app.get("/sse")
    async def sse_endpoint(request: Request) -> Response:
        """MCP SSE endpoint with auth."""
        if not verify_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        async with transport.connect(
            request.scope, request.receive, request._send
        ) as streams:
            read_stream, write_stream = streams
            await mcp.run(
                read_stream,
                write_stream,
                mcp.create_initialization_options(),
            )

        return Response(status_code=200)

    @app.post("/messages/")
    async def messages_endpoint(request: Request) -> Response:
        """MCP messages endpoint with auth."""
        if not verify_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        await transport.handle_post_message(request.scope, request.receive, request._send)
        return Response(status_code=200)

    return app
