import json
from pathlib import Path

from sourcing_agent.criteria import build_filters, passes_hard

VAC = json.loads(Path("data/vacancies.json").read_text(encoding="utf-8"))
NL_BACKEND = VAC[1]  # cities + 5 years
AI = VAC[0]          # countries + 3 years


def test_soft_filters_cannot_override_hard_ones():
    soft = {"countries": ["United States"], "min_years": 0, "skills_any": ["RAG"]}
    f = build_filters(AI, soft, [])
    assert f["countries"] == AI["hard_requirements"]["location_countries"]
    assert f["min_years"] == 3
    assert f["skills_any"] == ["RAG"]


def test_city_vacancy_uses_cities():
    f = build_filters(NL_BACKEND, {}, [])
    assert f["cities"] == ["Amsterdam", "Utrecht", "Rotterdam", "Eindhoven"]
    assert "countries" not in f


def test_passes_hard():
    ok = {"location": {"country": "Germany", "city": "Berlin"}, "years_experience": 4,
          "needs_sponsorship": False, "part_time_only": False}
    assert passes_hard(AI, ok)
    assert not passes_hard(AI, {**ok, "needs_sponsorship": True})
    assert not passes_hard(AI, {**ok, "part_time_only": True})
    assert not passes_hard(AI, {**ok, "years_experience": 2})
    assert not passes_hard(AI, {**ok, "location": {"country": "Norway", "city": "Oslo"}})
