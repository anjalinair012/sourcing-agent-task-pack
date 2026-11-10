"""Command line entry point: `uv run sourcing-agent`."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from sourcing_provider import SourcingProvider

from .llm import LLM
from .loop import Ctx, run_all
from .report import write_outputs
from .state import State


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sourcing-agent", description=__doc__)
    p.add_argument("--vacancies", type=Path, default=Path("data/vacancies.json"))
    p.add_argument("--out", type=Path, default=Path("out"))
    p.add_argument("--run-id", default="main")
    p.add_argument("--fresh", action="store_true", help="ignore saved state and start over")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv()
    vacancies = json.loads(args.vacancies.read_text(encoding="utf-8"))

    state_path = args.out / "state.json"
    if args.fresh and state_path.exists():
        state_path.unlink() # Unix term for removing a file
    state = State(state_path)
    resuming = state.exists()
    # reset=True wipes the provider's quota counter, so only do it on a brand new run.
    provider = SourcingProvider(run_id=args.run_id, reset=not resuming)

    try:
        llm = LLM()
    except Exception as e:  # e.g. no API key
        print(f"Cannot create the LLM client: {e}\nSet ANTHROPIC_API_KEY (see .env.example).",
              file=sys.stderr)
        return 2

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())  # finish the current step, save, write outputs

    print(f"{'Resuming' if resuming else 'Starting'} run '{args.run_id}', "
          f"quota left {provider.quota_remaining()}", file=sys.stderr)
    started = time.time()
    ctx = Ctx(provider=provider, llm=llm, state=state, out_dir=args.out, stop=stop)
    try:
        run_all(ctx, vacancies)
    except anthropic.AuthenticationError:
        state.save()
        print("The Anthropic API rejected the key. Check ANTHROPIC_API_KEY in .env "
              "(format: ANTHROPIC_API_KEY=sk-ant-..., no quotes). Progress is saved; rerun to resume.",
              file=sys.stderr)
        return 2
    state.data["elapsed_s"] = state.data.get("elapsed_s", 0) + time.time() - started
    state.save()
    write_outputs(state, vacancies, llm, args.out)
    print(f"Done. LLM cost ${llm.cost:.2f}. Outputs in {args.out}/", file=sys.stderr)
    return 130 if stop.is_set() else 0


if __name__ == "__main__":
    raise SystemExit(main())
