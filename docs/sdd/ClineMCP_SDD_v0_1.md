# ClineMCP — System Design Document v0.1

*June 2026 | RFD IT Services Ltd. | Living Document*

---

## §1 Purpose and Problem Statement

ClineMCP is a standalone MCP server that manages Cline CLI sessions as observable, persistent, self-reporting processes.

**The problem it solves:**

Cline runs as a subprocess of whatever process dispatches it. In the current DuggerBot architecture, TOBOR dispatches Cline via `dispatch_to_cline()` — which means Cline is a child process of TOBOR. When TOBOR restarts (via self-update, NSSM restart, or code change), the Cline subprocess dies. There is no visibility into whether Cline is running, what it has done, or whether it succeeded. Completion is only visible if a human is watching Claude Desktop at the exact moment the tool call returns.

ClineMCP moves Cline out of TOBOR's process tree entirely. Cline runs as a child of ClineMCP. TOBOR becomes a peer that calls ClineMCP tools — not a parent that spawns children. Cline sessions survive TOBOR restarts. Completion is reported to Telegram automatically.

**What ClineMCP enables:**

- TOBOR auto-dispatches Cline steps from the directive system without human trigger
- Cline sessions survive any TOBOR restart
- Completion, failure, and output are visible in Telegram regardless of Claude Desktop state
- Claude verifies floor via TOBOR after ClineMCP signals completion
- Robert's only touchpoint: directive approval and Telegram review

---

## §2 Position in the Stack

```
Robert (approves directives, reads Telegram)
    ↓
Claude (writes directives, verifies floors via TOBOR)
    ↓
TOBOR (stores directives, routes steps, calls ClineMCP)
    ↓
ClineMCP (manages Cline sessions, monitors, reports to Telegram)
    ↓
Cline CLI (executes tasks, writes to repo)
    ↓
Devin (escalation for complex/architectural steps)
```

TOBOR and ClineMCP are **peers** — both are MCP servers. TOBOR is a client of ClineMCP for Cline dispatch. ClineMCP is a client of TOBOR for `send_telegram` and `verify_test_floor`.

---

## §3 MVP Scope

**In scope — MVP:**

- `cline_start(task, model, cwd)` — spawn Cline session, return session_id
- `cline_status(session_id)` — return current status, elapsed time, output preview
- `cline_complete(session_id, step_id, floor_result)` — mark complete, send Telegram
- `cline_cancel(session_id)` — kill active subprocess
- `cline_output(session_id)` — return full session output
- SQLite session persistence — sessions survive ClineMCP restarts
- Telegram completion notification — calls TOBOR's `send_telegram` or direct httpx
- NSSM service on Nitro 5, port 8003
- Bearer token auth (same pattern as TOBOR)

**Deferred — explicitly out of scope for MVP:**

- ⏳ Multiple concurrent sessions — MVP is one session at a time
- ⏳ Session queuing — sessions are started on demand, no queue
- ⏳ Log streaming — full output available after completion, not during
- ⏳ Tower deployment — Nitro 5 MVP first
- ⏳ Model auto-selection — caller specifies model
- ⏳ DUGGERWORKSHOP dispatch — future tier
- ⏳ Cline plugin management — out of scope

---

## §4 Architecture

### 4.1 Repo Structure

```
C:\Github\ClineMCP\
├── clinemcp/
│   ├── __init__.py
│   ├── main.py              — entry point (uvicorn, .env.local load, logging)
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── server.py        — FastAPI + MCP SSE server (adapted from TOBOR)
│   │   ├── auth.py          — Bearer token verification (ported from TOBOR)
│   │   ├── tools.py         — MCP tool schemas (5 tools)
│   │   └── handlers.py      — MCP tool handlers
│   ├── runner.py            — Cline subprocess management
│   ├── sessions.py          — SQLite session store
│   └── telegram.py          — Telegram notification (ported from TOBOR)
├── tests/
│   ├── __init__.py
│   ├── mcp/
│   │   ├── test_auth.py
│   │   ├── test_handlers.py
│   │   └── test_tools.py
│   ├── test_runner.py
│   ├── test_sessions.py
│   └── test_telegram.py
├── config/
│   └── .gitkeep
├── docs/
│   ├── adr/
│   └── state/
│       └── current.md
├── AGENT_CONTRACT.md
├── .clinerules
├── .env.example
├── .gitignore
└── pyproject.toml
```

### 4.2 Component Map

