from sourcing_agent.loop import dry_rounds


def rounds(*pairs):
    """Trace entries from (returned, passed) pairs."""
    return [{"observed": {"returned": r, "passed": p}} for r, p in pairs]


def test_counts_rounds_that_bought_profiles_but_found_nothing():
    assert dry_rounds(rounds((3, 0)), returned=25, passed_now=0) == 2


def test_rounds_that_bought_nothing_are_skipped():
    assert dry_rounds(rounds((0, 0), (0, 0)), returned=0, passed_now=0) == 0
    assert dry_rounds(rounds((25, 0), (0, 0), (25, 0)), returned=25, passed_now=0) == 3


def test_a_strong_find_resets_the_count():
    assert dry_rounds(rounds((25, 2), (25, 0)), returned=25, passed_now=0) == 2
    assert dry_rounds(rounds((25, 0), (25, 2)), returned=25, passed_now=0) == 1
