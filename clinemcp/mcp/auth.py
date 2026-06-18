"""Bearer token authentication (ported from TOBOR)."""

import os
from functools import wraps

from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer

security = HTTPBearer()


def get_auth_token() -> str:
    """Get auth token from environment."""
    token = os.environ.get("CLINEMCP_AUTH_TOKEN", "")
    if not token:
        # Fallback for development
        token = os.environ.get("DUGGERBOT_AUTH_TOKEN", "")
    return token


def verify_token(request: Request) -> bool:
    """Verify Bearer token from request headers."""
    expected_token = get_auth_token()
    if not expected_token:
        # No token configured - allow all (development mode)
        return True

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False

    provided_token = auth_header[7:]  # Remove "Bearer " prefix
    return provided_token == expected_token


def require_auth(func):
    """Decorator to require authentication on MCP handlers."""

    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        if not verify_token(request):
            raise HTTPException(status_code=401, detail="Invalid or missing token")
        return await func(request, *args, **kwargs)

    return wrapper