| Component | File | Responsibility |
|---|---|---|
| MCP Server | `mcp/server.py` | FastAPI + SSE transport, session management, lifespan |
| Auth | `mcp/auth.py` | Bearer token verification |
| Tools | `mcp/tools.py` | 5 tool schemas, no logic |
| Handlers | `mcp/handlers.py` | Tool handlers, delegate to runner/sessions |
| Runner | `runner.py` | Cline subprocess, start/monitor/kill, output capture |
| Sessions | `sessions.py` | SQLite CRUD, session state machine |
| Telegram | `telegram.py` | httpx POST to Telegram Bot API |
| Entry point | `main.py` | load_dotenv, logging, uvicorn.run |

### 4.3 Session State Machine

```
         ┌─────────┐
         │ pending │  (created, not yet started)
         └────┬────┘
              │ cline_start()
              ▼
         ┌─────────┐
         │ running │  (subprocess active)
         └────┬────┘
         ┌────┴──────────┐
         │               │
         ▼               ▼
   ┌──────────┐    ┌──────────┐
   │ complete │    │  failed  │  (subprocess exited non-zero or timed out)
   └──────────┘    └──────────┘
         │
         │ cline_complete() called
         ▼
   ┌────────────────────┐
   │ completion_signaled │  (Telegram sent, floor recorded)
   └────────────────────┘

   Any state → cancelled  (cline_cancel() called)
```

### 4.4 SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    task         TEXT NOT NULL,
    model        TEXT NOT NULL,
    cwd          TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    exit_code    INTEGER,
    output       TEXT,
    step_id      INTEGER,
    floor_result TEXT,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    completed_at TEXT,
    error        TEXT
);
```

---

## §5 MCP Tool Specifications

All tools return JSON via `TextContent`. All handlers delegate to `runner.py` or `sessions.py`. No business logic in handlers.

### `cline_start`

```python
# Input
task: str      # Full task description passed to Cline
model: str     # Ollama model: "qwen2.5-coder:7b" | "qwen3:4b"
cwd: str       # Working directory, default "C:\\Github\\DuggerBot"

# Returns
{
    "session_id": "uuid",
    "status": "running",
    "started_at": "ISO timestamp",
    "error": None
}
```

Spawns Cline via `asyncio.create_subprocess_exec`:
```
cline_cmd task --provider ollama --model model --auto-approve true
         --cwd cwd --timeout 300 --json
```

`cline_cmd` read from `CLINE_PATH` env var (default: `cline`).
Session persisted immediately on start.

### `cline_status`

```python
# Input
session_id: str

# Returns
{
    "session_id": "uuid",
    "status": "running" | "complete" | "failed" | "cancelled" | "completion_signaled",
    "elapsed_seconds": 47,
    "output_preview": "first 500 chars of output...",
    "error": None | "error message"
}
```

### `cline_complete`

```python
# Input
session_id: str
step_id: int          # Directive step being completed
floor_result: str     # Actual floor: "249/0/0"

# Returns
{
    "session_id": "uuid",
    "success": True,
    "telegram_sent": True,
    "step_id": 1,
    "floor_result": "249/0/0"
}
```

Marks session `completion_signaled`. Sends Telegram:
```
✅ Cline Step {step_id} complete
Floor: {floor_result}
Session: {session_id[:8]}
```

### `cline_cancel`

```python
# Input
session_id: str

# Returns
{
    "session_id": "uuid",
    "cancelled": True,
    "was_running": True | False
}
```

Kills subprocess via `proc.kill()`. Marks session `cancelled`.

### `cline_output`

```python
# Input
session_id: str

# Returns
{
    "session_id": "uuid",
    "status": "complete",
    "output": "full stdout + stderr...",
    "exit_code": 0,
    "floor_result": "249/0/0" | None
}
```

---

## §6 Runner Implementation

```python
# runner.py — key patterns

CLINE_PATH = os.environ.get("CLINE_PATH", "cline")
DEFAULT_TIMEOUT = int(os.environ.get("CLINE_TIMEOUT_SECONDS", "300"))

async def start_session(session_id: str, task: str, model: str, cwd: str) -> None:
    """Spawn Cline, capture output, update session on completion."""
    proc = await asyncio.create_subprocess_exec(
        CLINE_PATH, task,
        "--provider", "ollama",
        "--model", model,
        "--auto-approve", "true",
        "--cwd", cwd,
        "--timeout", str(DEFAULT_TIMEOUT),
        "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=DEFAULT_TIMEOUT + 30
        )
        output = stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")
        exit_code = proc.returncode
        status = "complete" if exit_code == 0 else "failed"
    except asyncio.TimeoutError:
        proc.kill()
        output = "Session timed out"
        exit_code = -1
        status = "failed"

    await sessions.update_session(
        session_id, status=status, output=output, exit_code=exit_code
    )
