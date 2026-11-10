# Run 3: pool sizing and sweep, checked against the gold labels

Date: 2026-11-10. All four vacancies. This follows `reports/first_run_README.md`. Gold labels exist for
VAC-001 and VAC-002 only, so the comparison with the recruiter is limited to those two.

## How it was run

```
PYTHONUTF8=1 uv run python -m sourcing_agent.cli --out out_run3 --run-id run3 --fresh
PYTHONUTF8=1 python reports/eval_gold.py out_run3
```

- Outputs: `out_run3/`. Provider record: `.provider_audit/run3.jsonl`. Log: `run3.log`.
- Models: Haiku 5.5 scores profiles and Sonnet 5.5 diagnoses and writes the notes, both through OpenRouter.
- Wall time 524 s (8.7 min) and LLM spend $0.27 over 73 calls (our estimate from token counts, not a bill).
- Provider calls: 50, with 3 502 errors and 1 timeout, all retried without any failure.
- Quota: 327 of 1,500 profiles bought.

## What changed in the code since run 2

- **Pool size.** Before each vacancy the agent runs one free `count()` with only the hard filters, to
  learn how many profiles in the whole database it may ever buy. The model sees "pool 75, 36 bought, 39
  unseen", and so does the trace.
- **Sweep.** If the loop is about to give up and 200 or fewer profiles remain unseen (and the budget
  covers them), the agent buys them all with hard filters only.
- **True `space_exhausted`.** The stop reason now means every profile that meets the hard requirements
  was bought and scored.

## Headline

| | VAC-001 AI Engineer | VAC-002 Senior Backend | VAC-003 ML Platform | VAC-004 Data Engineer |
|---|---|---|---|---|
| Target (`target_strong`) | 15 | 10 | 12 | 8 |
| Pool (meets the hard requirements) | 1,406 | 75 | 190 | 491 |
| Profiles bought | 25 | 75 | 190 | 37 |
| Agent says strong | 21 | 4 | 1 | 2 |
| Rounds, stop reason | 1, `target_reached` | 9, `space_exhausted` | 8, `space_exhausted` | 8, `max_iterations` |
| Gold labels | yes | yes | no | no |

## Against the gold labels (VAC-001 and VAC-002), all three full runs

"Run 1" here is the first full four-vacancy run (`out/`, provider run `main`). It is not the two-vacancy
gold run described in `first_run_README.md`, which used the earlier scorer and has different numbers.

| | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| **VAC-001** agent says strong | 16 | 17 | 21 |
| of those, gold-strong (precision) | 8 (50%) | 10 (59%) | 10 (48%) |
| gold-strong among the 25 bought | 12 | 11 | 10 |
| gold-strong the agent caught, of those bought | 8 of 12 | 10 of 11 | 10 of 10 |
| **VAC-002** agent says strong | 4 | 4 | 4 |
| of those, gold-strong (precision) | 2 (50%) | 4 (100%) | 4 (100%) |
| gold-strong bought, of 5 that exist | 5 | 5 | 5 |
| gold-strong the agent caught | 2 of 5 | 4 of 5 | 4 of 5 |
| Profiles bought | 30 | 36 | 75 |
| Strong per 100 bought (gold) | 16.7 | 13.9 | 6.7 |

Mean agent score by gold label, run 3: VAC-001 0.12 (gold 0), 0.60 (gold 1), 0.76 (gold 2); VAC-002
0.07, 0.21, 0.65. The ordering is right on both vacancies in every run.

## What worked

- **The sweep gives a complete answer.** For VAC-002 the agent reviewed all 75 profiles that meet the
  hard requirements. The audit log shows 75 of 75 bought. The recruiter note says the pool is exhausted
  and 4 meet the bar. The gold labels agree that 5 exist, so one was missed.
- **VAC-003 got the same treatment.** All 190 were bought and 1 meets the bar. That is a solid
  "this brief is hard to fill" finding with a number behind it.
- **VAC-002 scoring.** Precision is 4 of 4 and the scorer catches 4 of the 5 gold-strong profiles.
  Run 1 caught 2. The years and bundled-criteria fixes made the difference.
- **Hard requirements.** None of the 50 provider calls in this run violated them, and none of the 296
  evidence items in the shortlists fails the verbatim check.
- **Provider faults.** The 502s and the timeout were retried and the run carried on.

## What did not work

1. **VAC-004 ended on `max_iterations` with 37 of 491 profiles bought.** Rounds 5-8 matched zero
   profiles and still counted toward the iteration cap. Its last diagnosis was about to go back to the
   filters that found 2 strong candidates.
2. **The shortlists are padded with partial fits.** VAC-001's 25 entries are 10 gold-strong, 14 gold-1
   and 1 gold-0. VAC-002's 25 are 5 gold-strong, 12 gold-1 and 8 gold-0. VAC-003's list has 25 entries
   for 1 strong candidate.
3. **One strong candidate is still missed on VAC-002.** PROF-0559 shows no AWS and no testing in its
   text. We decided that silence counts as "not met", so this is expected, not a bug.
5. **Time.** 524 s is close to the 10-minute limit, because scoring is still one batch at a time.
6. **Run-to-run variance.** The first 25 profiles on VAC-001 held 12, 11 and 10 gold-strong across the
   three runs, so single-run differences are weak evidence.
7. **Efficiency went down** because of the sweep (6.7 strong per 100 on VAC-002 against 13.9 before),
   in exchange for certainty. 1,173 of 1,500 profiles were unspent.

## Proposed fixes, in order

1. **Make the "strong" bar harder to meet on VAC-001-style vacancies.** Options: a second opinion from
   the stronger model on every profile that passes, or stopping only after a margin over the target
   (for example, 1.5 times). The first is more reliable. The second is simpler.
2. **List only strong profiles in the shortlist.**
3. **Do not count empty rounds toward `max_iterations`**, which fixes the VAC-004 case.
4. **Score batches in parallel**, to bring the run time well under 10 minutes.


