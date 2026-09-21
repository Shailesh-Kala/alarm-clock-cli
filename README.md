# alarm-clock-cli

A terminal alarm clock in Python. No web UI, no database, no third-party
packages — just the standard library and a process you leave running in a
terminal tab.

> ## 📋 Status: design under review — no code yet
>
> This repository currently contains **only the planning documents**. The
> implementation starts once they are approved.

---

## The documents

| Document | What it covers |
|---|---|
| **[Requirements](docs/requirements.md)** | What it does and deliberately doesn't do, the locked scope decisions, functional requirements FR-1…FR-12, and the acceptance criteria |
| **[Design](docs/design.md)** | Architecture, module map, data model, time semantics, the run loop, the ring/snooze state machine, and every edge case with its decided behaviour |
| **[Implementation plan](docs/implementation-plan.md)** | Six build phases, the manual verification checklist, effort estimate, and definition of done |

**Suggested reading order:** requirements → design → plan. Each builds on the one
before it.

---

## What is being built, in one screen

```bash
$ alarm add 07:30 --label "Standup"
Added a3f91c — 07:30 "Standup", first ring Tue 22 Sep 2026 07:30

$ alarm list
ID      TIME   LABEL     NEXT FIRE
a3f91c  07:30  Standup   Tue 22 Sep 2026 07:30

$ alarm run
Watching 1 alarm. Keep this terminal open.
  a3f91c  07:30  Standup   Tue 22 Sep 2026 07:30
```

…and at 07:30 the terminal fills with a banner and beeps until it is dismissed
with `Ctrl-C` or left alone to snooze.

## The shape of it

- **Foreground only.** `alarm run` holds a terminal. Close it and nothing rings.
- **Terminal bell + banner.** No audio files, no desktop notifications.
- **One-off alarms.** Add, list, remove, enable, disable, snooze, dismiss.
  Recurring alarms and timers are explicitly out of scope for v0.1.
- **Standard library only.** Python 3.9+, `git clone` and run.

The reasoning behind each of these — and what was rejected — is in
[requirements §2](docs/requirements.md#2-locked-scope-decisions).

---

## Reviewing

The four questions worth a decision before code is written are collected in
[requirements §8](docs/requirements.md#8-open-questions-for-review): the snooze
interval, whether fired alarms are kept or deleted, the missed-alarm catch-up
window, and whether a second `alarm run` should be refused.

One decision worth challenging explicitly: **v0.1 ships without an automated
test suite**, by decision. The consequences and the mitigation are set out in
[requirements §2](docs/requirements.md#2-locked-scope-decisions) and
[design §11](docs/design.md#11-risks-and-limitations).

## License

MIT — see [LICENSE](LICENSE).
