# ClineMCP — Agent Contract

## Identity
ClineMCP is a standalone MCP server that manages Cline CLI sessions.
It is a peer of TOBOR, not a child. Port 8003. Python 3.12. uv managed.

## Pre-flight (MANDATORY)
uv run pytest --tb=no -q
Must report: 40 passed, 0 failed, 0 skipped (Phase 0 target)
If count differs: STOP.

## Read-only files
All ADRs in docs/adr/ — permanently locked after commitment.

## Architectural constraints (all from ADRs above)
- asyncio.create_subprocess_exec only — never shell=True
- One active session at a time
- --auto-approve true always
- Sessions persisted before subprocess starts
- On startup: running sessions marked failed
- Telegram via direct httpx — no TOBOR dependency

## Proof standard
Raw pytest output only. Terminal screenshot for NSSM verification.
Agent summaries not accepted.
