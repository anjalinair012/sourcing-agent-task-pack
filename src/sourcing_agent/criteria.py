"""Turns a vacancy into provider filters, and checks profiles against hard requirements.

Hard requirements always come from the vacancy file and are added by code. The LLM can only
suggest the "soft" filters below, so it has no way to widen the brief.
"""

from __future__ import annotations

# Filters the LLM is allowed to choose.
SOFT_KEYS = {"keywords", "keywords_all", "titles", "skills_any", "skills_all", "seniority",
             "native_language"}


def hard_filters(vacancy: dict) -> dict:
    """Provider filters for the hard requirements the provider can filter on."""
    hr = vacancy["hard_requirements"]
    filters = {}
    if hr.get("location_countries"):
        filters["countries"] = hr["location_countries"]
    if hr.get("location_cities"):
        filters["cities"] = hr["location_cities"]
    if hr.get("min_years") is not None:
        filters["min_years"] = hr["min_years"]
    return filters


def build_filters(vacancy: dict, soft: dict, exclude_ids: list[str]) -> dict:
    """Hard filters + the allowed soft filters + ids we already have."""
    filters = {k: v for k, v in soft.items() if k in SOFT_KEYS and v}
    filters.update(hard_filters(vacancy))  # applied last, so soft can never override them
    if exclude_ids:
        filters["exclude_profile_ids"] = exclude_ids
    return filters


def passes_hard(vacancy: dict, p: dict) -> bool:
    """Full hard-requirement check on a profile, including what the provider cannot filter."""
    hr = vacancy["hard_requirements"]
    loc = p.get("location") or {}
    if hr.get("location_countries") and loc.get("country") not in hr["location_countries"]:
        return False
    if hr.get("location_cities") and loc.get("city") not in hr["location_cities"]:
        return False
    if (p.get("years_experience") or 0) < hr.get("min_years", 0):
        return False
    if hr.get("employment") == "full_time" and p.get("part_time_only"):
        return False
    if hr.get("work_authorization") == "no_sponsorship_available" and p.get("needs_sponsorship"):
        return False
    return True
