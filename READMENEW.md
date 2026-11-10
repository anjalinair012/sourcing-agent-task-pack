# Sourcing agent: guide for the reviewer

Written for the interviewer going through this repository. It explains what the project is, where
everything lives, and a sensible order to read it in. The task is in `Sourcing-Agent-Task.pdf`. The
original pack README is still `README.md`.

## What it does

For each vacancy in a JSON file, the agent runs a bounded loop against a quota-limited candidate search
provider (1,500 profiles for the whole run):

```
search -> score what came back -> work out what it means -> adjust -> search again -> stop
```

It then writes three files: `trace.jsonl` (one line per round per vacancy), `shortlist.json` (ranked
profiles with verbatim evidence) and `report.md` (what it did, why it stopped, what to tell the recruiter).

The product rules from the task, and where they are enforced:

- **Hard requirements are never relaxed.** Location, minimum years, full-time and no sponsorship come
  from the vacancy file. Code adds the location and years filters to every provider call, after the
  model's choice, so the model cannot override them (`criteria.py`). Sponsorship and part-time cannot be
  filtered by the provider, so profiles that fail them are dropped after purchase.
- **Every adjustment has evidence a person can check.** The counts in each trace entry are computed by
  code (for example "'flink': 2 of 2 passed list it, 4 of 11 failed do"), not written by the model.

## What the LLM decides and what code decides

| Decision | Who | Why |
|---|---|---|
| Does this profile meet each rubric item, and what is the exact quote that proves it | Model (Haiku 5.5) | Reading free text |
| Which optional filters to try next, and a one-line diagnosis | Model (Sonnet 5.5) | Judgement from counts |
| Wording of the recruiter note | Model (Sonnet 5.5) | Writing from facts the code supplies |
| Hard filters, quota, paging, when to stop | Code | Must be reliable and checkable |
| Is a quote really in the profile; the score; who counts as strong | Code | A model claim is not accepted without a verbatim quote |
| Evidence counts in the trace | Code | So a person can recompute them |

## How to run

Needs [uv](https://docs.astral.sh/uv/) and an API key in `.env` (copy `.env.example`):

```
uv sync
uv run pytest                                  # 17 tests, about 70 seconds
PYTHONUTF8=1 uv run sourcing-agent --out out_demo --run-id demo --fresh
```

- Run from the repo root: the provider looks for `data/profiles.jsonl` there.
- `PYTHONUTF8=1` is needed on Windows, because the provider reads the data file with the default encoding.
- The task's example works too: `uv run python example_run.py` (the pack README says `python3`, which
  only works if the package is installed in that Python).
- The key can be an Anthropic key (`sk-ant-`) or an OpenRouter key (`sk-or-`); the client picks the
  endpoint and model names from the prefix.
- `--fresh` ignores saved state and resets the provider's quota. Without it, a run resumes where it stopped.
- Watch a run: progress lines on stderr, `<out>/status.json`, and `.provider_audit/<run-id>.jsonl`.

## File structure

```
src/sourcing_agent/        the agent
  cli.py                   entry point: loads the vacancies, signal handling, runs the loop, writes outputs
  loop.py                  the per-vacancy loop, stop rules, pool sizing and sweep, progress output
  criteria.py              hard filters, the allowed soft filters, the hard-requirement check on a profile
  scoring.py               rubric scoring: prompt, schema, quote verification, score arithmetic
  llm.py                   API client (Anthropic or OpenRouter), JSON answers, retries, cost cap
  provider.py              retry wrapper around the search provider (rate limits, 502s, timeouts)
  state.py                 run state saved to disk after every step (atomic write)
  report.py                trace.jsonl, shortlist.json, report.md

src/sourcing_provider/     the provider supplied with the task, unchanged, installed as its own package
example_run.py             the example supplied with the task
tests/                     criteria, state, scoring, stop rule, and full-loop tests with a fake model
data/                      supplied: vacancies, profiles, gold labels, output schema
reports/                   our analysis of the runs (below), and the scripts that produced it
out/ out_run2/ out_run3/   outputs of the three full runs
out_gold/                  output of the earlier two-vacancy gold run
.provider_audit/           the provider's record of every call, one file per run id
CLAUDE.md                  guidance for Claude Code sessions on this repo
```

## Suggested reading order (about 20 minutes)

1. `src/sourcing_agent/loop.py`: `one_round`, `stop_reason`, `maybe_sweep`. This is the core.
2. `src/sourcing_agent/criteria.py`: how the hard requirements are kept out of the model's reach.
3. `src/sourcing_agent/scoring.py`: how a model answer becomes a score, and why a quote must be verbatim.
4. `src/sourcing_agent/state.py` and the `pending` record in `loop.py`: how a killed run resumes
   without buying the same profiles twice.
5. `out_run3/report.md` and `out_run3/trace.jsonl`: what a run produces.
6. `reports/run3_README.md`, then `reports/assessment_self_review.md`: our own critique, including
   what failed.

## The five constraints, briefly

1. **Survives being killed.** State is written after every step. Bought profiles are saved before
   scoring, so a restart scores them and does not buy them again.
2. **Observable.** One line per step on stderr and `status.json`.
3. **Stops cleanly when asked.** A signal handler sets a flag; the loop finishes the step, saves, and
   still writes the outputs.
4. **Provider faults are normal.** Rate limits wait, 502s and timeouts retry, an exhausted quota ends
   the vacancy, and a rejected API key stops the run with a message.
5. **Terminates, and says why.** Stopping is decided in code. The stop reasons are `target_reached`,
   `space_exhausted`, `quota_share_exhausted`, `provider_quota_exhausted`, `provider_unavailable`,
   `max_iterations`, `diminishing_returns` and `no_matches`. Only the last trace line of a vacancy has one.

## The latest full run (run 3, `out_run3/`)

524 seconds and about $0.27 of LLM spend (our estimate from token counts); 327 of 1,500 profiles bought;
0 hard-requirement violations in the audit log.

| | Target | Agent says strong | Stop reason | Bought of pool |
|---|---|---|---|---|
| VAC-001 AI Engineer | 15 | 21 | `target_reached` | 25 of 1,406 |
| VAC-002 Senior Backend | 10 | 4 | `space_exhausted` | 75 of 75 |
| VAC-003 ML Platform | 12 | 1 | `space_exhausted` | 190 of 190 |
| VAC-004 Data Engineer | 8 | 2 | `max_iterations` | 37 of 491 |

## Where it breaks (also in `reports/`)

- **The agent over-counts strong candidates on VAC-001.** It said 21, and the recruiter labels support
  only 10. Because it stops on its own count, the `target_reached` stop is not true against the labels.
- **VAC-004 stops at the iteration limit** because rounds that match nobody still count toward it.
- **The shortlists include partial fits**, so a list can be 25 long when only a few are strong.
- **Scoring varies between runs.** The same profiles under the same prompt scored differently each time.
- **Run time is close to the 10-minute limit**, because scoring runs one batch at a time.
- **Not tested:** a real `kill -9`, a real Ctrl+C, and any vacancy outside the four.

## Notes on the repository

- `.provider_audit/` is committed on purpose: the task treats it as the record of what the agent did.
  It holds one file per run id (`main`, `gold`, `run2`, `run3`), so it includes our experiments.
- Recruiter labels in `data/gold_relevance.json` are used only offline, in `reports/`, never by the agent.
- Anything in the agent that depends on a specific vacancy would be a bug. Vacancies are read from the
  file, and there is no vacancy-specific text in `src/`.
