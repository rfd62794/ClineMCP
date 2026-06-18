# ADR-006: One active session at a time (MVP)

**Status:** Accepted

## Context
MVP scope must be limited. Multiple concurrent sessions add complexity in session management, resource contention, and state tracking.

## Decision
MVP enforces a single active session. `cline_start` returns an error if a session is already in `running` state. Multiple concurrent sessions are deferred to v0.2 after the single-session pattern is proven.

## Consequences
- Simpler implementation
- Simpler testing
- Lower resource usage
- Queue management deferred
- May bottleneck if multiple tasks need concurrent execution

## Related
- Deferred to v0.2: Multiple concurrent sessions, session queuing
