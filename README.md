# Sourcing agent take-home, pack

Read the task PDF first. Then run `python3 example_run.py` from your repo root. It takes thirty
seconds and it saves you from learning the provider API the expensive way.

| File | What it is |
|---|---|
| `sourcing_provider.py` | The search API your agent must go through. Copy it into your repo. Read its docstring, quota, rate limits and faults are all documented there. |
| `example_run.py` | A working call against the provider, including the retry you will need. |
| `data/profiles.jsonl` | 2,500 candidate profiles. This is what the provider searches. You may read it directly to understand the shape of the data; **your agent must still go through the provider.** |
| `data/vacancies.json` | 4 vacancies: description, `hard_requirements`, `rubric`, `target_strong`. |
| `data/gold_relevance.json` | Recruiter labels for **2 of the 4** vacancies: `0` / `1` / `2`. |
| `data/output_schema.json` | Schemas for the three files you must produce. |

## The rules the provider enforces

- **1,500 profiles of quota for the entire run**, shared across all four vacancies. It does not reset.
- `count()` is free of quota. `search()` costs **one unit per profile returned**.
- About 6% of calls fail, 2% time out, and calls are rate limited. None of those cost quota.
- `page_size` maxes at 50, `page` at 19. You cannot page past 1,000 results.
- Every call is appended to `.provider_audit/<run_id>.jsonl` in your working directory.
  **Commit that directory.** It is the record of what your agent actually did.

Pass `tag="VAC-00X"` to `count()` and `search()` so each call can be attributed to a vacancy.

## Two things the provider will not do for you

- There is **no filter for visa sponsorship or part-time**, but both are fields on every profile.
- `count()` tells you the size of a space. It does not tell you whether the space is any good.

## What you must produce

Three files in `out/`, plus your README.

`out/trace.jsonl`, one line per loop iteration per vacancy:

```json
{"vacancy_id":"VAC-00X","iteration":2,
 "criteria":{"...":"the filters you sent to the provider this round"},
 "observed":{"total_count":0,"returned":0,"new":0,"passed":0},
 "diagnosis":"<what you concluded, in your own words>",
 "evidence":"<counts a human can check>",
 "adjustment":{"...":"what you changed for the next round"},
 "stop_reason":null}
```

The final iteration for each vacancy must carry a non-null `stop_reason`.

`out/shortlist.json`, up to 25 ranked profiles per vacancy, all four present:

```json
{"VAC-00X":[{"profile_id":"PROF-....","rank":1,"score":0.0,
             "reason":"<one or two lines a recruiter can read>",
             "evidence":["<text copied exactly from that profile>"]}]}
```

`evidence` must be **verbatim text from that profile's own fields**. We check it automatically.

`out/report.md`, for each vacancy, in a few lines: what the agent did, why it stopped, and what
you would tell the recruiter. Write the last part as if the recruiter will read it, because that is
the actual product.

## Budget

A full cold run over all four vacancies: **under 10 minutes** and **under $3** of API spend.
Measure both, report both.
