# ADR-001: Port 8003, standalone NSSM service

**Status:** Accepted

## Context
ClineMCP must survive TOBOR restarts. If ClineMCP is a child of TOBOR or shares a process, it will die when TOBOR restarts (self-update, NSSM restart, code change).

## Decision
ClineMCP runs on port 8003, completely independent of TOBOR (port 8001). Two separate NSSM services.

## Consequences
- Cline subprocess survival requires that ClineMCP never restarts due to TOBOR code changes or self-updates
- TOBOR and ClineMCP are true peers
- Additional NSSM service to manage

## Related
- ADR-004: TOBOR and ClineMCP are peers
