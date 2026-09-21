"""Defaults and path resolution.

Every tunable number in the program is named here rather than being written
inline at its use site, so the behaviour of the run loop can be understood from
one screen.
"""

import os
from pathlib import Path

# --- store -----------------------------------------------------------------

STORE_VERSION = 1
STORE_FILENAME = "alarms.json"

# --- ringing ---------------------------------------------------------------

RING_SECONDS = 60
"""How long an alarm rings before it auto-snoozes (requirements FR-6)."""

SNOOZE_MINUTES = 9
"""Traditional clock-radio interval (requirements Q1)."""

MAX_SNOOZES = 3
"""Consecutive snoozes before an alarm gives up and disables itself (FR-7)."""

BELL_INTERVAL_SECONDS = 2.0
"""Gap between BEL characters: insistent without making the terminal unusable."""

# --- run loop --------------------------------------------------------------

TICK_SECONDS = 1.0
"""Loop period. NFR-3 requires firing within one second of the scheduled time."""

POLL_SECONDS = 0.1
"""Sleep granularity, so Ctrl-C is acted on promptly rather than at tick edges."""

CATCHUP_SECONDS = 120
"""An alarm later than this is reported as missed, not rung late (FR-9, Q3)."""


def store_path() -> Path:
    """Resolve the alarm store location (design section 4.2).

    First match wins:
      1. $ALARM_CLOCK_HOME/alarms.json
      2. $XDG_DATA_HOME/alarm-clock/alarms.json
      3. ~/.local/share/alarm-clock/alarms.json
    """
    override = os.environ.get("ALARM_CLOCK_HOME")
    if override:
        return Path(override).expanduser() / STORE_FILENAME

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / "alarm-clock" / STORE_FILENAME

    return Path.home() / ".local" / "share" / "alarm-clock" / STORE_FILENAME
