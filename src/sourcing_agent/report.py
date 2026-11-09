"""Writes the three deliverables: trace.jsonl, shortlist.json, report.md."""

from __future__ import annotations

import json
from pathlib import Path

from .llm import LLM, THINKER, LLMError
from .state import State

NOTE_SYSTEM = (
    "You write the note a recruiter reads about one vacancy. Use only the facts given. Be plain "
    "and honest: say how many strong candidates were found against the target, and if short, why. "
    "The hard requirements were never relaxed. If relaxing one would plausibly help, you may "
    "propose it as a question for the recruiter, with your reasoning, and say clearly it was not "
    "done. No more than 120 words."
)


def write_trace(state: State, vacancies: list[dict], out: Path) -> None:
    lines = []
    for vac in vacancies:
        v = state.vacancy(vac["id"])
        for i, entry in enumerate(v["trace"]):
            entry = dict(entry)
            if i == len(v["trace"]) - 1 and entry["stop_reason"] is None:
                entry["stop_reason"] = "cancelled"  # run was stopped before this vacancy finished
            lines.append(json.dumps(entry))
    (out / "trace.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def shortlist_for(v: dict) -> list[dict]:
    """Top 25 scored profiles: strong ones first, then by score. Needs at least one verified quote."""
    scored = [(pid, s) for pid, s in v["scores"].items() if s["hits"]]
    scored.sort(key=lambda x: (not x[1]["passed"], -x[1]["score"], x[0]))
    out = []
    for rank, (pid, s) in enumerate(scored[:25], start=1):
        met = "; ".join(h["criterion"] for h in s["hits"])
        missing = ("; ".join(s["missing"])) or "nothing"
        reason = f"{'Strong' if s['passed'] else 'Partial'} fit. Shows: {met}. Missing must-haves: {missing}."
        evidence = list(dict.fromkeys(h["quote"] for h in s["hits"]))[:4]
        out.append({"profile_id": pid, "rank": rank, "score": s["score"],
                    "reason": reason[:400], "evidence": evidence})
    return out


def facts(vac: dict, v: dict) -> dict:
    strong = sum(1 for s in v["scores"].values() if s["passed"])
    return {
        "vacancy": f"{vac['id']} {vac['title']}", "target": vac["target_strong"],
        "strong_found": strong, "profiles_bought": v.get("spent", 0),
        "iterations": v["iteration"], "stop_reason": v["stop_reason"] or "cancelled",
        "hard_requirements": vac["hard_requirements"],
        "what_happened": [{"round": t["iteration"], "bought": t["observed"]["returned"],
                           "passed": t["observed"]["passed"], "diagnosis": t["diagnosis"]}
                          for t in v["trace"]],
    }


def recruiter_note(llm: LLM, f: dict) -> str:
    schema = {"type": "object", "properties": {"message": {"type": "string"}},
              "required": ["message"], "additionalProperties": False}
    try:
        return llm.ask_json(THINKER, NOTE_SYSTEM, json.dumps(f), schema, effort="medium")["message"]
    except LLMError:
        return (f"Found {f['strong_found']} strong candidates against a target of {f['target']}; "
                f"stopped because: {f['stop_reason']}. (The written summary could not be generated.)")


def write_outputs(state: State, vacancies: list[dict], llm: LLM, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_trace(state, vacancies, out)
    shortlist = {vac["id"]: shortlist_for(state.vacancy(vac["id"])) for vac in vacancies}
    (out / "shortlist.json").write_text(json.dumps(shortlist, indent=2), encoding="utf-8")

    parts = ["# Sourcing report\n"]
    for vac in vacancies:
        v = state.vacancy(vac["id"])
        f = facts(vac, v)
        parts.append(
            f"## {f['vacancy']}\n\n"
            f"**What the agent did:** {f['iterations']} search rounds, bought {f['profiles_bought']} "
            f"profiles, found {f['strong_found']} strong candidates (target {f['target']}).\n\n"
            f"**Why it stopped:** `{f['stop_reason']}`.\n\n"
            f"**What to tell the recruiter:** {recruiter_note(llm, f)}\n")
    elapsed = state.data.get("elapsed_s", 0)
    parts.append(f"## Run cost\n\nLLM spend this session: ${llm.cost:.2f} over {llm.calls} calls. "
                 f"Wall time across sessions: {elapsed / 60:.1f} min.\n")
    (out / "report.md").write_text("\n".join(parts), encoding="utf-8")
