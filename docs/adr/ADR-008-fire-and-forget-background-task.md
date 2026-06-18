# ADR-008: Fire-and-forget background task

**Status:** Accepted

## Context
`cline_start` must return immediately. The caller (TOBOR) cannot block waiting for Cline to complete.

## Decision
`cline_start` returns immediately after creating the background asyncio task. The caller does not wait for Cline to complete. `cline_status` polls completion. `cline_complete` signals when the caller is ready to close the step.

## Consequences
- Non-blocking tool calls
- Session must be persisted before background task starts
- Polling pattern for status checking
- Completion must be explicitly signaled by caller

## Related
- ADR-002: SQLite for session persistence
- Sessions persisted before subprocess starts
