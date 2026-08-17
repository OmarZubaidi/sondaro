"""The hours a show occupies, as the card renders them.

A start time on its own answers "when do I leave". Only the pair answers "am I
driving home at one in the morning", which is the question that decides whether
a Tuesday show is worth it. Providers publish an end for a minority of
listings, so the rest are estimated — and an estimate has to say so.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.providers.base import Event  # noqa: E402
from api.scan import ends  # noqa: E402


def an_event(**overrides) -> Event:
    return Event(
        **{
            "provider": "ticketmaster",
            "provider_event_id": "tm1",
            "artist_name": "Sabaton",
            "date": "2026-09-10",
            "time": "20:00",
            **overrides,
        }
    )


def test_a_published_end_is_reported_as_fact():
    assert ends(an_event(end_date="2026-09-10", end_time="23:00")) == ("23:00", None, False)


def test_an_unstated_end_is_the_assumed_set_length_and_says_so():
    """Every provider leaves this out most of the time. Three hours is a useful
    thing to plan around; three hours presented as the venue's own curfew is a
    claim nobody made."""
    assert ends(an_event()) == ("23:00", None, True)


def test_doors_still_tba_get_no_end_at_all():
    """There is nothing to add three hours to, and inventing both ends of a
    show we can't even say starts in the evening is not an estimate."""
    assert ends(an_event(time=None)) == (None, None, False)


def test_the_end_date_is_only_given_when_it_differs_from_the_start():
    """Repeating the start date underneath the start date tells you nothing,
    and the card has one narrow column to say all of this in."""
    assert ends(an_event(end_date="2026-09-10", end_time="23:00"))[1] is None
    assert ends(an_event(end_date="2026-09-13", end_time="22:00"))[1] == "2026-09-13"


def test_an_estimate_that_runs_past_midnight_carries_tomorrow_with_it():
    """23:00 doors means the estimate lands at 02:00 — on the following day,
    which is exactly the fact that changes the plan."""
    assert ends(an_event(time="23:00")) == ("02:00", "2026-09-11", True)


def test_a_malformed_clock_produces_no_end_rather_than_a_wrong_one():
    assert ends(an_event(time="doors at eight")) == (None, None, False)
