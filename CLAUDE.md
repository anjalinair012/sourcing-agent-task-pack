# Sourcing agent

Take-home: an agent loop that sources candidates for 4 vacancies through a quota-limited provider.
See README.md and Sourcing-Agent-Task.pdf for the task.

## Principles
- Keep the code simple and readable. Do not overcomplicate beyond the task requirements.
- Prefer plain functions and the standard library. No extra tooling, dependencies or abstractions unless needed.

## Commands
- `uv sync` install dependencies
- `uv run pytest` run tests
- `uv run sourcing-agent` run the agent

## Rules
- All searches must go through `sourcing_provider.py`; never read `data/profiles.jsonl` from the agent.
- Commit `.provider_audit/`. Deliverables go in `out/`.
