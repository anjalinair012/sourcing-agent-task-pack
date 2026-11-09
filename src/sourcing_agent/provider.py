"""Calls to the search provider, with the retry handling it needs."""

from __future__ import annotations

import time

from sourcing_provider import ProviderError, QuotaExceeded, RateLimited

__all__ = ["QuotaExceeded", "ProviderUnavailable", "call"]


class ProviderUnavailable(RuntimeError):
    """The provider kept failing after several retries."""


def call(fn, attempts: int = 6, **kwargs):
    """Call a provider method. Waits out rate limits, retries 502s and timeouts.

    QuotaExceeded is not retried: it means the run's quota is gone for good.
    """
    for attempt in range(attempts):
        try:
            return fn(**kwargs)
        except RateLimited as e:
            time.sleep(e.retry_after)
        except ProviderError:
            time.sleep(0.2 * (attempt + 1))
    raise ProviderUnavailable(f"provider failed {attempts} times in a row")
