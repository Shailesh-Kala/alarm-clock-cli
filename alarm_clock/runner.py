"""The foreground loop: the part that is actually an alarm clock.

Holds a schedule derived from the store, ticks once a second, and rings whatever
has come due. Closing the terminal stops it - that is the deal made in decision
D1 and it is stated plainly when the loop starts.
"""

import signal
import sys
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from alarm_clock import config, ringer, storage
from alarm_clock.models import Alarm, format_when
from alarm_clock.scheduler import FIRE, MISSED, classify, next_occurrence, snooze_until


@dataclass
class ScheduleEntry:
    """An armed alarm and the concrete moment it next goes off."""

    alarm: Alarm
    next_fire: datetime
    snoozes_used: int = 0


@dataclass
class RunOptions:
    ring_seconds: int = config.RING_SECONDS
    snooze_minutes: int = config.SNOOZE_MINUTES
    max_snoozes: int = config.MAX_SNOOZES
    once: bool = False
    path: Optional[Path] = None


class InterruptFlag:
    """Counts Ctrl-C presses so they can be interpreted in context.

    A signal handler that merely counts keeps the control flow on the page: no
    exception is thrown across the signal boundary, and the ring loop and the
    idle loop each decide for themselves what a press means (design section 8).
    """

    def __init__(self) -> None:
        self._pending = 0
        self._previous = None

    def install(self) -> None:
        self._previous = signal.signal(signal.SIGINT, self._handle)

    def restore(self) -> None:
        if self._previous is not None:
            signal.signal(signal.SIGINT, self._previous)

    def _handle(self, signum, frame) -> None:  # noqa: D401 - signal handler
        self._pending += 1

    def take(self) -> int:
        """Return the number of presses since the last call, and clear them."""
        pending, self._pending = self._pending, 0
        return pending


