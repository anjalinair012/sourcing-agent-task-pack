# Self-review against the assessment table

Written for the GloPros reviewers, and for whoever prepares the debrief. It answers the six rows of
"What you send, 50%" in `Sourcing-Agent-Task.pdf` using what we actually ran and checked.

**Basis:** run 3 (`out_run3/`, `.provider_audit/run3.jsonl`), compared with run 1 (`out/`, `main`) and
run 2 (`out_run2/`). This is a draft: the numbers will be refreshed after the final run. Items we have
not verified are marked **Not verified**.

## The three runs, side by side

| | Run 1 (`main`) | Run 2 | Run 3 |
|---|---|---|---|
| Code change since the previous run | n/a | scoring fix, longer stop rule | pool sizing, sweep of small pools |
| Wall time, LLM cost (our token-price estimate) | 177 s, $0.11 | 242 s, $0.20 | 524 s, $0.27 |
| Profiles bought (quota is 1,500) | 83 | 101 | 327 |
| VAC-001 strong / target 15 | 16 | 17 | 21 |
| VAC-002 strong / target 10 | 4 | 4 | 4 |
| VAC-003 strong / target 12 | 0 | 0 | 1 |
| VAC-004 strong / target 8 | 0 | 0 | 2 |
| Stop reasons | 1 target, 3 diminishing returns | 1 target, 1 max iterations, 2 diminishing returns | 1 target, 2 space exhausted, 1 max iterations |

## 1. Loop quality and termination (25%): does it improve on what it learned, and stop for a true reason?

**What it does.** Each round the agent counts, buys 25 profiles, scores them, and asks the model for the
next soft filters. The model is given counts that the code computes, such as "'flink': 2 of 2 passed
list it, 4 of 11 failed do". The hard requirements are added by code after the model's choice, so the
model cannot change them.

**Evidence that it learns.** In VAC-004 (run 3, round 3) the diagnosis reads: adding the Dutch
native-language filter left 2-3 profiles and none passed, while the looser round gave 9 profiles with 2
passing, so language is the binding constraint. The next round dropped that filter.

**Evidence that stops are true.** In run 3, VAC-002 and VAC-003 end with `space_exhausted`. The agent
first counts, for free, how many profiles in the whole database meet the hard requirements (75 and
190), then buys every one of them. A stop reason of "everyone was reviewed" is checkable against the
audit log: 75 of 75 and 190 of 190 profiles bought.

**Where it falls short.**
- VAC-004 ended on `max_iterations`. Rounds 5-8 matched zero profiles because the filters were too
  narrow, and empty rounds still count toward the cap. The pool is 491 and the agent bought 37, so
  `max_iterations` is the true reason but the search was not finished.
- Results vary from run to run. The same profiles scored under the same prompt moved between 12 and 16
  gold-strong on VAC-001 across three re-scores. The model's first filters also differ between runs.
- Earlier versions stopped far too soon (two empty rounds). We fixed that in run 2 and run 3, and the
  history is in the commits.

## 2. What it tells the recruiter (20%): is the answer honest and useful, above all where things did not go to plan?

**What it says (run 3, `out_run3/report.md`).**
- VAC-002: "I bought all 75 profiles that meet the hard requirements ... so the pool is exhausted and
  more searching won't help." Only 4 meet the bar against a target of 10. The recruiter gets a
  complete answer and a question about other cities, with an explicit note that nothing was relaxed.
- VAC-003: all 190 profiles bought, 1 strong. It proposes widening the location as a question and says
  it was not done.
- VAC-004: says it stopped at the iteration limit with 2 of 8, names native Dutch as the likely
  blocker, and does not claim the pool was exhausted.

**Where it falls short.**
- **"Strong" is generous on VAC-001.** The agent called 21 strong, but the recruiter gold labels mark
  only 10 of those 25 profiles as strong (precision 48%). The note presents 21 as the answer.
- **The shortlists are padded.** All four lists have 25 entries, including partial fits. VAC-002's
  has 8 profiles the recruiter labelled 0. The `reason` says "Partial fit", but the lists look
  stronger than the outcome. This is a known open fix: list only strong profiles.
- The recruiter notes are written by the model from facts the code supplies. The numbers match the
  state, but the wording varies from run to run.

## 3. Architecture and resilience (20%): does the design satisfy the five constraints?

| Constraint | How it is met | Checked how |
|---|---|---|
| 1. Survives being killed | State saved to `out/state.json` after every step with an atomic write. Bought profiles are saved before scoring, in a `pending` record, so a restart scores them and does not buy again. | Unit test: re-running a finished run spends no quota.
| 2. Observable | One progress line per step on stderr, plus `status.json` (vacancy, iteration, what it is doing, LLM spend, quota left). | Watched live during runs 2 and 3. |
| 3. Stops cleanly when asked | A signal handler sets a flag; the loop finishes the current step, saves, and still writes all outputs. | **Not verified but saved state logic added**  |
| 4. Faults are normal | The provider wrapper waits out rate limits and retries 502s and timeouts. An exhausted quota ends the vacancy cleanly. A failed LLM batch is retried next round. A rejected API key stops the run with a message. | Run 3 handled 3 502s and 1 timeout without a failure. The auth stop was triggered once by a bad key. |
| 5. Terminates and says why | Stopping is decided in code, never by the model. The last trace line of every vacancy has a non-null `stop_reason` and no earlier line has one. | Checked on runs 1-3. |


## 4. Efficiency under quota (15%): strong candidates found per profile spent

The task's control agent finds about 3.5 strong per 100 profiles. Our figures:

| | Strong per 100 profiles bought |
|---|---|
| Run 1 (agent's own count) | 24 |
| Run 2 (agent's own count) | 21 |
| Run 3 (agent's own count) | 8.6 (28 strong, 327 bought) |
| Run 3, VAC-001 and VAC-002 checked against the gold labels | 15 (10 + 5 gold-strong in 100 bought) |

- The agent's own counts over-count, because it flags partial fits as strong (see section 2), so the
  gold-based figure is the more reliable one. It is available for two vacancies only.
- Run 3's number is lower than run 2's on purpose. The sweep buys every profile in a small pool to
  give the recruiter a complete answer, which costs efficiency. 1,173 of 1,500 profiles went unspent.
- Time is a risk: 524 s is close to the 10-minute budget, because scoring runs one batch at a time.

## 5. Grounding and safety (10%): hard requirements respected, evidence real, explanations true

- **Hard requirements:** 0 violations across 107 audited provider calls (runs `main`, `gold`, `run2`,
  `run3`). The check compares each call's location and minimum-years filters with the vacancy file.
  Sponsorship and part-time are enforced after purchase.
- **A test with a fake model that tries to widen the country to the United States:** the filter is
  overwritten by the vacancy's real value.
- **Evidence:** 659 evidence items across the shortlists of runs 1-3, none that is not verbatim
  profile text. Every quote is verified in code against the profile's own fields, and a criterion
  without a verified quote counts as not met. Silence in a profile is "not met", by decision.
- **Every trace line has evidence.** 26 of 26 in run 3, with counts a person can check.
- **Weakness:** the model decides whether a profile meets each criterion, so "meets" can be wrong
  even when the quote is real. The gold comparison on VAC-001 shows this (48% precision).

## 6. Communication (10%): can we follow the thinking without you in the room?

- The trace records, per round, the filters used (hard and soft shown separately), the counts, a
  diagnosis in words, the evidence, and what changed.
- `reports/first_run_README.md` compares the first run with the recruiter labels, including what failed.

