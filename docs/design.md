# Design — `alarm-clock-cli`

**Status:** Implemented in v0.1.0 · **Date:** 2026-09-21 · **Companion to:** [requirements.md](requirements.md)

This document has been reconciled with the shipped code; where the build
diverged from the original design, the deviation and its reason are recorded in
place rather than quietly edited away.

---

## 1. Design principles

1. **Pure core, thin shell.** Time arithmetic and state transitions are pure
   functions over values. Everything that touches the clock, the disk, the
   terminal, or signals lives at the edges. This is what makes the code
   reviewable — and testable later — despite D7 (no test suite).
2. **The store is the truth; memory is a cache.** The JSON file is authoritative.
   The run loop holds a derived schedule and rebuilds it when the file changes.
3. **Never surprise the user about time.** Any command that schedules something
   prints the resolved absolute date-time it resolved to.
4. **Fail loudly at the edge, never in the middle.** Validate on input, so the
   loop never has to defend against a malformed alarm.

---

## 2. Architecture

```
                    ┌──────────────────────────────────────┐
   user terminal ──►│  cli.py        argparse dispatch      │
                    │                (add/list/remove/...)  │
                    └───────┬──────────────────────┬────────┘
                            │                      │
                  ┌─────────▼────────┐   ┌─────────▼──────────┐
                  │ commands.py      │   │ runner.py          │
                  │ CRUD handlers    │   │ foreground loop    │
                  └─────────┬────────┘   └───┬────────────┬───┘
                            │                │            │
        ┌───────────────────▼────────────────▼──┐  ┌──────▼───────┐
        │ storage.py   load / atomic save       │  │ ringer.py    │
        │              mtime change detection   │  │ banner + BEL │
        └───────────────────┬───────────────────┘  └──────────────┘
                            │
                  ┌─────────▼──────────┐      ┌──────────────────────┐
                  │ models.py          │◄─────┤ scheduler.py         │
                  │ Alarm dataclass    │      │ PURE next-fire math  │
                  │ parse/format HH:MM │      │ due? / missed? logic │
                  └────────────────────┘      └──────────────────────┘
                     no I/O below this line — pure values only
```

**Dependency rule:** arrows point downward only. `models.py` and `scheduler.py`
import nothing from the project except each other and the standard library.

---

## 3. Module map

| Module | Responsibility | Touches I/O? |
|---|---|---|
| `alarm_clock/__main__.py` | `python -m alarm_clock` entry point | no |
| `alarm_clock/cli.py` | argparse definition, subcommand dispatch, exit codes | stdout/stderr |
| `alarm_clock/commands.py` | One function per CRUD subcommand; formats output | via storage |
| `alarm_clock/runner.py` | The `run` loop: tick, reload, fire, snooze, signals | clock, signals |
| `alarm_clock/ringer.py` | Renders the banner, emits BEL, counts down the ring | stdout, clock |
| `alarm_clock/storage.py` | Read/write the JSON store atomically; detect changes | filesystem |
| `alarm_clock/models.py` | `Alarm` dataclass, `HH:MM` parse/format, ID generation | **no** |
| `alarm_clock/scheduler.py` | `next_occurrence`, due/missed classification, snooze math | **no** |
| `alarm_clock/config.py` | Defaults and resolved store path | env read only |

Nine small modules. The split exists so the two files carrying the real risk
(`models`, `scheduler`) are pure and readable on their own.

---

## 4. Data model

### 4.1 `Alarm`

```python
@dataclass
class Alarm:
    id: str            # 6 hex chars, unique within the store
    time: str          # canonical "HH:MM", zero-padded, 24-hour
    label: str         # free text, may be ""
    enabled: bool
    created_at: str    # ISO-8601 local, with offset
    last_fired_at: str | None
```

Deliberately flat and string-typed on disk: the file stays human-readable and
hand-editable, which matters for a tool with no admin UI.

### 4.2 On-disk format

Path resolution, first match wins:
1. `$ALARM_CLOCK_HOME/alarms.json`
2. `$XDG_DATA_HOME/alarm-clock/alarms.json`
3. `~/.local/share/alarm-clock/alarms.json`

