# ADR-004: TOBOR and ClineMCP are peers

**Status:** Accepted

## Context
TOBOR and ClineMCP must interact but neither should be the parent of the other.

## Decision
TOBOR calls ClineMCP tools (`cline_start`, `cline_status`) as an MCP client. ClineMCP calls TOBOR tools (`send_telegram`, `verify_test_floor`) for notifications and verification. Neither is the parent of the other. Both are NSSM services on Nitro 5.

## Consequences
- Bidirectional tool calls via MCP
- Loose coupling between services
- Either can restart independently
- Slightly more complex interaction pattern than direct subprocess

## Related
- ADR-001: Port 8003, standalone NSSM service
- ADR-003: Cline as direct child of ClineMCP
