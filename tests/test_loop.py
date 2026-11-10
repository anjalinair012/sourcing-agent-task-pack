import json
import re
import threading
from pathlib import Path

import pytest

import sourcing_provider
from sourcing_agent.criteria import passes_hard
from sourcing_agent.loop import Ctx, run_all
from sourcing_agent.report import write_outputs
from sourcing_agent.state import State

ROOT = Path(__file__).resolve().parent.parent
PROFILES = {}
for line in (ROOT / "data" / "profiles.jsonl").read_text(encoding="utf-8").splitlines():
    p = json.loads(line)
    PROFILES[p["profile_id"]] = p
VACANCIES = json.loads((ROOT / "data" / "vacancies.json").read_text(encoding="utf-8"))


class FakeLLM:
    """Stands in for the model. `good` says whether profiles meet the rubric."""

    def __init__(self, good: bool):
        self.good, self.cost, self.calls = good, 0.0, 0

    def ask_json(self, model, system, user, schema, **kw):
        self.calls += 1
        if "results" in schema["properties"]:  # scoring
            results = []
            for pid in re.findall(r"profile_id: (PROF-\d+)", user):
                headline = PROFILES[pid]["headline"]
                criteria = [{"index": i, "met": self.good, "quote": headline if self.good else ""}
                            for i in range(9)]
                results.append({"profile_id": pid, "criteria": criteria})
            return {"results": results}
        if "next_soft" in schema["properties"]:  # diagnosis + next filters
            return {"diagnosis": "fake", "next_soft": {
                "keywords": [], "keywords_all": [], "titles": [], "skills_any": ["Python"],
                "skills_all": [], "seniority": [], "native_language": [],
                "countries": ["United States"]}}  # tries to widen the brief; must be ignored
        return {"message": "fake note"}


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setattr(sourcing_provider, "AUDIT_DIR", str(tmp_path / "audit"))
    return sourcing_provider.SourcingProvider(run_id="t", reset=True, latency=False)


def run(provider, tmp_path, good, vacancies=VACANCIES):
    state = State(tmp_path / "state.json")
    ctx = Ctx(provider, FakeLLM(good), state, tmp_path, threading.Event())
    run_all(ctx, vacancies)
    return ctx, state


def test_every_vacancy_ends_with_a_stop_reason_and_respects_quota(provider, tmp_path):
    ctx, state = run(provider, tmp_path, good=False)
    for vac in VACANCIES:
        v = state.vacancy(vac["id"])
        assert v["stop_reason"] in {"diminishing_returns", "space_exhausted", "max_iterations",
                                    "quota_share_exhausted", "target_reached", "no_matches"}
        assert v["trace"][-1]["stop_reason"] == v["stop_reason"]
        assert v["spent"] <= v["share"]
    assert provider.quota_remaining() >= 0


def test_hard_requirements_hold_in_every_provider_call(provider, tmp_path):
    run(provider, tmp_path, good=False)
    audit = [json.loads(line) for line in open(provider.audit_path, encoding="utf-8")]
    calls = [a for a in audit if a["op"] in ("count", "search") and a.get("tag")]
    assert calls
    by_id = {v["id"]: v["hard_requirements"] for v in VACANCIES}
    for c in calls:
        hr, f = by_id[c["tag"]], c["filters"]
        assert f.get("countries") == hr.get("location_countries")
        assert f.get("cities") == hr.get("location_cities")
        assert f["min_years"] == hr["min_years"]


def test_shortlist_only_has_verified_evidence_and_passes_hard(provider, tmp_path):
    ctx, state = run(provider, tmp_path, good=True)
    write_outputs(state, VACANCIES, ctx.llm, tmp_path)
    shortlist = json.loads((tmp_path / "shortlist.json").read_text(encoding="utf-8"))
    assert set(shortlist) == {v["id"] for v in VACANCIES}
    for vac in VACANCIES:
        assert len(shortlist[vac["id"]]) <= 25
        for item in shortlist[vac["id"]]:
            p = PROFILES[item["profile_id"]]
            assert passes_hard(vac, p)
            assert all(e in p["headline"] for e in item["evidence"])


def test_resume_does_not_spend_quota_again(provider, tmp_path):
    ctx, state = run(provider, tmp_path, good=False)
    used = provider.quota_remaining()
    again = State(tmp_path / "state.json")
    run_all(Ctx(provider, FakeLLM(False), again, tmp_path, threading.Event()), VACANCIES)
    assert provider.quota_remaining() == used
