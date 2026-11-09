import json
from pathlib import Path

import sourcing_agent
from sourcing_agent.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent


def test_package_imports():
    assert sourcing_agent.__version__


def test_cli_defaults():
    args = build_parser().parse_args([])
    assert args.out == Path("out")


def test_vacancies_have_required_keys():
    vacancies = json.loads((ROOT / "data" / "vacancies.json").read_text(encoding="utf-8"))
    assert len(vacancies) == 4
    for v in vacancies:
        assert {"id", "hard_requirements", "rubric"} <= v.keys()
