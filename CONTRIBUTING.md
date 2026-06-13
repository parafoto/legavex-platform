# Contributing to LegasVex

Thank you for your interest. LegasVex is open-source legal AI infrastructure — contributions that improve access to justice are especially welcome.

## Ground rules

**Human-in-the-loop is non-negotiable.** Any change that removes or bypasses mandatory human approval for legal actions will not be merged. This is a safety invariant, not a preference.

**AI outputs are always drafts.** Do not add code paths that deliver AI-generated legal text directly to clients without advocate review.

**Privacy first.** Cloud LLM is opt-in. The default configuration should work entirely with a local Ollama instance.

## How to contribute

1. Fork the repository and create a branch: `git checkout -b feature/your-feature`
2. Make your changes with clear, focused commits
3. Test locally — at minimum run the bot in dry-run mode (`LEGASVEX_AGENT_COUNCIL_DRY_RUN=true`)
4. Open a Pull Request with a description of what changed and why

## What we welcome

- Bug fixes and reliability improvements
- New agent roles for the AgentCouncil (add to `agent_council.py` + prompt in `shared/prompt_registry/`)
- Additional legal database integrations (court search sources beyond kad.arbitr.ru / sudact.ru)
- Formatter improvements for Telegram output
- Localization (Ukrainian, German, English legal systems via `COUNTRY_AGENTS`)
- Documentation and examples

## What we won't merge

- Removal of HITL guards
- Direct client delivery of AI-generated legal advice
- Hard-coding cloud LLM as the only option
- Changes that require proprietary dependencies to function

## Questions

Open an issue or start a discussion on GitHub.
