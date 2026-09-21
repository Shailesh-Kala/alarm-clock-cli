# Implementation Plan — `alarm-clock-cli`

**Status:** Draft for review · **Date:** 2026-09-21
**Companions:** [requirements.md](requirements.md) · [design.md](design.md)

Nothing in this plan is built until the two documents above are approved.

---

## 1. Shape of the work

Six phases, built bottom-up: pure logic first, then storage, then the CLI, then
the loop. Each phase ends at a point where the repo is coherent and something is
demonstrable by hand — so review can happen at any phase boundary, not only at
the end.

| Phase | Deliverable | Demonstrable at the end |
|---|---|---|
| 0 | Repo scaffolding | `python3 -m alarm_clock --version` |
| 1 | Pure core: models + scheduler | Next-fire math verified in a REPL |
| 2 | Storage layer | Alarms survive a process restart |
| 3 | CRUD commands | Full add/list/remove/enable/disable |
| 4 | Ringer | A banner + bell on demand |
| 5 | Run loop, snooze, signals | The actual alarm clock |
| 6 | Docs, polish, release | A repo someone else can use |

---

## 2. Phase detail

### Phase 0 — Scaffolding

**Files:** `pyproject.toml`, `.gitignore`, `LICENSE`, `alarm_clock/__init__.py`,
`alarm_clock/__main__.py`, `alarm_clock/cli.py` (skeleton),
`alarm_clock/config.py`

- `pyproject.toml`: setuptools backend, `requires-python = ">=3.9"`,
  **`dependencies = []`**, console script `alarm = alarm_clock.cli:main`.
- `config.py`: defaults in one place — `RING_SECONDS = 60`,
  `SNOOZE_MINUTES = 9`, `MAX_SNOOZES = 3`, `CATCHUP_SECONDS = 120`,
  `TICK_SECONDS = 1`, `BELL_INTERVAL_SECONDS = 2` — plus `store_path()`
  implementing the three-step resolution in design §4.2.
- `cli.py`: argparse tree with every subcommand registered, handlers raising
  `NotImplementedError`. Getting the full surface visible early means the
  interface is reviewable before any behaviour is written.

**Done when:** `python3 -m alarm_clock --help` lists all seven commands.

---

### Phase 1 — Pure core

**Files:** `alarm_clock/models.py`, `alarm_clock/scheduler.py`

`models.py`
- `Alarm` dataclass exactly as design §4.1.
- `parse_hhmm(text) -> datetime.time` — accepts `H:MM` and `HH:MM`, rejects
  everything else with `ValueError` carrying a user-facing message. Explicitly
  rejects `7.30`, `0730`, `7:60`, `24:00`, negative values, whitespace-only.
- `format_hhmm(time) -> str` — canonical zero-padded output.
- `new_id(existing: set[str]) -> str` — 6 hex chars from `uuid4`, retried on
  collision.
- `Alarm.to_dict` / `Alarm.from_dict` — the only place field names are spelled.

`scheduler.py`
- `next_occurrence(hhmm, now) -> datetime` (design §5.1).
- `classify(entry, now, catchup) -> "wait" | "fire" | "missed"`.
- `snooze_until(now, minutes) -> datetime`.
- `resolve_id(token, alarms) -> Alarm` — exact, then unique prefix, then the two
  error cases (design §9.1).

**Constraint:** neither file imports anything from the project beyond the other,
and neither calls `datetime.now()` — `now` is always a parameter. This is what
makes the logic verifiable by inspection and testable later.

**Done when:** each function is exercised in a REPL against the edge-case table
in design §10, and the boundary cases (23:59→00:00 rollover, alarm exactly at
`now`, alarm one second past) behave as specified.

---

### Phase 2 — Storage

**File:** `alarm_clock/storage.py`

- `StoreError(Exception)` — the single error type the CLI catches and prints.
- `load() -> list[Alarm]` — missing file → `[]`; bad JSON, wrong `version`, or a
  malformed alarm entry → `StoreError` naming the path.
- `save(alarms)` — `mkdir` parents, write `.tmp` in the same directory,
  `flush` + `fsync`, `os.replace`.
