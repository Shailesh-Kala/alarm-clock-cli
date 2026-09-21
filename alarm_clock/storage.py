"""Reading and writing the alarm store.

The file on disk is the truth; anything held in memory is a cache of it. Writes
are atomic so that an interrupted write can never cost the user their alarms
(requirements FR-10, NFR-5).
"""

import json
import os
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from alarm_clock import config
from alarm_clock.models import Alarm

Fingerprint = Tuple[int, int]


class StoreError(Exception):
    """A problem with the store file itself. Printed as one sentence, never a traceback."""


def load(path: Optional[Path] = None) -> List[Alarm]:
    """Read the alarms. A missing file is an empty store, not an error."""
    target = path or config.store_path()

    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise StoreError("cannot read {}: {}".format(target, exc.strerror or exc))

    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StoreError(
            "{} is not valid JSON (line {}, column {}). "
            "Inspect or move the file, then try again.".format(target, exc.lineno, exc.colno)
        )

    if not isinstance(payload, dict):
        raise StoreError("{} should contain a JSON object at the top level".format(target))

    version = payload.get("version")
    if version != config.STORE_VERSION:
        raise StoreError(
            "{} has store version {!r}, but this build understands version {}".format(
                target, version, config.STORE_VERSION
            )
        )

    entries = payload.get("alarms")
    if not isinstance(entries, list):
        raise StoreError("{} should contain an 'alarms' list".format(target))

    alarms: List[Alarm] = []
    for index, entry in enumerate(entries):
        try:
            alarms.append(Alarm.from_dict(entry))
        except ValueError as exc:
            raise StoreError("{}: alarm #{} is invalid - {}".format(target, index + 1, exc))

    seen = set()
    for alarm in alarms:
        if alarm.id in seen:
            raise StoreError("{}: duplicate alarm id {!r}".format(target, alarm.id))
        seen.add(alarm.id)

    return alarms


def save(alarms: Sequence[Alarm], path: Optional[Path] = None) -> None:
    """Write the alarms atomically.

    Serialise to a temporary file beside the real one, fsync it, then rename over
    the top. A same-directory rename is atomic, so a crash mid-write leaves the
    previous good file untouched.
    """
    target = path or config.store_path()
    payload = {
        "version": config.STORE_VERSION,
        "alarms": [alarm.to_dict() for alarm in alarms],
    }
    body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    temporary = target.with_name(target.name + ".tmp")

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        raise StoreError("cannot write {}: {}".format(target, exc.strerror or exc))
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass  # already renamed into place, which is the normal path


def fingerprint(path: Optional[Path] = None) -> Optional[Fingerprint]:
    """Cheap change detection for the run loop: (mtime_ns, size), or None if absent.

    Polled once per tick so that an `alarm add` from another terminal is noticed
    without re-parsing the file every second (requirements FR-5).
    """
    target = path or config.store_path()
    try:
        stat = target.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)
