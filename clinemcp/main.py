"""Entry point — uvicorn, .env.local load, logging."""

import logging
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

# Load .env.local if present
env_path = Path(__file__).parent.parent / ".env.local"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()  # Try default .env

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("clinemcp")

# Get config
MCP_PORT = int(os.environ.get("MCP_PORT", "8003"))
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")


def main():
    """Run the MCP server."""
    from clinemcp.mcp.server import create_app

    app = create_app()

    logger.info(f"Starting ClineMCP on {MCP_HOST}:{MCP_PORT}")

    uvicorn.run(
        app,
        host=MCP_HOST,
        port=MCP_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
