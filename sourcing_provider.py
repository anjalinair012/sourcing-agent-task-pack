"""Fake sourcing provider, stands in for a LinkedIn-Recruiter-style search API.

Standard library only. Deterministic given the same run_id, so your runs are reproducible.

    from sourcing_provider import SourcingProvider, RateLimited, ProviderError, QuotaExceeded

    p = SourcingProvider(run_id="my-run", reset=True)     # reset once, at the start of a run
    n = p.count(countries=["Netherlands"], skills_all=["Python"])        # FREE, no quota
    r = p.search(countries=["Netherlands"], skills_all=["Python"], page=0, page_size=25)
    r.total_count, r.profiles, r.quota_remaining

THINGS THAT WILL HAPPEN TO YOU, because they happen in production:

  * `count()` costs no profile quota. `search()` costs ONE UNIT PER PROFILE RETURNED.
  * The whole run shares a quota of 1500 profiles across every vacancy. It does not reset.
  * Roughly 6% of calls fail with ProviderError and 2% time out. Neither costs quota.
  * Calls are rate limited. Over the limit raises RateLimited, which carries `retry_after`.
  * page_size is capped at 50 and page at 19, so you cannot page past 1000 results.

Every call is appended to `.provider_audit/<run_id>.jsonl`. **Commit that directory.**
It is the record of what your agent actually did, and it is what we read.

FILTERS (all optional, all combine with AND):

    keywords      list[str]  profile must contain AT LEAST ONE (searched over headline,
                             summary, current title, current company and skills)
    keywords_all  list[str]  profile must contain ALL of these
    titles        list[str]  substring match against current_title or headline (OR)
    countries     list[str]  exact match on location.country (OR)
    cities        list[str]  exact match on location.city (OR)
    skills_any    list[str]  at least one skill matches (OR, case-insensitive substring)
    skills_all    list[str]  every one of these matches
    min_years     float      years_experience >= x
    max_years     float      years_experience <= x
    seniority     list[str]  one of intern/entry/junior/mid/senior/lead (OR)
    companies     list[str]  substring match on current_company (OR)
    native_language list[str] first listed language (OR)
    open_to_work  bool
    exclude_profile_ids list[str]

Both calls also take `tag=`, recorded in the audit log, otherwise ignored. Pass the
vacancy id you are working on so a call can be attributed to a vacancy afterwards.

Results are ordered by how many of your optional signals a profile matched, then by
profile_id. The order is stable, so paging is stable.
"""
import hashlib
import json
import os
import time

QUOTA_PROFILES = 1500
MAX_PAGE_SIZE = 50
MAX_PAGE = 19
RATE_CALLS = 8            # calls allowed ...
RATE_WINDOW = 5.0         # ... per this many seconds
ERROR_RATE = 0.06
TIMEOUT_RATE = 0.02
BASE_LATENCY = 0.05

HERE = os.path.dirname(os.path.abspath(__file__))
def _find_data():
    if os.environ.get("SOURCING_PROFILES"):
        return os.environ["SOURCING_PROFILES"]
    for base in (HERE, os.getcwd(), os.path.join(HERE, ".."), os.path.join(os.getcwd(), "..")):
        p = os.path.join(base, "data", "profiles.jsonl")
        if os.path.exists(p):
            return p
    return os.path.join(HERE, "data", "profiles.jsonl")

DATA = _find_data()
# The audit lands in the working directory, i.e. YOUR repository root, so it is committed
# alongside your code. Override with SOURCING_AUDIT_DIR if your layout needs it.
AUDIT_DIR = os.environ.get("SOURCING_AUDIT_DIR") or os.path.join(os.getcwd(), ".provider_audit")


class ProviderError(RuntimeError):
    """The upstream returned a 5xx. Nothing was charged. Retrying is reasonable."""


class ProviderTimeout(ProviderError):
    """The upstream did not answer in time. Nothing was charged."""


class RateLimited(RuntimeError):
    def __init__(self, retry_after):
        super().__init__("rate limited; retry after %.2fs" % retry_after)
        self.retry_after = retry_after


class QuotaExceeded(RuntimeError):
    """The run's profile quota is spent. It does not reset. Nothing else will be returned."""