```json
{
  "version": 1,
  "alarms": [
    {
      "id": "a3f91c",
      "time": "07:30",
      "label": "Standup",
      "enabled": true,
      "created_at": "2026-09-21T17:42:10+05:30",
      "last_fired_at": null
    }
  ]
}
```

- `version` is checked on load. An unknown version is a clear error, not a guess.
- A missing file is not an error: it is an empty store.
- **Atomic write:** serialize to `alarms.json.tmp` in the same directory,
  `flush()` + `os.fsync()`, then `os.replace()`. Same-filesystem rename is atomic,
  so a crash mid-write leaves the previous good file intact.
- **Corrupt file:** `json.JSONDecodeError` or a schema mismatch raises a
  `StoreError` naming the path and suggesting the user inspect or move it. The
  file is never auto-deleted or auto-repaired.

### 4.3 Concurrency

No file locking. Two CLI processes writing simultaneously is last-writer-wins.
This is accepted: it is a single-user local tool and the write window is
sub-millisecond. It is recorded as a limitation in §10, not hidden.

---

## 5. Time semantics

All times are **naive local time** from `datetime.now()`. No UTC conversion, no
`zoneinfo` — the user means "07:30 on this machine's clock".

### 5.1 Next occurrence

```python
def next_occurrence(hhmm: time, now: datetime) -> datetime:
    """Smallest datetime d with d.time() == hhmm and d > now."""
    today = datetime.combine(now.date(), hhmm)
    return today if today > now else today + timedelta(days=1)
```

Strictly greater than `now`. An alarm added at exactly its own minute goes to
tomorrow — predictable, and FR-1 makes it visible by printing the resolved time.

### 5.2 DST and clock changes

The loop **never caches a next-fire time across a reload boundary without
re-deriving it from the wall clock**. Because `next_occurrence` is recomputed
from `datetime.now()` rather than by adding fixed deltas, a DST shift moves the
alarm with the wall clock, which is the behaviour a user expects from a clock.

Known consequence, documented rather than engineered around: on the autumn
"fall back" night a 01:30 alarm can be reached once; on the spring "spring
forward" night a 02:30 alarm does not exist and is skipped to the next day.

---

## 6. The run loop

### 6.1 State held in memory

```python
schedule: dict[str, ScheduleEntry]     # alarm id -> entry

@dataclass
class ScheduleEntry:
    alarm: Alarm
    next_fire: datetime
    snoozes_used: int
```

### 6.2 Tick, once per second

```
loop forever:
    if store mtime changed since last read:
        reload alarms
        for each enabled alarm not already scheduled: add entry (snoozes_used = 0)
        drop entries whose alarm was removed or disabled
        report what changed, in one line

    now = datetime.now()
    due = [e for e in schedule.values() if now >= e.next_fire]

    for entry in due sorted by next_fire:
        lateness = now - entry.next_fire
        if lateness > CATCHUP_WINDOW (120s):
            report "missed" with the scheduled time
            entry.next_fire = next_occurrence(entry.alarm.time, now)
            entry.snoozes_used = 0
        else:
            outcome = ring(entry)         # blocks for up to ring_seconds
            apply outcome (§7)

    sleep until the next whole second
```

**Why poll at 1 Hz instead of sleeping until the next alarm:** a long sleep
cannot notice a store change from another terminal (FR-5) and behaves badly
across machine suspend. A 1-second sleep is free (NFR-4) and makes both cases
trivial. Change detection is an `os.stat` mtime+size comparison, not a re-parse.

### 6.3 Ordering

If two alarms come due in the same tick, they ring one after another, ordered by
scheduled time. Concurrent ringing is not attempted — one banner at a time is the
whole point of the banner.

---

## 7. Ring and snooze state machine

