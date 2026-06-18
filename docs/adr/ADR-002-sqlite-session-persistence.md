# ADR-002: SQLite for session persistence

**Status:** Accepted

## Context
Sessions must survive ClineMCP restarts. When ClineMCP dies, running sessions must be recoverable and their state inspectable.

## Decision
Sessions stored in `sessions.db` at repo root (gitignored). Same aiosqlite pattern as TOBOR's `context.db`.

## Consequences
- Session state survives ClineMCP restarts
- A session that was running when ClineMCP died can be inspected after restart
- On restart, any session in `running` state is marked `failed` with error "ClineMCP restarted"
- Simple, reliable, no external dependencies

## Related
- ADR-003: Cline as direct child of ClineMCP
