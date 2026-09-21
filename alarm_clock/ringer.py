"""Making the alarm impossible to ignore: the banner and the bell.

The banner is the primary alert and the bell is secondary, because plenty of
terminals ship with the bell muted (design section 11).
"""

import sys
import time as time_module
from datetime import datetime
from typing import Callable, Optional

from alarm_clock import config
from alarm_clock.models import Alarm

DISMISSED = "dismissed"
ELAPSED = "elapsed"
EXIT = "exit"

_WIDTH = 60
_BELL = "\a"
_NON_TTY_UPDATE_SECONDS = 15.0


def _rule(left: str, right: str) -> str:
    return left + "=" * _WIDTH + right


def _row(text: str = "") -> str:
    return "|" + text.ljust(_WIDTH)[:_WIDTH] + "|"


def _centred(text: str) -> str:
    return _row(text.center(_WIDTH))


def _fit(text: str, room: int) -> str:
    return text if len(text) <= room else text[: room - 1] + "…"


def render_banner(
    alarm: Alarm,
    scheduled_at: datetime,
    now: datetime,
    snoozes_left: int,
    snooze_minutes: int = config.SNOOZE_MINUTES,
) -> str:
    """Build the alert block. Pure, so it can be eyeballed without waiting for 7am."""
    label = _fit(alarm.label or "(no label)", _WIDTH - 4)
    timing = "Scheduled {}   .   Now {}".format(
        scheduled_at.strftime("%H:%M"), now.strftime("%H:%M:%S")
    )

    if snoozes_left > 0:
        action = "Ctrl-C to dismiss  .  ignore to snooze {}m ({} left)".format(
            snooze_minutes, snoozes_left
        )
    else:
        action = "Ctrl-C to dismiss  .  last ring, no snoozes left"

    return "\n".join(
        [
            _rule("+", "+"),
            _centred("A L A R M"),
            _rule("+", "+"),
            _row("  " + label),
            _row("  " + _fit(timing, _WIDTH - 4)),
            _rule("+", "+"),
            _row("  " + _fit(action, _WIDTH - 4)),
            _rule("+", "+"),
        ]
    )


def ring(
    alarm: Alarm,
    scheduled_at: datetime,
    ring_seconds: int,
    snoozes_left: int,
    snooze_minutes: int,
    take_interrupts: Callable[[], int],
    clock: Optional[Callable[[], datetime]] = None,
) -> str:
    """Ring until dismissed or until the ring duration runs out.

    `take_interrupts` returns the number of Ctrl-C presses since it was last
    called, and clears them. One dismisses this alarm; two at once means the user
    wants out of the program entirely (requirements FR-8).

    Returns DISMISSED, ELAPSED or EXIT.
    """
    now = clock() if clock else datetime.now()
    interactive = sys.stdout.isatty()

    take_interrupts()  # discard anything queued before the ring started
    print()
    print(render_banner(alarm, scheduled_at, now, snoozes_left, snooze_minutes))

    started = time_module.monotonic()
    next_bell = started
    next_non_tty_update = started + _NON_TTY_UPDATE_SECONDS

    while True:
        elapsed = time_module.monotonic() - started
        remaining = ring_seconds - elapsed

        interrupts = take_interrupts()
        if interrupts >= 2:
            _clear_status(interactive)
            return EXIT
        if interrupts == 1:
            _clear_status(interactive)
            print("  dismissed {}".format(alarm.describe()))
            return DISMISSED

        if remaining <= 0:
            _clear_status(interactive)
            return ELAPSED

        moment = time_module.monotonic()
        if moment >= next_bell:
            sys.stdout.write(_BELL)
            next_bell = moment + config.BELL_INTERVAL_SECONDS

        if interactive:
            sys.stdout.write("\r  ringing - {:>3.0f}s left ".format(remaining))
            sys.stdout.flush()
        elif moment >= next_non_tty_update:
            print("  ringing - {:.0f}s left".format(remaining))
            next_non_tty_update = moment + _NON_TTY_UPDATE_SECONDS

        time_module.sleep(config.POLL_SECONDS)


def _clear_status(interactive: bool) -> None:
    """Wipe the in-place countdown so the next line starts clean."""
    if interactive:
        sys.stdout.write("\r" + " " * (_WIDTH + 2) + "\r")
        sys.stdout.flush()
