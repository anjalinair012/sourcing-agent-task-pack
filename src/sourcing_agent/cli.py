"""Command line entry point: `uv run sourcing-agent`."""

from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sourcing-agent", description=__doc__)
    p.add_argument("--vacancies", type=Path, default=Path("data/vacancies.json"))
    p.add_argument("--out", type=Path, default=Path("out"))
    p.add_argument("--run-id", default="main")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # TODO: wire up the agent loop; writes out/trace.jsonl, shortlist.json, report.md
    raise NotImplementedError(f"agent loop not implemented yet (out={args.out})")


if __name__ == "__main__":
    raise SystemExit(main())