class SearchResult:
    def __init__(self, total_count, page, page_size, profiles, quota_remaining):
        self.total_count = total_count
        self.page = page
        self.page_size = page_size
        self.profiles = profiles
        self.quota_remaining = quota_remaining

    def __repr__(self):
        return "<SearchResult total=%d page=%d returned=%d quota_left=%d>" % (
            self.total_count, self.page, len(self.profiles), self.quota_remaining)


def _norm(s):
    return str(s or "").lower()


class SourcingProvider:
    def __init__(self, run_id="default", reset=False, data_path=None, latency=True):
        self.run_id = run_id
        self.latency = latency
        os.makedirs(AUDIT_DIR, exist_ok=True)
        self.audit_path = os.path.join(AUDIT_DIR, "%s.jsonl" % run_id)
        self.state_path = os.path.join(AUDIT_DIR, "%s.state.json" % run_id)
        if reset:
            for p in (self.audit_path, self.state_path):
                if os.path.exists(p):
                    os.remove(p)
        self._profiles = []
        with open(data_path or DATA) as f:
            for line in f:
                if line.strip():
                    self._profiles.append(json.loads(line))
        self._index = [(p, self._blob(p)) for p in self._profiles]
        self._append({"op": "session_start", "run_id": run_id, "profiles_loaded": len(self._profiles)})

    # ---------------------------------------------------------------- state
    def _state(self):
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                return json.load(f)
        return {"calls": 0, "quota_used": 0, "recent": []}

    def _save(self, st):
        with open(self.state_path, "w") as f:
            json.dump(st, f)

    def quota_remaining(self):
        return max(0, QUOTA_PROFILES - self._state()["quota_used"])

    def calls_made(self):
        return self._state()["calls"]

    def _append(self, rec):
        rec["ts"] = round(time.time(), 3)
        with open(self.audit_path, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    # ---------------------------------------------------------------- faults
    def _roll(self, call_index):
        h = hashlib.sha256(("%s:%d" % (self.run_id, call_index)).encode()).digest()
        return int.from_bytes(h[:6], "big") / float(1 << 48)

    def _gate(self, op, filters, page, page_size):
        """Rate limit, then fault injection. Returns the call index."""
        st = self._state()
        now = time.time()
        recent = [t for t in st["recent"] if now - t < RATE_WINDOW]
        if len(recent) >= RATE_CALLS:
            wait = round(RATE_WINDOW - (now - recent[0]), 2)
            st["recent"] = recent
            self._save(st)
            self._append({"op": op, "call": st["calls"], "filters": filters, "page": page,
                          "page_size": page_size, "outcome": "rate_limited", "retry_after": wait})
            raise RateLimited(max(0.05, wait))
        st["calls"] += 1
        idx = st["calls"]
        recent.append(now)
        st["recent"] = recent[-RATE_CALLS:]
        self._save(st)
        if self.latency:
            time.sleep(BASE_LATENCY + 0.1 * self._roll(idx + 99991))
        r = self._roll(idx)
        if r < TIMEOUT_RATE:
            self._append({"op": op, "call": idx, "filters": filters, "page": page,
                          "page_size": page_size, "outcome": "timeout"})
            raise ProviderTimeout("upstream timeout")
        if r < TIMEOUT_RATE + ERROR_RATE:
            self._append({"op": op, "call": idx, "filters": filters, "page": page,
                          "page_size": page_size, "outcome": "error_502"})
            raise ProviderError("upstream returned 502")
        return idx

    # ---------------------------------------------------------------- matching
    @staticmethod
    def _blob(p):
        return _norm(" ".join([
            p.get("headline", ""), p.get("summary", ""), p.get("current_title", ""),
            p.get("current_company", ""), " ".join(p.get("skills") or []),
        ]))

    @staticmethod
    def _skill_hit(want, skills):
        w = _norm(want)
        return any(w in _norm(s) or _norm(s) in w for s in skills)

    def _match(self, p, blob, f):
        loc = p.get("location") or {}
        if f.get("countries") and loc.get("country") not in f["countries"]:
            return None
        if f.get("cities") and loc.get("city") not in f["cities"]:
            return None
        if f.get("min_years") is not None and (p.get("years_experience") or 0) < f["min_years"]:
            return None
        if f.get("max_years") is not None and (p.get("years_experience") or 0) > f["max_years"]:
            return None
        if f.get("seniority") and p.get("seniority") not in f["seniority"]:
            return None
        if f.get("open_to_work") is not None and bool(p.get("open_to_work")) != bool(f["open_to_work"]):
            return None
        if f.get("native_language"):
            langs = p.get("languages") or []
            if not langs or langs[0] not in f["native_language"]:
                return None
        if f.get("companies") and not any(_norm(c) in _norm(p.get("current_company")) for c in f["companies"]):
            return None
        if f.get("exclude_profile_ids") and p["profile_id"] in set(f["exclude_profile_ids"]):
            return None
        skills = p.get("skills") or []
        for s in f.get("skills_all") or []:
            if not self._skill_hit(s, skills):
                return None
        for k in f.get("keywords_all") or []:
            if _norm(k) not in blob:
                return None
        if f.get("titles"):
            t = _norm(p.get("current_title")) + " " + _norm(p.get("headline"))
            if not any(_norm(x) in t for x in f["titles"]):
                return None
        score = 0
        if f.get("keywords"):
            hits = sum(1 for k in f["keywords"] if _norm(k) in blob)
            if hits == 0:
                return None
            score += hits
        if f.get("skills_any"):
            hits = sum(1 for s in f["skills_any"] if self._skill_hit(s, skills))
            if hits == 0:
                return None
            score += hits
        return score

    def _candidates(self, f):
        out = []
        for p, blob in self._index:
            sc = self._match(p, blob, f)
            if sc is not None:
                out.append((-sc, p["profile_id"], p))
        out.sort(key=lambda x: (x[0], x[1]))
        return [p for _, _, p in out]

    @staticmethod
    def _public(p):
        return {k: v for k, v in p.items() if not k.startswith("_")}

    # ---------------------------------------------------------------- API
    def count(self, tag=None, **filters):
        """How many profiles match. Costs no profile quota. But it is still a call.

        `tag` is recorded in the audit log and otherwise ignored. Pass the vacancy id
        you are working on; it is how we attribute a call to a vacancy when reviewing."""
        idx = self._gate("count", filters, None, None)
        n = len(self._candidates(filters))
        st = self._state()
        self._append({"op": "count", "call": idx, "tag": tag, "filters": filters, "total_count": n,
                      "quota_before": QUOTA_PROFILES - st["quota_used"],
                      "quota_after": QUOTA_PROFILES - st["quota_used"], "outcome": "ok"})
        return n

    def search(self, page=0, page_size=25, tag=None, **filters):
        """A page of matching profiles. Costs one quota unit per profile returned.

        `tag` is recorded in the audit log and otherwise ignored. Pass the vacancy id."""
        page = int(page)
        page_size = int(page_size)
        if page_size < 1 or page_size > MAX_PAGE_SIZE:
            raise ValueError("page_size must be between 1 and %d" % MAX_PAGE_SIZE)
        if page < 0 or page > MAX_PAGE:
            raise ValueError("page must be between 0 and %d" % MAX_PAGE)
        idx = self._gate("search", filters, page, page_size)
        st = self._state()
        left = QUOTA_PROFILES - st["quota_used"]
        if left <= 0:
            self._append({"op": "search", "call": idx, "tag": tag, "filters": filters, "page": page,
                          "page_size": page_size, "returned": 0, "quota_before": 0,
                          "quota_after": 0, "outcome": "quota_exceeded"})
            raise QuotaExceeded("profile quota for this run is spent")
        hits = self._candidates(filters)
        window = hits[page * page_size:(page + 1) * page_size]
        charged = min(len(window), left)
        window = window[:charged]
        st["quota_used"] += charged
        self._save(st)
        self._append({"op": "search", "call": idx, "tag": tag, "filters": filters, "page": page,
                      "page_size": page_size, "returned": charged, "total_count": len(hits),
                      "profile_ids": [p["profile_id"] for p in window],
                      "quota_before": left, "quota_after": left - charged,
                      "outcome": "ok" if charged == len(hits[page * page_size:(page + 1) * page_size])
                                 else "truncated_by_quota"})
        return SearchResult(len(hits), page, page_size, [self._public(p) for p in window],
                            QUOTA_PROFILES - st["quota_used"])
