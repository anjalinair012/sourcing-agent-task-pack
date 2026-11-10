import json
from pathlib import Path

from sourcing_agent.scoring import grade

VAC = json.loads(Path("data/vacancies.json").read_text(encoding="utf-8"))[1]  # senior backend
PROFILE = {"profile_id": "P", "headline": "Backend Engineer", "years_experience": 7.8,
           "skills": ["Python", "PostgreSQL"], "summary": ""}


def answer(index, quote, met=True):
    return [{"index": index, "met": met, "quote": quote}]


def test_quote_must_be_verbatim_from_the_profile():
    assert grade(VAC, PROFILE, answer(1, "PostgreSQL"))["hits"]
    assert not grade(VAC, PROFILE, answer(1, "Postgres 15 expert"))["hits"]  # invented text


def test_years_experience_can_be_quoted():
    assert grade(VAC, PROFILE, answer(0, "7.8"))["hits"]


def test_silence_is_not_met():
    result = grade(VAC, PROFILE, answer(2, "", met=False))
    assert not result["hits"] and not result["passed"]
