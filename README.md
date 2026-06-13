# LegasVex

**Open-source legal AI platform for the Russian legal system — Telegram-based, privacy-first, human-in-the-loop**

LegasVex helps lawyers manage cases, scan contracts for risk, search court databases, and draft legal documents — all through Telegram, with a multi-agent orchestrator and mandatory human approval before any consequential action.

---

## Features

### For lawyers & advocates
- **Client intake** — register new matters directly from Telegram (`/intake`)
- **Portfolio & dashboard** — active cases, deadlines, risk overview at a glance (`/dashboard`, `/portfolio`)
- **Contract risk scan** — paste contract text, get structured risk analysis (`/risk_scan`)
- **Document management** — upload PDFs/docs, auto-classify per matter
- **Case law search** — arbitration (kad.arbitr.ru) + general jurisdiction (sudact.ru) in one command
- **Legal analysis drafts** — AI prepares a working draft; advocate reviews and approves

### Multi-agent orchestrator
8 specialized agent roles, budget-controlled, activated per task type:

| Role | Responsibility | Cost (units) |
|------|---------------|-------------|
| `critic` | Finds logical gaps and weak arguments | 1 |
| `proceduralist` | Checks deadlines, jurisdiction, procedural requirements | 2 |
| `evidence_analyst` | Links claims to facts and sources | 2 |
| `strategist` | Generates legal strategy options | 2 |
| `fact_checker` | Verifies data and citations | 1 |
| `position_architect` | Structures the legal position and defense | 2 |
| `risk_controller` | Assesses legal risks | 1 |
| `cost_controller` | Enforces budget (always runs, zero cost) | 0 |

Budget presets: `QUICK=2` (~30s) · `STANDARD=4` (~90s) · `FULL=8` (~3 min)

### Human-in-the-loop (HITL)
The following task types **always require explicit advocate approval** before execution:
`LEGAL_ANALYSIS` · `COMPLAINT_SEND` · `DOCUMENT_FINAL` · `MATTER_STATUS_CHANGE` · `CLIENT_INTAKE` · `EVIDENCE_COLLECT`

Safety invariants hard-coded at startup:
- `HUMAN_APPROVAL_REQUIRED=true`
- `DIRECT_CLIENT_DELIVERY=false`

### AI layer — no vendor lock-in
Priority order:
1. **Ollama (local)** — privacy-first, default, no data leaves your server
2. **OpenRouter** — optional cloud fallback, opt-in only
3. **Rule-based engine** — structured analysis without any LLM (6 Russian dispute categories)

### Audit trail
Every legally significant action is logged with actor ID, timestamp, `legal_significance` tag (`draft` / `approval`), and PII flag.

---

## Architecture

```
Telegram
 ├── Bot API mode (run_bot_assistant.py)       ← recommended
 └── Telethon userbot (run_telegram_assistant.py)

LawyerTelegramAssistant
 ├── SmartRouter          — confidential vs expert contour routing
 ├── CommandParser        — /commands and natural language
 ├── LocalAPIBridge       — CRM / Intake / Legal QA microservices
 ├── AIAssistant          — Ollama | OpenRouter
 ├── LegalSearch          — kad.arbitr.ru | sudact.ru
 ├── PilotMatterStore     — local file-based matter storage + audit log
 └── Orchestrator
      ├── TaskPlanner     — decomposes commands into typed tasks
      ├── AgentRouter     — routes by task type and country (ru/ua/de)
      ├── AgentCouncil    — selects roles by task type + budget
      ├── AgentCouncilExecutor — runs roles via LLM providers
      └── StateMachine    — lifecycle: created→planned→awaiting_human→approved→completed
```

---

## Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Bot interface | Telegram Bot API (stdlib) · Telethon MTProto |
| AI providers | Ollama · OpenRouter · Rule-based (no LLM) |
| Legal databases | kad.arbitr.ru · sudact.ru |
| Database | SQLite (dev) · PostgreSQL (prod) |
| Audit | JSONL append-only log + structured DB audit events |
| License | MIT |

---

## Quick start

```bash
git clone https://github.com/parafoto/legasvex.git
cd legasvex
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env: set BOT_TOKEN, Ollama endpoint or OpenRouter key

# Run (Bot API mode)
python services/chat/telegram_assistant/run_bot_assistant.py
```

For the Telethon userbot mode, run authorization first:
```bash
python services/chat/telegram_assistant/authorize_telegram.py
python services/chat/telegram_assistant/run_telegram_assistant.py
```

---

## Design principles

**Human-in-the-loop always.** LegasVex never sends complaints, finalizes documents, or changes case status without explicit advocate approval. AI drafts; humans decide.

**Privacy first.** Local Ollama is the default. Client data and case materials never leave your infrastructure unless explicitly configured.

**Transparent AI.** Every AI output is labeled as a draft. The system prompt prohibits categorical legal conclusions without document review. A transparency footer shows model, contour, and council roles used.

**Open infrastructure.** Legal AI must be auditable. If justice systems depend on algorithms, those algorithms should be open to inspection.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome.

## License

MIT © 2026 LegasVex contributors
