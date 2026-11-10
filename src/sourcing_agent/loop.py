"""The search loop for one vacancy: search, score, diagnose, adjust, stop.

Code decides everything that must be reliable (hard filters, quota, stopping, evidence counts).
The LLM only picks which soft filters to try next, and says in words what it sees.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .criteria import SOFT_KEYS, build_filters, hard_filters, passes_hard
from .llm import LLM, THINKER, LLMError
from .provider import ProviderUnavailable, QuotaExceeded, call
from .scoring import score_profiles
from .state import State

PAGE = 25            # profiles bought per round
MAX_ITERATIONS = 8   # per vacancy
DRY_ROUNDS = 3       # rounds in a row that bought profiles but found no new strong candidate
SWEEP_MAX = 200      # if this few unseen profiles remain when the loop would give up, buy them all
SWEEP_PAGE = 50      # provider maximum page size
GIVE_UP = ("max_iterations", "diminishing_returns", "no_matches")


@dataclass
class Ctx:
    provider: object
    llm: LLM
    state: State
    out_dir: Path
    stop: threading.Event  # set by Ctrl+C / SIGTERM


def say(ctx: Ctx, vid: str, iteration: int, text: str) -> None:
    """Progress line for a human watching, plus out/status.json for anything polling it."""
    print(f"[{vid} iter {iteration}] {text}", file=sys.stderr, flush=True)
    status = {"vacancy": vid, "iteration": iteration, "doing": text, "updated": time.time(),
              "llm_cost_usd": round(ctx.llm.cost, 3), "quota_left": ctx.provider.quota_remaining()}
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    (ctx.out_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")


# ---------------------------------------------------------------- evidence (code, not LLM)

def skill_evidence(v: dict) -> str:
    """Skills that separate the profiles that passed from those that failed, with counts."""
    scored = [(v["seen"][pid], s) for pid, s in v["scores"].items()
              if not s.get("dropped") and pid in v["seen"]]
    passed = [p for p, s in scored if s["passed"]]
    failed = [p for p, s in scored if not s["passed"]]
    if not passed or not failed:
        return f"{len(passed)} passed and {len(failed)} failed so far; not enough to compare skills."

    def count(group, skill):
        return sum(1 for p in group if skill in {x.lower() for x in p.get("skills") or []})

    all_skills = {x.lower() for p, _ in scored for x in p.get("skills") or []}
    rows = []
    for skill in all_skills:
        a, b = count(passed, skill), count(failed, skill)
        gap = a / len(passed) - b / len(failed)
        if a >= 2 and gap >= 0.3:
            rows.append((gap, f"'{skill}': {a} of {len(passed)} passed list it, "
                              f"{b} of {len(failed)} failed do"))
    rows.sort(reverse=True)
    return "; ".join(r for _, r in rows[:5]) or "no skill clearly separates passed from failed."


# ---------------------------------------------------------------- LLM: choose next soft filters

SOFT_SCHEMA = {
    "type": "object",
    "properties": {
        "diagnosis": {"type": "string"},
        "next_soft": {"type": "object",
                      "properties": {k: {"type": "array", "items": {"type": "string"}}
                                     for k in sorted(SOFT_KEYS)},
                      "required": sorted(SOFT_KEYS), "additionalProperties": False},
    },
    "required": ["diagnosis", "next_soft"], "additionalProperties": False,
}

SOFT_SYSTEM = (
    "You steer a candidate search. The location, minimum years, full-time and sponsorship "
    "requirements are fixed and applied for you; you cannot change them. You only choose "
    "optional filters: keywords (any), keywords_all, titles, skills_any, skills_all, seniority "
    "(intern/entry/junior/mid/senior/lead) and native_language. Use empty lists for filters you "
    "do not want. All filters combine with AND. skills_any and keywords match profiles that have "
    "at least one of the terms. skills_all and keywords_all require every term, so each extra "
    "term shrinks the results. Start with the loose ones and tighten only when the results are "
    "too broad. Base your choice on the counts you are given, and "
    "say in the diagnosis what the numbers mean in one or two sentences."
)


def propose(ctx: Ctx, vac: dict, soft: dict, observed: dict | None, evidence: str,
            history: list[dict], pool_note: str = "") -> tuple[str, dict]:
    """Ask the LLM for the next soft filters. Returns (diagnosis, validated soft filters)."""
    rubric = json.dumps(vac["rubric"])
    parts = [f"Vacancy: {vac['title']}\n{vac['description']}\nRubric: {rubric}",
             f"Target: {vac['target_strong']} strong candidates.",
             f"Current soft filters: {json.dumps(soft)}"]
    if pool_note:
        parts.append(pool_note)
    if observed is None:
        parts.append("No search has run yet. Choose a sensible first set of soft filters.")
    else:
        parts.append(f"This round: {json.dumps(observed)}")
        parts.append(f"Evidence (counts from the code): {evidence}")
        parts.append("Rounds so far: " + json.dumps(
            [{"soft": h["criteria"].get("soft"), "observed": h["observed"]} for h in history]))
    try:
        r = ctx.llm.ask_json(THINKER, SOFT_SYSTEM, "\n\n".join(parts), SOFT_SCHEMA, effort="medium")
    except LLMError as e:
        return f"LLM unavailable ({e}); keeping the same filters.", soft
    cleaned = {k: v for k, v in r["next_soft"].items() if k in SOFT_KEYS and v}
    return r["diagnosis"], cleaned


# ---------------------------------------------------------------- one round

def dry_rounds(trace: list[dict], returned: int, passed_now: int) -> int:
    """How many rounds in a row, counting this one, bought profiles but found no new strong one.

    A round that bought nothing is skipped: it cost no quota and says nothing about the pool.
    """
    rounds = [(t["observed"]["returned"], t["observed"]["passed"]) for t in trace]
    rounds.append((returned, passed_now))
    dry = 0
    for bought, passed in reversed(rounds):
        if bought == 0:
            continue
        if passed > 0:
            break
        dry += 1
    return dry


def unseen(v: dict) -> int | None:
    """Profiles that meet the hard requirements and have not been bought yet (None if pool unknown)."""
    return None if v.get("pool") is None else v["pool"] - len(v["seen"])


def pool_note(v: dict) -> str:
    if v.get("pool") is None:
        return ""
    return (f"Pool: {v['pool']} profiles in the whole database meet the hard requirements; "
            f"{len(v['seen'])} bought so far, {unseen(v)} still unseen.")


def maybe_sweep(v: dict, reason: str | None) -> str | None:
    """If the loop is about to give up but the rest of the pool is small and affordable, buy it all.

    Returns None (keep going) when a sweep starts, otherwise the reason unchanged.
    """
    left = unseen(v)
    if reason in GIVE_UP and left is not None and 0 < left <= min(SWEEP_MAX, v["share"] - v["spent"]):
        v["sweep"] = True
        return None
    return reason


def stop_reason(v: dict, vac: dict, it: int, total: int, returned: int, passed_now: int,
                forced_stop: str | None, provider) -> str | None:
    """Decide in code whether to stop. Returns the stop_reason, or None to carry on."""
    total_passed = sum(1 for s in v["scores"].values() if s["passed"])
    if forced_stop:
        return forced_stop
    if total_passed >= vac["target_strong"]:
        return "target_reached"
    if provider.quota_remaining() <= 0:
        return "provider_quota_exhausted"
    if v["spent"] >= v["share"]:
        return "quota_share_exhausted"
    left = unseen(v)
    if (left is not None and left <= 0) or (total <= returned and not v["soft"]):
        return "space_exhausted"  # every profile that meets the hard requirements has been bought
    if v.get("sweep"):
        return None  # sweeping buys everything left; only the checks above end it
    if it >= MAX_ITERATIONS:
        return "max_iterations"
    if dry_rounds(v["trace"], returned, passed_now) >= DRY_ROUNDS:
        return "diminishing_returns"
    return None


def buy_profiles(ctx: Ctx, vac: dict, v: dict, it: int) -> None:
    """Count, then search. Saves what was bought (and the round's filters) in v['pending']."""
    vid, provider = vac["id"], ctx.provider
    if it == 1 and not v["soft"]:
        say(ctx, vid, it, "planning first search")
        _, v["soft"] = propose(ctx, vac, {}, None, "", [], pool_note(v))
    filters = build_filters(vac, v["soft"], list(v["seen"]))
    total = call(provider.count, tag=vid, **filters)  # free
    page = min(SWEEP_PAGE if v.get("sweep") else PAGE, v["share"] - v["spent"],
               provider.quota_remaining(), total)
    ids, forced_stop = [], None
    if page > 0:
        say(ctx, vid, it, f"searching: {total} unseen profiles match, buying {page}")
        try:
            r = call(provider.search, tag=vid, page=0, page_size=page, **filters)
            for p in r.profiles:
                v["seen"][p["profile_id"]] = p
            ids = [p["profile_id"] for p in r.profiles]
            v["spent"] += len(ids)
        except QuotaExceeded:
            forced_stop = "provider_quota_exhausted"
        except ProviderUnavailable:
            forced_stop = "provider_unavailable"
    shown = {"hard": hard_filters(vac), "soft": v["soft"], "exclude_seen": len(v["seen"]) - len(ids)}
    v["pending"] = {"criteria": shown, "total": total, "ids": ids, "forced_stop": forced_stop}
    ctx.state.save()  # before scoring: a kill after this never makes us pay for these profiles again


def score_unscored(ctx: Ctx, vac: dict, v: dict, it: int) -> int:
    """Score every profile bought but not yet scored. Returns how many failed the hard check."""
    todo = [p for pid, p in v["seen"].items() if pid not in v["scores"]]
    dropped = 0
    for p in list(todo):
        if not passes_hard(vac, p):  # e.g. needs sponsorship: the provider cannot filter this
            v["scores"][p["profile_id"]] = {"score": 0, "passed": False, "dropped": True,
                                            "hits": [], "missing": []}
            dropped += 1
            todo.remove(p)
    if todo:
        say(ctx, vac["id"], it, f"scoring {len(todo)} profiles")
        v["scores"].update(score_profiles(ctx.llm, vac, todo))
    ctx.state.save()
    return dropped


def one_round(ctx: Ctx, vac: dict, v: dict) -> None:
    vid = vac["id"]
    it = v["iteration"] + 1
    if "pending" not in v:  # after a kill, the round's profiles may already be bought
        buy_profiles(ctx, vac, v, it)
    pend = v["pending"]
    dropped = score_unscored(ctx, vac, v, it)

    ids = pend["ids"]
    passed_now = sum(1 for pid in ids if v["scores"].get(pid, {}).get("passed"))
    unscored = sum(1 for pid in ids if pid not in v["scores"])
    observed = {"total_count": pend["total"], "returned": len(ids), "new": len(ids),
                "passed": passed_now}
    strong_total = sum(1 for s in v["scores"].values() if s["passed"])
    evidence = (f"{len(ids)} bought; {dropped} dropped for sponsorship/part-time; "
                f"{unscored} not scored (LLM failure); {passed_now} passed this round; "
                f"{strong_total} strong in total, target {vac['target_strong']}. "
                + pool_note(v) + " " + skill_evidence(v))

    reason = stop_reason(v, vac, it, pend["total"], len(ids), passed_now, pend["forced_stop"], ctx.provider)
    reason = maybe_sweep(v, reason)
    say(ctx, vid, it, "diagnosing" + (f" (stopping: {reason})" if reason else ""))
    this_round = {"criteria": pend["criteria"], "observed": observed}
    diagnosis, new_soft = propose(ctx, vac, v["soft"], observed, evidence, v["trace"] + [this_round],
                                  pool_note(v))
    if not reason and pend["total"] == 0 and new_soft == v["soft"]:
        reason = maybe_sweep(v, "no_matches")  # nothing matched and the filters would not change
    if v.get("sweep") and not reason:
        new_soft = {}  # sweeping: hard requirements only, buy everything that is left
        evidence += f" Sweep mode: buying the {unseen(v)} unseen profiles that meet the hard requirements."

    v["trace"].append({
        "vacancy_id": vid, "iteration": it, "criteria": pend["criteria"], "observed": observed,
        "diagnosis": diagnosis, "evidence": evidence,
        "adjustment": {} if reason else {"from": v["soft"], "to": new_soft},
        "stop_reason": reason,
    })
    if not reason:
        v["soft"] = new_soft
    v["stop_reason"] = reason
    v["iteration"] = it
    del v["pending"]
    ctx.state.save()


def run_vacancy(ctx: Ctx, vac: dict, share: int) -> None:
    v = ctx.state.vacancy(vac["id"])
    if "share" not in v:
        v["share"], v["spent"] = share, 0
    if "pool" not in v:  # free: how many profiles in the whole database meet the hard requirements
        try:
            v["pool"] = call(ctx.provider.count, tag=vac["id"], **hard_filters(vac))
        except ProviderUnavailable:
            v["pool"] = None
        ctx.state.save()
    while v["stop_reason"] is None and not ctx.stop.is_set():
        one_round(ctx, vac, v)


def run_all(ctx: Ctx, vacancies: list[dict]) -> None:
    for vac in vacancies:
        if ctx.state.vacancy(vac["id"])["stop_reason"] is not None:
            continue
        unfinished = [x for x in vacancies if ctx.state.vacancy(x["id"])["stop_reason"] is None]
        # Equal split of what is left; whatever a vacancy leaves unspent rolls into the next ones.
        run_vacancy(ctx, vac, ctx.provider.quota_remaining() // len(unfinished))
        if ctx.stop.is_set():
            say(ctx, vac["id"], ctx.state.vacancy(vac["id"])["iteration"], "cancelled, progress saved")
            return
