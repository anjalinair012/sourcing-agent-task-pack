"""Re-score the profiles a gold run already bought (no provider quota used) and compare with gold.

Run from the repo root:  PYTHONUTF8=1 uv run python reports/rescore_gold.py out_gold
"""
import collections
import json
import sys

from dotenv import load_dotenv

from sourcing_agent.llm import LLM
from sourcing_agent.scoring import score_profiles

load_dotenv(".env")
state = json.load(open(sys.argv[1] + "/state.json", encoding="utf-8"))["vacancies"]
gold = json.load(open("data/gold_relevance.json", encoding="utf-8"))["labels"]
vacs = {v["id"]: v for v in json.load(open("data/vacancies.json", encoding="utf-8"))}
llm = LLM()

for vid, v in state.items():
    profiles = [v["seen"][p] for p, s in v["scores"].items() if not s.get("dropped")]
    new = score_profiles(llm, vacs[vid], profiles)
    for label, scores in (("before", {p: v["scores"][p] for p in new}), ("after", new)):
        passed = [p for p, s in scores.items() if s["passed"]]
        strong = [p for p in scores if gold[vid][p] == 2]
        tp = [p for p in passed if gold[vid][p] == 2]
        print(f"{vid} {label}: passed={len(passed)} gold-labels of passed="
              f"{dict(collections.Counter(gold[vid][p] for p in passed))} "
              f"caught {len(tp)} of {len(strong)} gold-strong in the bought set")
    missed = [p for p in new if gold[vid][p] == 2 and not new[p]["passed"]]
    for p in missed:
        print("   still missed:", p, "missing", new[p]["missing"])
print(f"LLM cost ${llm.cost:.3f}")
