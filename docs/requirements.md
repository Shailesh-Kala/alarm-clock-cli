# Requirements — `alarm-clock-cli`

**Status:** Implemented in v0.1.0 · **Date:** 2026-09-21 · **Owner:** Shailesh Kala

---

## 1. Purpose

A single-user alarm clock that lives entirely in the terminal. The user schedules
wall-clock alarms (`07:30`), keeps a long-running process open in a terminal, and
gets a loud, visible alert when an alarm comes due.

The product goal is **a small tool that does one thing completely**, not a broad
clock suite. Every decision below favours a finished, predictable behaviour over
an extra feature.

---

## 2. Locked scope decisions

These were decided before design and are treated as fixed. Changing any of them
is a scope change, not a detail.

| # | Decision | Chosen | Rejected alternatives |
|---|---|---|---|
| D1 | Runtime model | **Foreground process.** `alarm run` occupies a terminal and rings alarms. Closing the terminal stops it. | Background daemon w/ PID file; launchd/cron registration |
| D2 | Alert method | **Terminal banner + ASCII BEL only.** No audio files, no desktop notifications, no user-supplied shell commands. | `afplay` sound; `osascript` notification; custom command hook |
| D3 | Feature depth | **Core only.** One-off alarms: add / list / remove / enable / disable, plus snooze and dismiss while ringing. | Recurring alarms; countdown timers; stopwatch; world clock; TUI |
| D4 | Dependencies | **Python standard library only at runtime.** No third-party packages. | Click/Typer + Rich |
| D5 | Ring behaviour | **Ring for N seconds, then auto-snooze.** No raw-terminal keyboard capture. | Raw `termios` key handling; blocking `input()` prompt |
| D6 | Time input | **24-hour `HH:MM` only.** | 12-hour am/pm; relative offsets (`+45m`); full date-times |
| D7 | Tests | **No formal automated test suite.** Verification is a documented manual checklist. | `unittest` + CI; `pytest` + CI |

> **Flag on D7.** A repo meant to be shared and reviewed is weaker without tests,
> and the scheduling logic (§4, FR-5/FR-9) is exactly the kind of date arithmetic
> that silently breaks. The plan therefore keeps all such logic in pure,
> side-effect-free functions so a test suite can be added later without
> restructuring, and ships a manual verification checklist in its place. Noted,
> and proceeding as decided.

---

## 3. Users and usage context

**Primary user:** a developer who already has a terminal open all day and wants a
reminder that does not involve reaching for a phone.

**Expected session:**
1. `alarm add 07:30 --label "Standup"` — schedule it.
2. `alarm run` — leave it running in a spare terminal tab or `tmux` pane.
3. At 07:30 the terminal fills with a banner and beeps.
4. The user either ignores it (it auto-snoozes) or presses `Ctrl-C` to dismiss.

**Assumed environment:** macOS or Linux, Python 3.9+, a terminal emulator where
the bell character is either audible or produces a visual flash.

---

## 4. Functional requirements

### FR-1 — Add an alarm
`alarm add <HH:MM> [--label TEXT]`

- Accepts a 24-hour time, zero-padded or not (`7:30` and `07:30` both valid).
- Rejects anything else with a clear message and a non-zero exit code.
- Assigns a short, unique, human-typable ID.
- Alarm is created **enabled**.
- On success, prints the ID **and the resolved next fire time as an absolute
  date-time**, so "I added 07:30 at 07:31 and it went to tomorrow" is never a
  surprise.
- `--label` is optional free text used only for display.

### FR-2 — List alarms
`alarm list [--all]`

- Default: a table of enabled alarms — ID, time, label, next fire time.
- `--all`: also shows disabled alarms, visibly marked as such.
- Sorted by next fire time; disabled alarms sort last.
- An empty list prints a friendly message, not an empty table, and exits 0.

### FR-3 — Remove alarms
`alarm remove <id> [<id> ...]`

- Deletes permanently. Accepts several IDs in one call.
- An unknown ID is an error naming the ID; other valid IDs in the same call are
  still removed, and the command exits non-zero.

### FR-4 — Enable / disable
`alarm enable <id>` · `alarm disable <id>`

- A disabled alarm is retained but never fires and is skipped by the run loop.
- Enabling or disabling an already-enabled/disabled alarm is a no-op that
  succeeds (idempotent).

### FR-5 — Run loop
`alarm run [--ring-seconds N] [--snooze-minutes N] [--max-snoozes N] [--once]`

- Runs in the foreground until interrupted.
- On start, prints every scheduled alarm and its next fire time, so the user can
  confirm at a glance that the thing they expect is actually armed.
- Wakes at least once per second; fires alarms whose time has arrived.
- **Picks up changes made from another terminal** while running: if `alarm add`
  or `alarm remove` is run elsewhere, the loop notices and re-reads the store
  without needing a restart.
- `--once` exits after the first alarm completes. This exists to make manual
  verification finite and is also useful for one-shot use.
- Idle output is quiet: no per-second spam.

### FR-6 — Ringing
When an alarm comes due:

- Print a large, unmistakable banner: the label, the scheduled time, the current
  time, and what the user can do about it.
- Emit the ASCII BEL character (`\a`) repeatedly at a fixed interval for the ring
  duration (default 60 s).
