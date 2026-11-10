# First run: checking the agent against the gold labels

Date: 2026-11-10. Vacancies: VAC-001 and VAC-002, the two that have recruiter labels in
`data/gold_relevance.json`. This is an offline check. The agent never sees the gold labels.

## How it was run

A vacancies file holding only VAC-001 and VAC-002, on its own provider run id so it did not use the
quota of the real run:

```
PYTHONUTF8=1 uv run python -m sourcing_agent.cli \
  --vacancies <file with VAC-001 and VAC-002> --out out_gold --run-id gold --fresh
PYTHONUTF8=1 python reports/eval_gold.py out_gold
```

- Models: Haiku 5.5 scores profiles, Sonnet 5.5 diagnoses and writes notes, both through OpenRouter.
- Provider record: `.provider_audit/gold.jsonl`. Agent outputs: `out_gold/`.
- Cost and time: LLM spend $0.06, wall time 114 seconds.
- Quota: a fresh 1,500 profiles for this run id, split 750 per vacancy.

## Headline

| | VAC-001 AI Engineer | VAC-002 Senior Backend |
|---|---|---|
| Target (`target_strong`) | 15 | 10 |
| Gold-strong profiles that exist | 25 | 5 |
| Rounds, stop reason | 1, `target_reached` | 4, `diminishing_returns` |
| Profiles bought | 25 | 26 |
| Gold-strong among those bought | 16 | 5 |
| Strong per 100 bought (gold) | 64 | 19 |
| Agent said "strong" | 21 | 2 |
| Of those, gold-strong (precision) | 16 of 21 (76%) | 2 of 2 |
| Gold-strong the agent passed (recall within bought) | 16 of 16 | 2 of 5 (40%) |
| Shortlist size | 25 | 19 |
| Shortlist profiles with gold label 0 | 1 | 6 |

The task's control agent spends 367 profiles for 13 strong candidates, about 3.5 per 100.

## What worked

- **Efficiency on VAC-001.** The first search matched only 30 profiles and the agent bought 25 of
  them. 16 were gold-strong. It stopped after one round once its own count passed the target.
- **Ranking.** Mean agent score by gold label: VAC-001 0.12 (gold 0), 0.59 (gold 1), 0.78 (gold 2).
  VAC-002 0.17, 0.27, 0.57. Higher gold labels get higher scores in both.
- **Hard requirements.** Every provider call carried the vacancy's location and minimum years. The
  agent dropped 2 profiles in VAC-002 for needing sponsorship or being part-time only. Both were
  gold 0.
- **Honest outcome on VAC-002.** Only 5 strong people exist against a target of 10. The agent
  bought all 5 of them and did not widen the brief to look successful.

## What did not work

1. **Shortlist padding.** The shortlist includes weak partial fits. VAC-002's list contains six
   profiles with gold label 0 (Business Analysts, Data Analysts, an Insights Analyst), each with
   score 0.23. VAC-001's list has one (an Embedded Software Engineer at rank 25).
2. **Scoring misses real strong candidates on VAC-002.** It passed 2 of the 5. The other three lost
   points on "Production AWS, containers, infrastructure as code" and "Testing discipline and code
   review habits", which profiles rarely state in words. One also lost the "5+ years" item, even
   though the hard filter already guarantees five years. Years live in a number field, so the
   scorer could not quote it as evidence.
3. **The 80% threshold does not separate the labels.** On VAC-001, five gold-1 profiles sit at
   exactly 0.8 of the must-have weight and so passed. On VAC-002, gold-2 profiles sit at 0.5 to
   0.8 and gold-1 profiles at up to 0.5.
4. **Stopped too early on VAC-002.** After round 2 the agent added narrow keywords (round 3), and
   the search matched nobody. Round 4 matched nobody as well. Two rounds in a row with no new
   strong candidates triggered `diminishing_returns`. Neither round bought anything, so they cost
   no quota. The round-4 diagnosis says it was about to go back to the broader filters that had
   found 23 profiles.
5. **First filters were too narrow.** The first search matched 30 profiles for VAC-001 (of 1,406
   that meet the hard requirements) and 3 for VAC-002. The free `count()` could have been used to
   check the size before buying.

## Proposed fixes, in order

1. Shortlist only profiles the agent judged strong.
2. Let `years_experience` count as a verbatim quote for the rubric item about years.
3. Count a round towards `diminishing_returns` only if it bought profiles.
4. Use the free count to adjust a first search that matches very few or very many profiles.
5. Leave the 80% threshold for now. Two labelled vacancies are too few to tune it without fitting
   them. Revisit once fix 2 is in.

## Limits of this check

- Two vacancies, one run each. Language models vary between runs, so treat the numbers as a first
  look, not a measurement.
- Gold labels exist for all 2,500 profiles on these two vacancies only. VAC-003 and VAC-004 are
  untested.
- "Gold-strong" means label 2 in `data/gold_relevance.json`. The agent's "strong" means it met at
  least 80% of the must-have weight with verified quotes. They are different definitions.