- `fingerprint() -> tuple | None` — `(mtime_ns, size)` from `os.stat`, or `None`
  if absent. This is the cheap change-detection the run loop polls (design §6.2).

**Done when:** a store written by hand loads; a truncated store raises a clean
`StoreError`; killing the process during a write never corrupts the file.

---

### Phase 3 — CRUD commands

**File:** `alarm_clock/commands.py`, plus wiring in `cli.py`

One function per subcommand, each taking parsed args and returning an exit code.

- `cmd_add` — parse, generate ID, save, print resolved absolute next fire
  (FR-1).
- `cmd_list` — sort by next fire with disabled last, render a fixed-width table,
  friendly empty-state message.
- `cmd_remove` — resolve each ID, remove the resolvable ones, report the rest,
  return 1 if any failed (FR-3).
- `cmd_enable` / `cmd_disable` — idempotent; `enable` prints the new next fire.
- Central error handling in `cli.main`: catch `StoreError` and `ValueError`,
  print one sentence to stderr, return 1. Tracebacks only for genuine bugs.

**Done when:** acceptance criteria 1–4, 10 and 12 pass by hand.

---

### Phase 4 — Ringer

**File:** `alarm_clock/ringer.py`

- `render_banner(alarm, scheduled_at, now, snoozes_left) -> str` — pure, returns
  a string, so the banner can be eyeballed without waiting for an alarm.
- `ring(alarm, scheduled_at, ring_seconds, interrupt) -> RingOutcome` — prints
  the banner, then loops: emit `\a` every `BELL_INTERVAL_SECONDS`, redraw the
  countdown line, poll the interrupt flag. Returns `DISMISSED` or `ELAPSED`.
- Non-TTY detection via `sys.stdout.isatty()`; falls back to line-per-update
  output when redirected (design §10).

**Done when:** a hidden `--demo-banner` flag (or a REPL call) shows the banner
and audibly beeps, and `Ctrl-C` during the demo returns `DISMISSED` rather than
killing the process.

---

### Phase 5 — Run loop

**File:** `alarm_clock/runner.py`

Built in four passes, each independently checkable:

1. **Skeleton** — load, build `schedule`, print the startup summary, tick at 1 Hz
   with a quiet idle.
2. **Reload** — poll `fingerprint()`, diff against the in-memory schedule,
   add/drop entries, print one line per change (FR-5).
3. **Firing** — `classify` each entry; wire `fire` to the ringer and `missed` to
   a report line (FR-9).
4. **Outcomes** — the state machine of design §7: dismiss and exhaustion persist
   `last_fired_at` and `enabled = False`; snooze updates memory only; `--once`
   exits after the first terminal outcome.

Signal handling (design §8) is installed here: a handler recording a flag and a
timestamp, polled by both the ring loop and the idle sleep, with the
double-`Ctrl-C` escape.

**Done when:** acceptance criteria 5–9 and 11 pass by hand.

---

### Phase 6 — Docs and release

- `README.md`: what it is, the foreground-only caveat stated up front, install
  (clone-and-run, and the optional `pip install -e .`), a worked example, a
  command reference, where the store lives, and how to get the terminal bell to
  actually make noise on macOS Terminal and iTerm2.
- Re-read `requirements.md` and `design.md` against what was actually built, and
  correct the documents where the implementation deviated — a design doc that
  disagrees with the code is worse than none.
- A short "Limitations" section in the README carrying design §11 forward, so a
  reader learns the constraints without opening `docs/`.
- Tag `v0.1.0`.

---

## 3. Manual verification checklist

Standing in for an automated suite (decision D7). Run top to bottom on a clean
store; every line is a pass/fail.

**Setup**
```bash
export ALARM_CLOCK_HOME=/tmp/alarm-verify && rm -rf "$ALARM_CLOCK_HOME"
```

**A. Input validation**
- [ ] `alarm add 07:30 --label "Standup"` → prints ID + absolute next fire
- [ ] `alarm add 7:30` → accepted, stored as `07:30`
- [ ] `alarm add 25:00` → error, exit 1
- [ ] `alarm add 7:70` → error, exit 1
- [ ] `alarm add abc` → error, exit 1
- [ ] `alarm add 7.30` → error, exit 1
- [ ] `alarm add` with no argument → usage error, exit 2

