# alarm-clock-cli

A terminal alarm clock in Python. No web UI, no database, no third-party
packages — just the standard library and a process you leave running in a
terminal tab.

```
+============================================================+
|                         A L A R M                          |
+============================================================+
|  Standup                                                   |
|  Scheduled 07:30   .   Now 07:30:00                        |
+============================================================+
|  Ctrl-C to dismiss  .  ignore to snooze 9m (3 left)        |
+============================================================+
  ringing -  47s left
```

> **It only rings while `alarm run` is open.** This is a foreground program by
> design — it is not a daemon and it does not survive closing the terminal,
> logging out, or rebooting. Leave it in a spare tab or a `tmux` pane.

---

## Install

Needs Python 3.9 or newer. Nothing else.

```bash
git clone https://github.com/Shailesh-Kala/alarm-clock-cli.git
cd alarm-clock-cli
python3 -m alarm_clock --help
```

Optionally put `alarm` on your PATH:

```bash
pip install -e .
```

Every example below works either way — `alarm <command>` or
`python3 -m alarm_clock <command>`.

## Use it

```bash
alarm add 07:30 --label "Standup"     # schedule it
alarm list                            # see what is armed
alarm run                             # leave this running
```

```
$ alarm add 07:30 --label "Standup"
Added a3f91c 07:30 "Standup" - first ring Tue 22 Sep 2026 07:30

$ alarm list
ID      TIME   LABEL    NEXT FIRE
a3f91c  07:30  Standup  Tue 22 Sep 2026 07:30

$ alarm run
Watching 1 alarm. Keep this terminal open; Ctrl-C to stop.
  a3f91c  07:30  Standup               Tue 22 Sep 2026 07:30
```

When it goes off, the banner appears and the terminal beeps. Then either:

- **`Ctrl-C`** — dismiss it. The loop keeps running for your other alarms.
- **do nothing** — after 60 seconds it snoozes for 9 minutes and comes back, up
  to 3 times, then gives up and disables itself.

`Ctrl-C` while nothing is ringing stops the program.

## Commands

| Command | What it does |
|---|---|
| `alarm add HH:MM [--label TEXT]` | Schedule a one-off alarm at the next occurrence of that time |
| `alarm list [--all]` | Show armed alarms; `--all` includes disabled ones |
| `alarm remove ID [ID...]` | Delete alarms permanently |
| `alarm enable ID` | Re-arm a disabled alarm |
| `alarm disable ID` | Keep an alarm but stop it ringing |
| `alarm run [options]` | Watch the clock and ring alarms |
| `alarm --version` | Print the version |

Anywhere an `ID` is accepted, an unambiguous prefix works too — `alarm remove a3f`.

Options for `run`, useful for trying it out without waiting for real time to pass:

| Flag | Default | Meaning |
|---|---|---|
| `--ring-seconds N` | 60 | How long it rings before snoozing |
| `--snooze-minutes N` | 9 | How long a snooze lasts |
| `--max-snoozes N` | 3 | Snoozes before it gives up |
| `--once` | off | Exit after the first alarm finishes |

```bash
# a fast demonstration of the whole snooze cycle
alarm add $(date -v+1M +%H:%M) --label "Test"
alarm run --ring-seconds 3 --snooze-minutes 1 --max-snoozes 2
```

There is also an undocumented `alarm demo`, which rings a throwaway alarm right
now so you can check the banner and the bell without scheduling anything.

## Times

`HH:MM`, 24-hour. `7:30` and `07:30` both work; anything else is rejected.

An alarm always means **the next time that clock reading comes around** — add
`07:30` at 09:00 and it fires tomorrow morning. `alarm add` always prints the
absolute date and time it resolved to, so this is never a guess.

## Where alarms live

A single JSON file, in the first of these that applies:

1. `$ALARM_CLOCK_HOME/alarms.json`
2. `$XDG_DATA_HOME/alarm-clock/alarms.json`
3. `~/.local/share/alarm-clock/alarms.json`

`alarm --help` prints the resolved path. The file is plain JSON and safe to read
or hand-edit; writes are atomic, so an interrupted write cannot cost you your
alarms.

A running `alarm run` notices changes to that file, so you can add or remove
alarms from a second terminal without restarting it.

## If you cannot hear the bell

The alarm writes the ASCII bell character, which many terminals mute by default.
The banner is the primary alert for exactly that reason, but to get a sound:

- **macOS Terminal** — Settings → Profiles → Advanced → Bell: tick *Audible bell*
  (or *Visual bell* for a flash).
- **iTerm2** — Settings → Profiles → Terminal → Notifications: tick
  *Silence bell* **off**.
- **tmux** — `set -g bell-action any` in `~/.tmux.conf`.

## Limitations

Deliberate, and worth knowing before you rely on it:

- **Foreground only.** Close the terminal and nothing rings. No daemon, no
  launchd, no reboot survival.
- **One-off alarms only.** No recurring or repeating alarms in v0.1.
- **Terminal alert only.** No sound files, no desktop notifications.
- **Sleep.** If the machine is asleep when an alarm is due, it rings on wake if
  it is less than two minutes late; anything later is reported as missed rather
  than going off at the wrong time.
- **Two `alarm run` processes will both ring.** There is no lock.
- **No automated test suite in v0.1** — see the
  [manual verification checklist](docs/implementation-plan.md#3-manual-verification-checklist).

## Documentation

The planning documents this was built from, kept current with the code:

| Document | Contents |
|---|---|
| [Requirements](docs/requirements.md) | Scope decisions, functional requirements, acceptance criteria |
| [Design](docs/design.md) | Architecture, data model, run loop, ring/snooze state machine, edge cases |
| [Implementation plan](docs/implementation-plan.md) | Build phases, manual verification checklist, definition of done |

## License

MIT — see [LICENSE](LICENSE).
