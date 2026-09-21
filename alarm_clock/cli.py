"""The command surface: argparse definition, dispatch, and exit codes."""

import argparse
import sys
from datetime import datetime, timedelta

from alarm_clock import __version__, commands, config, storage
from alarm_clock.runner import RunOptions, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alarm",
        description="A terminal alarm clock. Alarms ring only while `alarm run` is open.",
        epilog="Alarms are stored in {}".format(config.store_path()),
    )
    parser.add_argument("--version", action="version", version="alarm-clock-cli {}".format(__version__))

    subcommands = parser.add_subparsers(dest="command", metavar="<command>")

    add = subcommands.add_parser("add", help="schedule a new alarm")
    add.add_argument("time", metavar="HH:MM", help="24-hour time, for example 07:30")
    add.add_argument("--label", default="", help="what the alarm is for")

    listing = subcommands.add_parser("list", help="show scheduled alarms")
    listing.add_argument("--all", action="store_true", help="include disabled alarms")

    remove = subcommands.add_parser("remove", help="delete alarms permanently")
    remove.add_argument("ids", nargs="+", metavar="ID", help="alarm id, or an unambiguous prefix")

    enable = subcommands.add_parser("enable", help="re-arm a disabled alarm")
    enable.add_argument("id", metavar="ID")

    disable = subcommands.add_parser("disable", help="keep an alarm but stop it ringing")
    disable.add_argument("id", metavar="ID")

    runner = subcommands.add_parser("run", help="watch the clock and ring alarms")
    runner.add_argument("--ring-seconds", type=int, default=config.RING_SECONDS,
                        help="how long an alarm rings before snoozing (default: %(default)s)")
    runner.add_argument("--snooze-minutes", type=int, default=config.SNOOZE_MINUTES,
                        help="snooze length (default: %(default)s)")
    runner.add_argument("--max-snoozes", type=int, default=config.MAX_SNOOZES,
                        help="snoozes before an alarm gives up (default: %(default)s)")
    runner.add_argument("--once", action="store_true", help="exit after the first alarm completes")

    # Undocumented on purpose: omitting `help` keeps it out of `--help`.
    demo = subcommands.add_parser("demo")
    demo.add_argument("--ring-seconds", type=int, default=10)

    return parser


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "add":
        return commands.cmd_add(args.time, args.label)
    if args.command == "list":
        return commands.cmd_list(args.all)
    if args.command == "remove":
        return commands.cmd_remove(args.ids)
    if args.command == "enable":
        return commands.cmd_enable(args.id)
    if args.command == "disable":
        return commands.cmd_disable(args.id)
    if args.command == "run":
        return _run(args)
    if args.command == "demo":
        return _demo(args)
    raise AssertionError("unhandled command {!r}".format(args.command))


def _run(args: argparse.Namespace) -> int:
    for name, value in (
        ("--ring-seconds", args.ring_seconds),
        ("--snooze-minutes", args.snooze_minutes),
    ):
        if value < 1:
            raise ValueError("{} must be at least 1".format(name))
    if args.max_snoozes < 0:
        raise ValueError("--max-snoozes cannot be negative")

    return run(
        RunOptions(
            ring_seconds=args.ring_seconds,
            snooze_minutes=args.snooze_minutes,
            max_snoozes=args.max_snoozes,
            once=args.once,
        )
    )


def _demo(args: argparse.Namespace) -> int:
    """Ring a throwaway alarm now, so the banner and bell can be checked on demand."""
    from alarm_clock import ringer
    from alarm_clock.models import Alarm, parse_hhmm
    from alarm_clock.runner import InterruptFlag

    now = datetime.now()
    alarm = Alarm.create("demo00", parse_hhmm(now.strftime("%H:%M")), "Demo alarm", now)

    interrupts = InterruptFlag()
    interrupts.install()
    try:
        outcome = ringer.ring(
            alarm=alarm,
            scheduled_at=now - timedelta(seconds=2),
            ring_seconds=args.ring_seconds,
            snoozes_left=config.MAX_SNOOZES,
            snooze_minutes=config.SNOOZE_MINUTES,
            take_interrupts=interrupts.take,
        )
    finally:
        interrupts.restore()

    print("Demo finished: {}".format(outcome))
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    try:
        return _dispatch(args)
    except (storage.StoreError, ValueError) as exc:
        print("alarm: {}".format(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 0
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
