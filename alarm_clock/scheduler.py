"""When does an alarm next go off, and what should the loop do about it now.

Pure, and deliberately free of `datetime.now()`: every function takes `now` as a
parameter, so any moment in time - midnight, a DST boundary - can be examined
without waiting for it.
"""

from datetime import datetime, time, timedelta
from typing import Iterable, List

from alarm_clock.models import Alarm

WAIT = "wait"
FIRE = "fire"
MISSED = "missed"


def next_occurrence(at: time, now: datetime) -> datetime:
    """The smallest datetime `d` where `d.time() == at` and `d > now`.

    Strictly greater than now: an alarm added during its own minute rolls to
    tomorrow. Predictable, and the CLI prints the resolved time so it is never a
    surprise (requirements FR-1).
    """
    today = datetime.combine(now.date(), at)
    return today if today > now else today + timedelta(days=1)


def snooze_until(now: datetime, minutes: int) -> datetime:
    return now + timedelta(minutes=minutes)


def classify(next_fire: datetime, now: datetime, catchup_seconds: int) -> str:
    """Decide what the run loop does with a scheduled alarm this tick.

    An alarm whose moment passed while the machine was asleep should not go off
    hours later, so anything later than the catch-up window is MISSED, not FIRE
    (requirements FR-9).
    """
    if now < next_fire:
        return WAIT
    lateness = (now - next_fire).total_seconds()
    return FIRE if lateness <= catchup_seconds else MISSED


def resolve_id(token: str, alarms: Iterable[Alarm]) -> Alarm:
    """Find an alarm by exact id or by unambiguous prefix (requirements FR-11)."""
    candidates: List[Alarm] = list(alarms)
    needle = (token or "").strip().lower()

    for alarm in candidates:
        if alarm.id == needle:
            return alarm

    matches = [alarm for alarm in candidates if alarm.id.startswith(needle)]
    if not needle or not matches:
        raise ValueError("no alarm with id {!r}".format(token))
    if len(matches) > 1:
        listed = ", ".join(sorted(alarm.id for alarm in matches))
        raise ValueError("id {!r} is ambiguous: matches {}".format(token, listed))
    return matches[0]


def sort_for_display(alarms: Iterable[Alarm], now: datetime) -> List[Alarm]:
    """Enabled alarms first by next fire time, then disabled ones by clock time."""
    return sorted(
        alarms,
        key=lambda alarm: (
            not alarm.enabled,
            next_occurrence(alarm.time_of_day, now) if alarm.enabled else datetime.max,
            alarm.time,
            alarm.id,
        ),
    )