```

> ⚠️ **RULE:** `asyncio.create_subprocess_exec` only. Never `shell=True`.
> Never `asyncio.create_subprocess_shell`.

> ⚠️ **RULE:** `start_session` runs as a background asyncio task — fire and forget.
> `cline_start` returns immediately after spawning the task.
> The session is already persisted before the background task starts.

---

## §7 Telegram Notification

Port `duggerbot/telegram.py` directly. One function:

```python
async def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Send Telegram message. Returns True on success, False on failure. Never raises."""
```

`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from `.env.local`.

---

## §8 Configuration (.env.example)

```bash
# ClineMCP service config
MCP_PORT=8003
MCP_HOST=0.0.0.0
INSTANCE_ROLE=development
CLNEMCP_AUTH_TOKEN=generate_with_secrets_token_hex_32

# Cline
CLINE_PATH=C:\Users\cheat\AppData\Roaming\npm\cline.cmd
CLINE_TIMEOUT_SECONDS=300
CLINE_DEFAULT_MODEL=qwen2.5-coder:7b
CLINE_DEFAULT_CWD=C:\Github\DuggerBot

# Telegram (same bot as TOBOR)
TELEGRAM_BOT_TOKEN=from_privybot_env
TELEGRAM_CHAT_ID=from_privybot_env

# SQLite
SESSIONS_DB_PATH=sessions.db
```

---

## §9 NSSM Deployment

```powershell
# Admin shell
nssm install ClineMCP "C:\Github\ClineMCP\.venv\Scripts\python.exe"
nssm set ClineMCP AppParameters "-m clinemcp.main"
nssm set ClineMCP AppDirectory "C:\Github\ClineMCP"
nssm set ClineMCP AppStdout "C:\Github\ClineMCP\logs\nssm_stdout.log"
nssm set ClineMCP AppStderr "C:\Github\ClineMCP\logs\nssm_stderr.log"
nssm set ClineMCP AppEnvironmentExtra "PATH=C:\Program Files\Git\cmd;C:\Users\cheat\AppData\Roaming\npm;C:\Users\cheat\.local\bin;C:\Program Files\nodejs;C:\Windows\System32;C:\Windows"
nssm set ClineMCP AppExit default Restart
nssm set ClineMCP AppExit 1 Exit
nssm set ClineMCP Start SERVICE_AUTO_START
nssm start ClineMCP
```

Claude Desktop config addition:
```json
"clinemcp": {
    "command": "C:\\Users\\cheat\\AppData\\Roaming\\npm\\mcp-remote.cmd",
    "args": [
        "http://localhost:8003/sse",
        "--header", "Authorization: Bearer CLINEMCP_AUTH_TOKEN"
    ]
}
```

---

## §10 Architectural Decision Records

### ADR-001: Port 8003, standalone NSSM service

**Status:** Accepted

ClineMCP runs on port 8003, completely independent of TOBOR (port 8001). Two separate NSSM services. Rationale: Cline subprocess survival requires that ClineMCP never restarts due to TOBOR code changes or self-updates.

### ADR-002: SQLite for session persistence

**Status:** Accepted

Sessions stored in `sessions.db` at repo root (gitignored). Same aiosqlite pattern as TOBOR's `context.db`. Session state survives ClineMCP restarts — a session that was running when ClineMCP died can be inspected after restart. On restart, any session in `running` state is marked `failed` with error "ClineMCP restarted".

### ADR-003: Cline as direct child of ClineMCP

**Status:** Accepted

The subprocess spawned by `runner.py` is a child of the ClineMCP Python process. TOBOR has no process relationship with Cline. A TOBOR restart has zero effect on an active Cline session. This is the core architectural decision that motivated ClineMCP's existence.

### ADR-004: TOBOR and ClineMCP are peers

**Status:** Accepted

TOBOR calls ClineMCP tools (`cline_start`, `cline_status`) as an MCP client. ClineMCP calls TOBOR tools (`send_telegram`, `verify_test_floor`) for notifications and verification. Neither is the parent of the other. Both are NSSM services on Nitro 5.

### ADR-005: Telegram via direct httpx, not TOBOR dependency

**Status:** Accepted

ClineMCP sends Telegram notifications directly via httpx POST to the Telegram Bot API. This avoids a runtime dependency on TOBOR being available. TOBOR going down does not prevent ClineMCP from reporting completion.

### ADR-006: One active session at a time (MVP)

**Status:** Accepted

MVP enforces a single active session. `cline_start` returns an error if a session is already in `running` state. Multiple concurrent sessions are deferred to v0.2 after the single-session pattern is proven.

### ADR-007: Auto-approve always true

**Status:** Accepted

`--auto-approve true` is hardcoded in the subprocess call. ClineMCP is not an interactive tool. All tool approvals are granted automatically. Scope control is the directive's responsibility, not Cline's approval prompts.

### ADR-008: fire-and-forget background task

**Status:** Accepted

`cline_start` returns immediately after creating the background asyncio task. The caller does not wait for Cline to complete. `cline_status` polls completion. `cline_complete` signals when the caller is ready to close the step.

---

## §11 Test Plan

**Target floor: 40 passed, 0 failed, 0 skipped**
**Coverage: 80%+ per module and overall**

### test_auth.py (5 tests)
- `test_valid_token_passes`
- `test_invalid_token_returns_401`
- `test_missing_token_returns_401`
- `test_token_loaded_from_env`
- `test_bearer_prefix_required`

### test_sessions.py (10 tests)
- `test_create_session_stores_pending_status`
- `test_update_session_status_to_running`
- `test_get_session_returns_correct_fields`
- `test_session_not_found_returns_none`
- `test_update_to_complete_with_output`
- `test_update_to_failed_with_error`
- `test_update_to_cancelled`
- `test_get_active_session_returns_running`
- `test_get_active_session_returns_none_when_idle`
- `test_on_startup_marks_running_sessions_failed`

### test_runner.py (10 tests)
- `test_start_session_spawns_subprocess`
- `test_start_session_uses_cline_path_from_env`
- `test_start_session_passes_model_flag`
- `test_start_session_passes_cwd_flag`
- `test_start_session_marks_complete_on_exit_0`
- `test_start_session_marks_failed_on_nonzero_exit`
- `test_start_session_kills_on_timeout`
- `test_start_session_marks_failed_on_timeout`
- `test_cancel_kills_running_process`
- `test_cancel_returns_false_when_no_active_process`

### test_handlers.py (10 tests)
- `test_cline_start_returns_session_id`
- `test_cline_start_errors_when_session_already_running`
- `test_cline_status_returns_running_for_active`
- `test_cline_status_returns_not_found_for_unknown`
- `test_cline_complete_marks_session_completion_signaled`
- `test_cline_complete_sends_telegram`
- `test_cline_cancel_returns_cancelled_true`
- `test_cline_cancel_returns_false_when_not_running`
- `test_cline_output_returns_full_output`
- `test_cline_output_returns_error_for_unknown_session`

### test_telegram.py (5 tests)
- `test_send_message_returns_true_on_200`
- `test_send_message_returns_false_when_token_missing`
- `test_send_message_returns_false_on_http_error`
- `test_send_message_retries_without_parse_mode`
- `test_send_message_never_raises`

---

## §12 AGENT_CONTRACT.md (to be committed at Phase 0)

```markdown
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
```

---

## §13 Phase Map

| Phase | Name | Deliverables | Floor |
|---|---|---|---|
| 0 | Scaffold | pyproject.toml, AGENT_CONTRACT.md, .clinerules, .env.example, logs/.gitkeep, sessions.db gitignore, ADR-001 through ADR-008 | 0/0/0 |
| 1 | Sessions + Auth | sessions.py, auth.py, test_sessions.py, test_auth.py | 15/0/0 |
| 2 | Runner | runner.py, test_runner.py | 25/0/0 |
| 3 | MCP Server | server.py, tools.py, handlers.py, test_handlers.py, test_tools.py | 38/0/0 |
| 4 | Telegram + Entry Point | telegram.py, main.py, test_telegram.py | 43/0/0 |
| 5 | Deployment Gate | NSSM service live, Claude Desktop tether confirmed, cline_start() returns session from Claude Desktop | 43/0/0 + live verify |

---

*ClineMCP SDD v0.1 | June 2026 | RFD IT Services Ltd.*
*Cline lives in ClineMCP. TOBOR is a peer. Sessions survive everything.*
