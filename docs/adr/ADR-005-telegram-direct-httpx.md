# ADR-005: Telegram via direct httpx, not TOBOR dependency

**Status:** Accepted

## Context
If ClineMCP depends on TOBOR for Telegram, and TOBOR is down, completion notifications are lost.

## Decision
ClineMCP sends Telegram notifications directly via httpx POST to the Telegram Bot API. This avoids a runtime dependency on TOBOR being available.

## Consequences
- TOBOR going down does not prevent ClineMCP from reporting completion
- Duplicated Telegram logic (acceptable for reliability)
- Direct control over notification reliability

## Related
- ADR-004: TOBOR and ClineMCP are peers