- Show the remaining ring time so the user can see it is still live.

### FR-7 — Snooze
- If the ring duration elapses with no dismissal, the alarm **auto-snoozes**:
  rescheduled for `snooze-minutes` later (default 9), and the snooze is printed
  with the exact time it will return.
- After `max-snoozes` (default 3) consecutive snoozes, the alarm stops nagging,
  is marked as fired, and is auto-disabled (see FR-10).

### FR-8 — Dismiss
- `Ctrl-C` **while an alarm is ringing** dismisses that alarm and returns the
  loop to waiting. It does not kill the process.
- `Ctrl-C` while idle (not ringing) exits the program cleanly.
- A second `Ctrl-C` within 2 seconds always exits, so the user is never trapped.

### FR-9 — Missed alarms
If the machine sleeps or the process is suspended across an alarm time:

- On resume, an alarm whose time passed **within a short catch-up window**
  (default 120 s) still rings.
- An alarm whose time passed longer ago is **not** rung hours late. It is
  reported as missed, with its scheduled time, and rescheduled normally.

### FR-10 — Persistence and lifecycle
- Alarms persist across runs in a single JSON file on disk.
- Writes are atomic: an interrupted write must never leave a truncated or
  unreadable store.
- The file is versioned so its format can change later without guessing.
- A one-off alarm that has completed (dismissed, or out of snoozes) is
  **auto-disabled and kept**, with its last-fired timestamp, rather than deleted.
  Re-arming it is `alarm enable <id>`.

### FR-11 — ID ergonomics
- Any command taking an ID also accepts an unambiguous **prefix** of it.
- An ambiguous prefix is an error that lists the candidates.

### FR-12 — Errors and exit codes
| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Runtime error (bad time, unknown ID, unreadable store) |
| `2` | Usage error (argparse default: unknown command or flag) |

Errors go to `stderr`, are a single plain sentence, and never show a traceback
for an expected condition.

---

## 5. Non-functional requirements

- **NFR-1 Zero install friction.** `python3 -m alarm_clock` works from a clone
  with no `pip install` and no virtualenv.
- **NFR-2 Portability.** Python 3.9+, macOS and Linux. No compiled extensions.
- **NFR-3 Accuracy.** An alarm fires within 1 second of its scheduled time on a
  machine that is awake.
- **NFR-4 Footprint.** The idle loop must be effectively free — sleep-driven, not
  a busy wait.
- **NFR-5 Data safety.** A corrupt or hand-edited store produces a clear error
  naming the file; it never crashes with a raw traceback and never silently
  discards the user's alarms.
- **NFR-6 Readability.** Scheduling and parsing logic stays in pure functions
  with no I/O, so it can be reasoned about — and later tested — in isolation.

---

## 6. Out of scope

Explicit non-goals, listed so review can challenge the boundary rather than
discover it later:

- Recurring or repeating alarms (daily, weekdays, days-of-week)
- Countdown timers, stopwatch, world clock, live clock display
- Audio playback, desktop notifications, custom on-fire commands
- Surviving reboot, logout, or terminal close
- Multi-user, networked, or synced alarms
- Time zones other than the machine's local time
- A web or graphical interface of any kind
- A database of any kind

---

## 7. Acceptance criteria

The implementation is accepted when all of the following are demonstrated by
hand (see the checklist in the implementation plan):

1. `alarm add 07:30 --label "Standup"` prints an ID and an absolute next-fire
   date-time.
2. Adding a time that has already passed today resolves to tomorrow, and says so.
3. `alarm list` shows the alarm; `--all` additionally shows disabled ones.
4. Invalid times (`25:00`, `7:70`, `abc`, `7.30`) are each rejected with a clear
   message and exit code 1.
5. An alarm added a minute ahead actually rings at the right minute, with a
   visible banner and an audible or visual bell.
6. Leaving the ring alone auto-snoozes it, and the printed return time is
   correct.
7. `Ctrl-C` during a ring dismisses that alarm and leaves the loop running;
   `Ctrl-C` while idle exits.
8. Exhausting the snooze limit stops the alarm and leaves it disabled with a
   last-fired timestamp.
9. `alarm add` in a second terminal is picked up by the running loop without a
   restart.
10. Alarms survive stopping and restarting the process.
11. A deliberately corrupted JSON store produces a clear error, not a traceback.
12. `alarm remove` on an unknown ID reports it, still removes the valid ones, and
    exits non-zero.

---

## 8. Open questions for review

None of these blocked implementation. **v0.1.0 was built with the stated
defaults**, and each remains open - changing any of them is a small change to
`config.py`, not a redesign.

- **Q1.** Default snooze of 9 minutes is the traditional clock-radio interval.
  Is a rounder default (5 or 10) preferred?
- **Q2.** Completed alarms are kept-and-disabled (FR-10). Should they instead be
  deleted automatically after firing? Keeping them means `list --all` grows over
  time with no prune command in scope.
- **Q3.** The catch-up window for missed alarms is 120 s. Too short for a laptop
  that sleeps briefly mid-ring?
- **Q4.** Should `alarm run` refuse to start if another instance is already
  running? Two loops would ring the same alarm twice. As built: documented
  limitation, no lock file (D1 keeps the runtime model minimal).