**B. Time resolution**
- [ ] An alarm for two minutes from now resolves to **today**
- [ ] An alarm for one minute ago resolves to **tomorrow**, and says so
- [ ] An alarm added at `23:59` for `00:05` resolves to tomorrow's date

**C. CRUD**
- [ ] `alarm list` shows enabled alarms sorted by next fire
- [ ] `alarm list` on an empty store prints a friendly message, exit 0
- [ ] `alarm disable <id>` → hidden from `list`, visible in `list --all`
- [ ] `alarm enable <id>` → returns, prints the next fire
- [ ] Enabling an already-enabled alarm succeeds (idempotent)
- [ ] A unique ID prefix works everywhere a full ID does
- [ ] An ambiguous prefix errors and lists the candidates
- [ ] `alarm remove <good> <bogus>` removes the good one, reports the bogus one, exits 1

**D. Ringing**
- [ ] An alarm one minute out fires within one second of the minute
- [ ] The banner shows label, scheduled time, current time, snoozes left
- [ ] The bell is audible (or flashes) in the test terminal
- [ ] The countdown redraws in place on a TTY
- [ ] `alarm run > out.txt` produces readable non-TTY output

**E. Snooze and dismiss**
- [ ] Ignoring the ring auto-snoozes; the printed return time is correct
- [ ] With `--ring-seconds 5 --snooze-minutes 1 --max-snoozes 2`, it rings 3 times total, then stops
- [ ] After exhaustion the alarm is disabled with `last_fired_at` set
- [ ] `Ctrl-C` during a ring dismisses and the loop keeps running
- [ ] `Ctrl-C` while idle exits cleanly, exit 0
- [ ] Two `Ctrl-C` within 2 s during a ring exits

**F. Persistence and reload**
- [ ] Alarms survive stop and restart
- [ ] `alarm add` in a second terminal is picked up by the running loop
- [ ] `alarm remove` in a second terminal drops it from the running loop
- [ ] `echo 'not json' > $ALARM_CLOCK_HOME/alarms.json` → clear error, no traceback
- [ ] A store with `"version": 99` → clear error naming the version

**G. Resilience**
- [ ] Sleep the machine across an alarm by ~10 minutes → reported as missed, not rung late
- [ ] Sleep across an alarm by ~30 seconds → rings on wake
- [ ] `--once` exits after the first completed alarm

---

## 4. Effort estimate

| Phase | Estimate |
|---|---|
| 0 Scaffolding | 0.5 h |
| 1 Pure core | 1.5 h |
| 2 Storage | 1.0 h |
| 3 CRUD commands | 2.0 h |
| 4 Ringer | 1.5 h |
| 5 Run loop | 2.5 h |
| 6 Docs and release | 1.5 h |
| Manual verification pass | 1.5 h |
| **Total** | **≈ 12 h** |

Phases 3–5 are the load-bearing ones. The estimate assumes the locked decisions
in requirements §2 hold; reopening D1, D3 or D5 changes the shape of phase 5
materially.

---

## 5. Risks to the plan

| Risk | Likelihood | Handling |
|---|---|---|
| Time-of-day bugs found only at the boundary (midnight, DST) | Medium | All such logic is pure and parameterised on `now`, so boundaries can be checked at any hour by passing a fabricated `now` |
| Verification of snooze behaviour is slow in real time | High | `--ring-seconds` / `--snooze-minutes` flags exist partly to make the checklist runnable in seconds instead of half an hour |
| Sleep/resume behaviour differs across machines | Medium | Catch-up window is a named constant, easy to tune after real use |
| No test suite (D7) lets a regression through | Medium | Accepted by decision; structure keeps the door open, checklist is the stopgap |
| Scope creep toward recurring alarms | Medium | Requirements §6 names it as out of scope; it becomes v0.2 work, not v0.1 |

---

## 6. Definition of done for v0.1.0

- Every acceptance criterion in requirements §7 passes by hand.
- The full checklist in §3 above has been run and the result recorded.
- `README.md` lets a stranger install and use the tool without reading `docs/`.
- `requirements.md` and `design.md` describe what was actually built.
- Runtime imports are standard library only — verifiable by inspection.
- Tagged `v0.1.0` on `main`.
