# Claude for OSS — Application: LegasVex

**GitHub:** https://github.com/parafoto/legasvex  
**Maintainer:** github.com/parafoto  
**Deadline:** June 30, 2026

---

## Project description

LegasVex is an open-source multi-agent legal AI platform built specifically for the Russian legal system. It delivers legal intelligence through a Telegram interface — helping lawyers manage cases, scan contracts for risk, search court databases (kad.arbitr.ru, sudact.ru), and draft legal documents, all with mandatory human-in-the-loop approval before any consequential action.

**What's actually shipped (not a demo):**
- Telegram bot for advocates with full matter lifecycle management
- Contract risk scanner — paste text, get structured risk analysis
- Case law search across arbitration and general jurisdiction courts
- Multi-agent orchestrator: TaskPlanner → AgentCouncil → StateMachine with HITL enforcement
- AI layer supporting Ollama (local, privacy-first) with OpenRouter as fallback
- Audit trail with legal significance tags on every action

**Why it matters to the ecosystem:**
Access to legal services in Russia is deeply unequal — most people can't afford professional legal advice. LegasVex is building open, reusable legal AI infrastructure that NGOs, civic tech projects, legal aid organizations, and individual advocates can run on their own servers. The codebase is designed to be auditable because legal AI must be transparent to be trusted.

**Why Claude specifically:**
Claude is central to LegasVex's roadmap. The current AI layer routes to Ollama/OpenRouter, but Claude's reasoning quality — especially for complex multi-step legal analysis — is what the next major version is being built around. Claude Max 20x would let us run high-frequency testing of legal reasoning across real case types (labor disputes, contract law, civil claims) without hitting rate limits that currently block iteration.

**Active development:**
Python 3.14 backend, active commits, real working bot serving test users.

---

## Short pitch (for single-field forms)

LegasVex is an open-source legal AI platform for the Russian legal system — Telegram-based, privacy-first, with a multi-agent orchestrator and mandatory human-in-the-loop approval. We're building open legal infrastructure so justice tooling is transparent, auditable, and accessible to everyone who needs it.

---

## Checklist before submitting

- [ ] Repo is public: github.com/parafoto/legasvex
- [ ] Has commits within last 3 months
- [ ] README describes the project clearly
- [ ] .env.example present (no secrets in repo)
- [ ] Submit at: https://claude.com/contact-sales/claude-for-oss
- [ ] Deadline: June 30, 2026
