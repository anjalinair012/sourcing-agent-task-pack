"""Compare the agent's judgements with the recruiter gold labels (offline check only)."""
import collections
import json
import sys

state = json.load(open(sys.argv[1] + "/state.json", encoding="utf-8"))["vacancies"]
gold = json.load(open("data/gold_relevance.json", encoding="utf-8"))["labels"]
vacs = {v["id"]: v for v in json.load(open("data/vacancies.json", encoding="utf-8"))}
shortlist = json.load(open(sys.argv[1] + "/shortlist.json", encoding="utf-8"))

for vid, v in state.items():
    if vid not in gold:
        continue  # no recruiter labels for this vacancy
    g = gold[vid]
    n_gold_strong = sum(1 for x in g.values() if x == 2)
    scores = v["scores"]
    scored = {p: s for p, s in scores.items() if not s.get("dropped")}
    passed = [p for p, s in scored.items() if s["passed"]]
    strong_seen = [p for p in v["seen"] if g[p] == 2]
    print(f"\n=== {vid} {vacs[vid]['title']} ===")
    print(f"stop_reason={v['stop_reason']} iterations={v['iteration']} bought={v['spent']} "
          f"target={vacs[vid]['target_strong']} gold_strong_in_db={n_gold_strong}")
    print(f"dropped by hard check (sponsorship/part-time): {sum(1 for s in scores.values() if s.get('dropped'))}"
          f"  -> gold labels of those: {dict(collections.Counter(g[p] for p, s in scores.items() if s.get('dropped')))}")
    print(f"agent passed={len(passed)}; gold labels of passed: {dict(collections.Counter(g[p] for p in passed))}")
    tp = sum(1 for p in passed if g[p] == 2)
    print(f"precision (passed that are gold-strong): {tp}/{len(passed)}")
    print(f"gold-strong among everything bought: {len(strong_seen)}; agent caught {tp} of them "
          f"(recall within bought {tp}/{len(strong_seen)})")
    print(f"strong found per 100 profiles bought (gold-strong in bought): {100 * len(strong_seen) / max(1, v['spent']):.1f}")
    print(f"gold-strong still unseen: {n_gold_strong - len(strong_seen)}")
    missed = [p for p in strong_seen if p not in passed]
    print(f"gold-strong bought but agent did not pass: {len(missed)}")
    for p in missed[:5]:
        s = scores[p]
        print(f"   {p} agent score {s['score']} missing {s['missing']}")
    fp = [p for p in passed if g[p] != 2]
    print(f"passed but gold says {sorted(set(g[p] for p in fp))}: {len(fp)}")
    by_label = collections.defaultdict(list)
    for p, s in scored.items():
        by_label[g[p]].append(s["score"])
    print("mean agent score by gold label:",
          {k: round(sum(x) / len(x), 2) for k, x in sorted(by_label.items())})
    sl = shortlist[vid]
    print(f"shortlist ({len(sl)}): gold labels {dict(collections.Counter(g[i['profile_id']] for i in sl))}")
    print("trace passed per round:", [t["observed"]["passed"] for t in v["trace"]],
          "total_count per round:", [t["observed"]["total_count"] for t in v["trace"]])
