# Sourcing agent

Take-home: an agent loop that sources candidates for 4 vacancies through a quota-limited provider.
See `Sourcing-Agent-Task.pdf` for the task, `READMENEW.md` for a guided tour of the repo, and
`reports/` for analysis of the runs.

## Principles
- Keep the code simple and readable. Do not overcomplicate beyond the task requirements.
- Prefer plain functions and the standard library. No extra tooling, dependencies or abstractions unless needed.
- Stopping, hard requirements, quota and evidence counts are decided in code. The model only reads text,
  suggests soft filters and writes notes. Do not move those decisions into a prompt.

## Commands
- `uv sync` install dependencies
- `uv run pytest` run tests (about 70 seconds; the full-loop tests use a fake model but the real provider)
- `PYTHONUTF8=1 uv run sourcing-agent --out out_demo --run-id demo --fresh` run the agent.
  `PYTHONUTF8=1` is needed on Windows. Run from the repo root (the provider looks for `data/` there).
- `uv run python example_run.py` the example supplied with the task
- `uv run ruff check .` lint (`reports/`, `example_run.py` and `src/sourcing_provider/` are excluded)

## Layout
- `src/sourcing_agent/`: `loop.py` (loop, stop rules, sweep), `criteria.py` (hard/soft filters),
  `scoring.py` (rubric scoring), `llm.py`, `provider.py`, `state.py`, `report.py`, `cli.py`
- `src/sourcing_provider/`: the supplied provider, unchanged, installed as its own package
- `tests/`, `data/` (supplied), `reports/` (analysis scripts and write-ups)
- Outputs: `out/` is the submission run. Experiments use their own `--out out_<name>` and `--run-id`.

## Rules
- All searches go through `sourcing_provider`. The agent never reads `data/profiles.jsonl`.
- Never relax a hard requirement. They come from the vacancy file and are added by code last.
- `data/gold_relevance.json` is for offline checks in `reports/` only, never inside the agent.
- Commit `.provider_audit/`. A new run id writes a new file there; `--fresh` on an existing id resets it.
- Secrets: the API key lives only in `.env`, which is git-ignored. `.env.example` must stay empty.
  Check `git diff` before committing, and never use `git add -A` without looking at `git status`.
- LLM key: `sk-ant-` uses Anthropic directly; `sk-or-` uses OpenRouter with `anthropic/...` model names.
- Scoring is noisy between runs. Do not conclude a prompt change helped from one run; re-score the same
  saved profiles (`reports/rescore_gold.py`) a few times first.
