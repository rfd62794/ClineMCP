# ADR-003: Cline as direct child of ClineMCP

**Status:** Accepted

## Context
The core problem: Cline dies when TOBOR restarts because Cline is a subprocess of TOBOR.

## Decision
The subprocess spawned by `runner.py` is a child of the ClineMCP Python process. TOBOR has no process relationship with Cline.

## Consequences
- A TOBOR restart has zero effect on an active Cline session
- This is the core architectural decision that motivated ClineMCP's existence
- ClineMCP must be running for Cline to execute (acceptable trade-off)

## Related
- ADR-001: Port 8003, standalone NSSM service
- ADR-004: TOBOR and ClineMCP are peers