```
                  ┌─────────┐
                  │ WAITING │◄────────────────────────────┐
                  └────┬────┘                             │
                 now >= next_fire                         │
                       │                                  │
                  ┌────▼────┐   Ctrl-C (SIGINT)      ┌────┴──────┐
                  │ RINGING ├───────────────────────►│ DISMISSED │
                  └────┬────┘                        └────┬──────┘
          ring_seconds elapsed                            │
                       │                                  │
                  ┌────▼─────────────┐                    │
                  │ snoozes_used + 1 │                    │
                  └────┬─────────────┘                    │
            ┌──────────┴───────────┐                      │
   <= max_snoozes            > max_snoozes                │
            │                      │                      │
     ┌──────▼──────┐        ┌──────▼──────┐               │
     │  SNOOZED    │        │  EXHAUSTED  │               │
     │ next_fire = │        │ mark fired  │               │
     │ now + delta │        │ auto-disable│               │
     └──────┬──────┘        └──────┬──────┘               │
            │                      │                      │
            └──────────────────────┴──────────────────────┘
                                   │
                         persist + return to WAITING
```

**On DISMISSED and EXHAUSTED** (both are terminal for a one-off alarm):
`last_fired_at = now`, `enabled = False`, written back to the store, entry
removed from the schedule. Per FR-10 the alarm is kept, not deleted.

**On SNOOZED:** nothing is written to disk — snooze state is in-memory only and
belongs to this run. Restarting the loop re-arms the alarm at its wall-clock
time, which is the least surprising behaviour.

### 7.1 Ringing output

```
+============================================================+
|                         A L A R M                          |
+============================================================+
|  Standup                                                   |
|  Scheduled 07:30   .   Now 07:30:02                        |
+============================================================+
|  Ctrl-C to dismiss  .  ignore to snooze 9m (2 left)        |
+============================================================+
  ringing -  47s left
```

Two deviations from the original sketch, both decided while building:

- **Pure ASCII, no emoji.** Emoji are double-width and render at different
  widths across terminals, which breaks the alignment of every row in the box.
  A banner that arrives visibly broken is worse than a plainer one.
- **The countdown sits below the box, not inside it.** Redrawing a line inside
  the box would need cursor movement; below it, a plain `\r` suffices. The
  status line is wiped when the ring ends so the next output starts clean.

Long labels are truncated with an ellipsis to fit the box. The BEL is emitted
every 2 seconds rather than every tick - insistent without making the terminal
unusable. On a non-TTY stdout (redirected or piped) the in-place redraw is
replaced by one progress line every 15 seconds.

## 8. Signal handling

`SIGINT` is the only signal handled, and its meaning is contextual (FR-8):

| Context | Ctrl-C |
|---|---|
| Ringing | Dismiss this alarm, keep looping |
| Ringing, two presses before the next poll | Exit the program |
| Idle | Exit cleanly |

**Implementation:** the handler does nothing but increment a counter.
`InterruptFlag.take()` returns the presses since the last call and clears them;
the ring loop and the idle loop each decide what that means. No exception is
raised across the signal boundary, so the control flow stays visible on the page.

This is simpler than the two-second window originally planned, and gives the
same guarantee that the user is never trapped: one press dismisses and returns
to idle, where the *next* press exits. Two presses landing in the same 100 ms
poll are read as "get me out", not as two dismissals. The planned
`DOUBLE_INTERRUPT_SECONDS` constant turned out to be unnecessary and was removed
rather than left in place as a lie about how the program works.

A consequence of PEP 475: `time.sleep()` resumes after a handler returns, so
responsiveness comes from sleeping in 100 ms slices (`POLL_SECONDS`) rather than
one long sleep.

`SIGTERM` is left at its default - a `kill` should stop the process.

## 9. CLI surface

| Command | Arguments | Output on success | Exit |
|---|---|---|---|
| `add` | `HH:MM`, `--label TEXT` | `Added a3f91c — 07:30 "Standup", first ring Tue 22 Sep 2026 07:30` | 0 |
| `list` | `--all` | Table: ID, time, label, next fire, status | 0 |
| `remove` | `<id>...` | `Removed a3f91c (07:30 "Standup")` per ID | 0 / 1 |
| `enable` | `<id>` | `Enabled a3f91c — next ring ...` | 0 / 1 |
| `disable` | `<id>` | `Disabled a3f91c` | 0 / 1 |
| `run` | `--ring-seconds`, `--snooze-minutes`, `--max-snoozes`, `--once` | Startup summary, then event lines | 0 |
| `--version` | — | `alarm-clock-cli 0.1.0` | 0 |
| `demo` | `--ring-seconds` | Rings a throwaway alarm immediately. Undocumented in `--help`; exists so the banner and bell can be checked without scheduling anything | 0 |

