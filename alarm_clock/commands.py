"""One function per subcommand. Each returns the process exit code.

Anything that can go wrong for an ordinary reason - a bad time, an unknown id, an
unreadable store - is raised as ValueError or StoreError and turned into a single
sentence by `cli.main`. Tracebacks are reserved for genuine bugs.
"""

import sys
from datetime import datetime
from typing import List, Sequence

from alarm_clock import storage
from alarm_clock.models import Alarm, format_when, new_id, parse_hhmm
from alarm_clock.scheduler import next_occurrence, resolve_id, sort_for_display


def cmd_add(time_text: str, label: str, path=None) -> int:
    at = parse_hhmm(time_text)
    alarms = storage.load(path)

    alarm = Alarm.create(
        alarm_id=new_id(existing=[item.id for item in alarms]),
        at=at,
        label=label or "",
        created_at=datetime.now(),
    )
    alarms.append(alarm)
    storage.save(alarms, path)

    first_ring = next_occurrence(at, datetime.now())
    print("Added {} - first ring {}".format(alarm.describe(), format_when(first_ring)))
    return 0


def cmd_list(show_all: bool, path=None) -> int:
    alarms = storage.load(path)
    visible = alarms if show_all else [alarm for alarm in alarms if alarm.enabled]

    if not visible:
        if alarms and not show_all:
            print("No enabled alarms. See all of them with: alarm list --all")
        else:
            print("No alarms yet. Add one with: alarm add 07:30")
        return 0

    now = datetime.now()
    rows = []
    for alarm in sort_for_display(visible, now):
        when = format_when(next_occurrence(alarm.time_of_day, now)) if alarm.enabled else "-"
        rows.append(
            (alarm.id, alarm.time, alarm.label or "-", when, "on" if alarm.enabled else "off")
        )

    headers = ("ID", "TIME", "LABEL", "NEXT FIRE") + (("STATUS",) if show_all else ())
    trimmed = [row if show_all else row[:4] for row in rows]
    _print_table(headers, trimmed)
    return 0


def cmd_remove(tokens: Sequence[str], path=None) -> int:
    alarms = storage.load(path)
    doomed: List[Alarm] = []
    failures: List[str] = []

    for token in tokens:
        try:
            alarm = resolve_id(token, alarms)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        if alarm not in doomed:
            doomed.append(alarm)

    if doomed:
        remaining = [alarm for alarm in alarms if alarm not in doomed]
        storage.save(remaining, path)
        for alarm in doomed:
            print("Removed {}".format(alarm.describe()))

    # A bad id must not cost the user the good ones in the same call (FR-3).
    sys.stdout.flush()  # keep the two streams in order when output is redirected
    for message in failures:
        print(message, file=sys.stderr)
    return 1 if failures else 0


def cmd_enable(token: str, path=None) -> int:
    return _set_enabled(token, True, path)


def cmd_disable(token: str, path=None) -> int:
    return _set_enabled(token, False, path)


def _set_enabled(token: str, enabled: bool, path=None) -> int:
    alarms = storage.load(path)
    alarm = resolve_id(token, alarms)

    if alarm.enabled == enabled:
        # Idempotent: saying it twice is not an error (FR-4).
        state = "already enabled" if enabled else "already disabled"
        print("{} is {}".format(alarm.describe(), state))
        if enabled:
            _print_next(alarm)
        return 0

    alarm.enabled = enabled
    storage.save(alarms, path)

    if enabled:
        print("Enabled {}".format(alarm.describe()))
        _print_next(alarm)
    else:
        print("Disabled {}".format(alarm.describe()))
    return 0


def _print_next(alarm: Alarm) -> None:
    print("  next ring {}".format(format_when(next_occurrence(alarm.time_of_day, datetime.now()))))


def _print_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))

    def line(cells: Sequence[str]) -> str:
        return "  ".join(str(cell).ljust(widths[index]) for index, cell in enumerate(cells)).rstrip()

    print(line(headers))
    for row in rows:
        print(line(row))
