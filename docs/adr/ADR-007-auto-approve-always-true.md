# ADR-007: Auto-approve always true

**Status:** Accepted

## Context
ClineMCP is not an interactive tool. It runs unattended on a server.

## Decision
`--auto-approve true` is hardcoded in the subprocess call. All tool approvals are granted automatically. Scope control is the directive's responsibility, not Cline's approval prompts.

## Consequences
- No human-in-the-loop for approvals
- Directives must be carefully scoped
- Faster execution (no blocking on prompts)
- Higher trust requirement for the system

## Related
- AGENT_CONTRACT.md: Architectural constraints
