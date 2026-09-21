"""Values: the Alarm record, time parsing, and ID generation.

Pure. This module imports nothing from the project and performs no I/O, which is
what makes it verifiable by reading it.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Dict, Iterable, Optional

_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$", re.ASCII)
_ID_LENGTH = 6
_TIME_HELP = "expected 24-hour HH:MM, for example 07:30"


def parse_hhmm(text: str) -> time:
    """Parse a 24-hour time. Accepts `7:30` and `07:30`; rejects everything else.

    Raises ValueError carrying a message meant for the user's eyes.
    """
    raw = (text or "").strip()
    match = _HHMM_RE.match(raw)
    if not match:
        raise ValueError("invalid time {!r}: {}".format(text, _TIME_HELP))

    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError(
            "invalid time {!r}: hour must be 00-23 and minute 00-59".format(text)
        )
    return time(hour, minute)


def format_hhmm(value: time) -> str:
    """Canonical zero-padded representation."""
    return "{:02d}:{:02d}".format(value.hour, value.minute)


def format_when(moment: datetime) -> str:
    """Absolute date-time for user-facing output, e.g. `Tue 22 Sep 2026 07:30`."""
    return moment.strftime("%a %d %b %Y %H:%M")


def new_id(existing: Iterable[str]) -> str:
    """A short, typable, unique id. Retried on the (vanishingly rare) collision."""
    taken = set(existing)
    while True:
        candidate = uuid.uuid4().hex[:_ID_LENGTH]
        if candidate not in taken:
            return candidate


@dataclass
class Alarm:
    """One scheduled alarm, as stored on disk."""

    id: str
    time: str  # canonical "HH:MM"
    label: str
    enabled: bool
    created_at: str  # ISO-8601 local, with offset
    last_fired_at: Optional[str] = None

    @classmethod
    def create(
        cls, alarm_id: str, at: time, label: str, created_at: datetime
    ) -> "Alarm":
        return cls(
            id=alarm_id,
            time=format_hhmm(at),
            label=label or "",
            enabled=True,
            created_at=created_at.astimezone().isoformat(timespec="seconds"),
            last_fired_at=None,
        )

    @property
    def time_of_day(self) -> time:
        """The stored time as a value. Safe because the store is validated on load."""
        return parse_hhmm(self.time)

    def describe(self) -> str:
        """Short identification for log lines, e.g. `a3f91c 07:30 "Standup"`."""
        if self.label:
            return '{} {} "{}"'.format(self.id, self.time, self.label)
        return "{} {}".format(self.id, self.time)

    # -- serialisation: the only place field names are spelled ---------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "time": self.time,
            "label": self.label,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_fired_at": self.last_fired_at,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "Alarm":
        """Rebuild from stored JSON, validating as we go.

        The run loop must never have to defend itself against a malformed alarm,
        so everything is checked here, at the edge. Raises ValueError.
        """
        if not isinstance(raw, dict):
            raise ValueError("alarm entry is not an object")

        for field in ("id", "time", "label", "created_at"):
            if not isinstance(raw.get(field), str):
                raise ValueError("alarm entry has a missing or invalid {!r}".format(field))

        if not isinstance(raw.get("enabled"), bool):
            raise ValueError("alarm entry has a missing or invalid 'enabled'")

        last_fired = raw.get("last_fired_at")
        if last_fired is not None and not isinstance(last_fired, str):
            raise ValueError("alarm entry has an invalid 'last_fired_at'")

        at = parse_hhmm(raw["time"])  # rejects a hand-edited bad time

        return cls(
            id=raw["id"],
            time=format_hhmm(at),
            label=raw["label"],
            enabled=raw["enabled"],
            created_at=raw["created_at"],
            last_fired_at=last_fired,
        )
