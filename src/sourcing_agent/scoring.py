"""Score profiles against a vacancy's rubric.

The LLM reads the profile and says which rubric items it shows, quoting the proof.
Code checks every quote really is in the profile and does all the arithmetic.
"""

from __future__ import annotations

from .llm import LLM, SCORER, LLMError

BATCH = 10
PASS_MUST = 0.8  # a profile is "strong" if it meets at least 80% of the must-have weight

SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "profile_id": {"type": "string"},
            "criteria": {"type": "array", "items": {
                "type": "object",
                "properties": {"index": {"type": "integer"}, "met": {"type": "boolean"},
                               "quote": {"type": "string"}},
                "required": ["index", "met", "quote"], "additionalProperties": False}},
        },
        "required": ["profile_id", "criteria"], "additionalProperties": False}}},
    "required": ["results"], "additionalProperties": False,
}

SYSTEM = (
    "You score candidate profiles against a hiring rubric. For every profile and every "
    "criterion, say whether the profile shows it. If it does, quote the exact words that prove "
    "it, copied character for character from the profile. If no text in the profile proves it, "
    "set met to false and quote to an empty string. Do not guess or infer from the job title alone. "
    "If a profile says nothing about a criterion, it is not met. Some criteria list alternatives or "
    "examples, such as 'AWS, Azure or GCP' or 'AWS, containers, infrastructure as code': one clearly "
    "evidenced alternative or a close equivalent is enough (Docker or Kubernetes for containers, "
    "Terraform for infrastructure as code, GCP for a cloud criterion). years_experience is a field "
    "you may quote, for example '7.8'."
)


def rubric_items(vacancy: dict) -> list[dict]:
    """Must-haves first, then nice-to-haves. The list position is the criterion index."""
    rubric = vacancy["rubric"]
    return ([{**c, "kind": "must"} for c in rubric["must"]]
            + [{**c, "kind": "nice"} for c in rubric.get("nice", [])])


def profile_fields(p: dict) -> list[str]:
    """Every piece of profile text a quote may be copied from."""
    fields = [p.get("headline"), p.get("current_title"), p.get("current_company"), p.get("summary")]
    fields += list(p.get("skills") or []) + list(p.get("languages") or [])
    if p.get("years_experience") is not None:
        fields.append(str(p["years_experience"]))
    return [f for f in fields if f]


def profile_text(p: dict) -> str:
    return "\n".join([
        f"profile_id: {p['profile_id']}",
        f"headline: {p.get('headline', '')}",
        f"title: {p.get('current_title', '')} at {p.get('current_company', '')}",
        f"years_experience: {p.get('years_experience')}",
        f"languages: {' | '.join(p.get('languages') or [])}",
        f"skills: {' | '.join(p.get('skills') or [])}",
        f"summary: {p.get('summary', '')}",
    ])


def grade(vacancy: dict, profile: dict, answer: list[dict]) -> dict:
    """Turn the LLM's per-criterion answers into a score. A hit without a verbatim quote is ignored."""
    items = rubric_items(vacancy)
    fields = profile_fields(profile)
    hits, met_weight, must_met, must_total = [], 0, 0, 0
    for i, item in enumerate(items):
        if item["kind"] == "must":
            must_total += item["weight"]
        a = next((c for c in answer if c.get("index") == i), None)
        if a and a["met"] and a["quote"] and any(a["quote"] in f for f in fields):
            hits.append({"criterion": item["criterion"], "quote": a["quote"]})
            met_weight += item["weight"]
            if item["kind"] == "must":
                must_met += item["weight"]
    total = sum(item["weight"] for item in items)
    return {
        "score": round(met_weight / total, 3),
        "passed": must_total > 0 and must_met / must_total >= PASS_MUST,
        "hits": hits,
        "missing": [i["criterion"] for i in items
                    if i["kind"] == "must" and i["criterion"] not in [h["criterion"] for h in hits]],
    }


def score_profiles(llm: LLM, vacancy: dict, profiles: list[dict]) -> dict[str, dict]:
    """Score profiles in batches. A batch the LLM fails on is skipped; it is retried next round."""
    items = rubric_items(vacancy)
    rubric = "\n".join(f"{i}. [{c['kind']}, weight {c['weight']}] {c['criterion']}"
                       for i, c in enumerate(items))
    out = {}
    for start in range(0, len(profiles), BATCH):
        batch = profiles[start:start + BATCH]
        user = (f"Vacancy: {vacancy['title']}\n\nRubric:\n{rubric}\n\nProfiles:\n\n"
                + "\n\n".join(profile_text(p) for p in batch))
        try:
            results = llm.ask_json(SCORER, SYSTEM, user, SCHEMA, max_tokens=6000)["results"]
        except LLMError:
            continue
        by_id = {r["profile_id"]: r["criteria"] for r in results}
        for p in batch:
            if p["profile_id"] in by_id:
                out[p["profile_id"]] = grade(vacancy, p, by_id[p["profile_id"]])
    return out