@dataclass
class Runner:
    options: RunOptions
    schedule: Dict[str, ScheduleEntry] = field(default_factory=dict)
    interrupts: InterruptFlag = field(default_factory=InterruptFlag)
    _fingerprint: Optional[storage.Fingerprint] = None

    # -- entry point ---------------------------------------------------------

    def run(self) -> int:
        # The loop is long-lived, so its output must arrive as it happens rather
        # than when a block buffer happens to fill. Without this, redirecting to
        # a file or piping to `tee` shows nothing for minutes at a time.
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except (AttributeError, OSError):
            pass

        self._load_schedule(datetime.now(), announce=False)
        self._print_startup()

        self.interrupts.install()
        try:
            return self._loop()
        finally:
            self.interrupts.restore()

    def _loop(self) -> int:
        while True:
            if self.interrupts.take():
                print("\nStopped.")
                return 0

            now = datetime.now()
            self._reload_if_changed(now)

            for entry in self._due(now):
                outcome = self._handle_due(entry, now)
                if outcome == "exit":
                    print("\nStopped.")
                    return 0
                if outcome == "finished" and self.options.once:
                    print("Done (--once).")
                    return 0
                now = datetime.now()

            if not self._sleep(config.TICK_SECONDS):
                print("\nStopped.")
                return 0

    # -- schedule ------------------------------------------------------------

    def _load_schedule(self, now: datetime, announce: bool) -> None:
        """Rebuild the schedule from the store, keeping state for alarms that stayed."""
        alarms = storage.load(self.options.path)
        self._fingerprint = storage.fingerprint(self.options.path)
        armed = {alarm.id: alarm for alarm in alarms if alarm.enabled}

        for alarm_id in list(self.schedule):
            if alarm_id not in armed:
                dropped = self.schedule.pop(alarm_id)
                if announce:
                    print("  - no longer watching {}".format(dropped.alarm.describe()))

        for alarm_id, alarm in armed.items():
            existing = self.schedule.get(alarm_id)
            if existing is None:
                self.schedule[alarm_id] = ScheduleEntry(
                    alarm=alarm, next_fire=next_occurrence(alarm.time_of_day, now)
                )
                if announce:
                    print(
                        "  + now watching {} - {}".format(
                            alarm.describe(),
                            format_when(self.schedule[alarm_id].next_fire),
                        )
                    )
            elif existing.alarm.time != alarm.time:
                existing.alarm = alarm
                existing.next_fire = next_occurrence(alarm.time_of_day, now)
                existing.snoozes_used = 0
                if announce:
                    print(
                        "  ~ rescheduled {} - {}".format(
                            alarm.describe(), format_when(existing.next_fire)
                        )
                    )
            else:
                existing.alarm = alarm

    def _reload_if_changed(self, now: datetime) -> None:
        """Pick up `alarm add` or `alarm remove` run in another terminal (FR-5)."""
        if storage.fingerprint(self.options.path) == self._fingerprint:
            return
        try:
            self._load_schedule(now, announce=True)
        except storage.StoreError as exc:
            print("  ! store unreadable, keeping current alarms: {}".format(exc), file=sys.stderr)
            self._fingerprint = storage.fingerprint(self.options.path)

    def _due(self, now: datetime) -> List[ScheduleEntry]:
        ready = [entry for entry in self.schedule.values() if now >= entry.next_fire]
        return sorted(ready, key=lambda entry: entry.next_fire)

    # -- firing --------------------------------------------------------------

    def _handle_due(self, entry: ScheduleEntry, now: datetime) -> str:
        verdict = classify(entry.next_fire, now, config.CATCHUP_SECONDS)

        if verdict == MISSED:
            print(
                "{}  missed {} - scheduled {}, machine was unavailable".format(
                    now.strftime("%H:%M:%S"), entry.alarm.describe(), format_when(entry.next_fire)
                )
            )
            entry.next_fire = next_occurrence(entry.alarm.time_of_day, now)
            entry.snoozes_used = 0
            print("           next ring {}".format(format_when(entry.next_fire)))
            return "rescheduled"

        if verdict != FIRE:
            return "waiting"

        snoozes_left = max(0, self.options.max_snoozes - entry.snoozes_used)
        outcome = ringer.ring(
            alarm=entry.alarm,
            scheduled_at=entry.next_fire,
            ring_seconds=self.options.ring_seconds,
            snoozes_left=snoozes_left,
            snooze_minutes=self.options.snooze_minutes,
            take_interrupts=self.interrupts.take,
        )

        if outcome == ringer.EXIT:
            return "exit"
        if outcome == ringer.DISMISSED:
            self._finish(entry)
            return "finished"

        return self._snooze_or_give_up(entry)

    def _snooze_or_give_up(self, entry: ScheduleEntry) -> str:
        entry.snoozes_used += 1
        if entry.snoozes_used > self.options.max_snoozes:
            print(
                "  no snoozes left for {} - giving up".format(entry.alarm.describe())
            )
            self._finish(entry)
            return "finished"

        entry.next_fire = snooze_until(datetime.now(), self.options.snooze_minutes)
        print(
            "  snoozed {} until {} ({} of {})".format(
                entry.alarm.describe(),
                entry.next_fire.strftime("%H:%M:%S"),
                entry.snoozes_used,
                self.options.max_snoozes,
            )
        )
        return "snoozed"

    def _finish(self, entry: ScheduleEntry) -> None:
        """A one-off alarm has done its job: record it, disable it, keep it (FR-10)."""
        self.schedule.pop(entry.alarm.id, None)
        try:
            alarms = storage.load(self.options.path)
        except storage.StoreError as exc:
            print("  ! could not record the alarm as fired: {}".format(exc), file=sys.stderr)
            return

        for alarm in alarms:
            if alarm.id == entry.alarm.id:
                alarm.enabled = False
                alarm.last_fired_at = datetime.now().astimezone().isoformat(timespec="seconds")
                break
        else:
            return  # removed from another terminal mid-ring; nothing to record

        try:
            storage.save(alarms, self.options.path)
        except storage.StoreError as exc:
            print("  ! could not record the alarm as fired: {}".format(exc), file=sys.stderr)
        # Our own write must not look like an external change on the next tick.
        self._fingerprint = storage.fingerprint(self.options.path)
        print("  {} is done and now disabled - re-arm with: alarm enable {}".format(
            entry.alarm.id, entry.alarm.id
        ))

    # -- output --------------------------------------------------------------

    def _print_startup(self) -> None:
        if not self.schedule:
            print("No enabled alarms. Add one with: alarm add 07:30")
            print("Watching for changes. Keep this terminal open; Ctrl-C to stop.")
            return

        count = len(self.schedule)
        print("Watching {} alarm{}. Keep this terminal open; Ctrl-C to stop.".format(
            count, "" if count == 1 else "s"
        ))
        for entry in sorted(self.schedule.values(), key=lambda item: item.next_fire):
            print(
                "  {:<8}{:<7}{:<22}{}".format(
                    entry.alarm.id,
                    entry.alarm.time,
                    (entry.alarm.label or "")[:20],
                    format_when(entry.next_fire),
                )
            )

    # -- timing --------------------------------------------------------------

    def _sleep(self, seconds: float) -> bool:
        """Sleep in slices. Returns False if the user asked to stop."""
        deadline = time_module.monotonic() + seconds
        while time_module.monotonic() < deadline:
            if self.interrupts.take():
                return False
            time_module.sleep(config.POLL_SECONDS)
        return True


def run(options: RunOptions) -> int:
    return Runner(options=options).run()