Invocable as `python3 -m alarm_clock <cmd>` always, and as `alarm <cmd>` after an
optional `pip install -e .` (a `pyproject.toml` with **zero runtime
dependencies** — D4 is about what the program imports, and it imports only the
standard library).

### 9.1 ID resolution (FR-11)

```
exact match            -> that alarm
unique prefix match    -> that alarm
no match               -> error "no alarm with id 'xyz'"
several prefix matches -> error listing every candidate
```

---

## 10. Edge cases and decisions

| Case | Behaviour |
|---|---|
| `alarm add 7:30` (not zero-padded) | Accepted, canonicalised to `07:30` |
| `alarm add 25:00` / `7:70` / `abc` / `7.30` | Rejected, exit 1, message names the expected format |
| `alarm add` for a time 30 s away | Scheduled for today; printed absolute time makes it obvious |
| `alarm add` for a time that just passed | Scheduled for tomorrow; printed absolute time makes it obvious |
| Duplicate alarms at the same time | Allowed — distinct IDs, both ring |
| Store file missing | Treated as empty; created on first write |
| Store directory missing | Created with `mkdir -p` semantics on first write |
| Store file corrupt | Clear `StoreError` naming the path; nothing is auto-repaired |
| Store unwritable (permissions) | Clear error naming the path, exit 1 |
| Alarm removed elsewhere while ringing | Current ring finishes; the entry is dropped at the next reload |
| Alarm disabled elsewhere while snoozed | Entry dropped at the next reload; it does not return |
| Machine sleeps across an alarm | Rings if within 120 s, otherwise reported as missed (FR-9) |
| Machine sleeps mid-ring | Ring ends early on wake; treated as the ring having elapsed → snooze |
| Two `alarm run` instances | Both ring. Known limitation; no lock file (open question Q4) |
| Terminal does not support the bell | Banner still prints; it is the primary signal, the bell is secondary |
| Non-TTY stdout (piped/redirected) | Countdown redraw falls back to one line every 15 s, no `\r`. The run loop also forces line buffering, so `alarm run > file` shows events as they happen instead of when a block buffer fills |
| Clock changed manually while running | Next tick re-derives from the wall clock; alarm follows the new time |

---

## 11. Risks and limitations

| Risk | Impact | Mitigation |
|---|---|---|
| **No automated tests (D7)** | Scheduling regressions ship silently | Pure functions in `scheduler.py`/`models.py`; documented manual checklist; structure ready for a suite to be added without refactoring |
| Foreground-only (D1) | A closed terminal means no alarm | Stated plainly in the README; `alarm run` prints that it must stay open |
| Bell may be silent in some terminals | User misses the alarm | Banner is the primary alert; README notes enabling the audible or visual bell |
| Two loops double-ring | Confusing | Documented; Q4 open for review |
| No lock on the store | Simultaneous writes, last wins | Sub-millisecond atomic writes; single-user tool; documented |
| Rendering of box characters | Cosmetic breakage | Resolved: the banner is pure ASCII, so there is nothing left to break |

---

## 12. Repository layout

```
alarm-clock-cli/
├── README.md
├── LICENSE                      # MIT
├── pyproject.toml               # zero runtime deps; console_script "alarm"
├── .gitignore
├── docs/
│   ├── requirements.md
│   ├── design.md
│   └── implementation-plan.md
└── alarm_clock/
    ├── __init__.py              # __version__
    ├── __main__.py
    ├── cli.py
    ├── commands.py
    ├── config.py
    ├── models.py
    ├── scheduler.py
    ├── storage.py
    ├── ringer.py
    └── runner.py
```

**As built:** 1,090 lines of Python across nine modules. All but one are
under 140 lines; `runner.py` is 290, because splitting the loop from the
outcome handling would have separated things that are read together. The
estimate of 600–800 lines was low - the error paths and the reload logic were
each larger than expected.
