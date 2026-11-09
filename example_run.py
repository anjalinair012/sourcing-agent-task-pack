"""Thirty seconds with the provider, so you do not spend your budget learning the API.

Run from your repository root:   python3 example_run.py
"""
import json, time
from sourcing_provider import SourcingProvider, RateLimited, ProviderError, QuotaExceeded

vac = json.load(open("data/vacancies.json"))
v = vac[0]
hr = v["hard_requirements"]

p = SourcingProvider(run_id="example", reset=True)

def call(fn, **kw):
    """The provider is flaky on purpose. Something like this is the minimum."""
    for attempt in range(5):
        try:
            return fn(**kw)
        except RateLimited as e:
            time.sleep(e.retry_after)
        except ProviderError:
            time.sleep(0.2 * (attempt + 1))
    raise RuntimeError("provider would not answer")

# Counting is free. Measure the space before you spend quota in it.
broad = call(p.count, tag=v["id"], countries=hr["location_countries"], min_years=hr["min_years"])
tight = call(p.count, tag=v["id"], countries=hr["location_countries"], min_years=hr["min_years"],
             skills_all=["Python"], skills_any=["embeddings", "RAG", "vector search"])
print("%s: %d profiles meet the hard requirements; %d also look relevant" % (v["id"], broad, tight))

r = call(p.search, tag=v["id"], countries=hr["location_countries"], min_years=hr["min_years"],
         skills_all=["Python"], skills_any=["embeddings", "RAG", "vector search"],
         page=0, page_size=10)
print("got %d of %d, quota left %d" % (len(r.profiles), r.total_count, r.quota_remaining))
for x in r.profiles[:3]:
    print("  %s  %-28s %-22s %sy  %s" % (x["profile_id"], x["name"], x["current_title"],
                                         x["years_experience"], x["location"]["city"]))
print("\nEvery call above was written to .provider_audit/example.jsonl, have a look.")
