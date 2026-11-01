import argparse
import json
import math
import shlex
import ssl
import sys
import time
from datetime import datetime
from pathlib import Path

from .client import APIError, UniFiClient
from .config import ConfigError
from .commands import READ_COMMANDS, Session, query
from .export import export_csv
from .output import render, render_status, render_vertical


def _positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def _interval(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive number of seconds")
    return number


def _output_option(parser, *, default="table"):
    parser.add_argument("--json", action="store_const", const="json", dest="output_format",
                        default=default, help="Display JSON instead of a table")


def build_parser():
    parser = argparse.ArgumentParser(description="UniFi Network REST API client")
    parser.add_argument("--config", default="config.json", help="JSON config file (default: config.json)")
    _output_option(parser)
    commands = parser.add_subparsers(dest="command")
    shell = commands.add_parser("shell", help="Start the interactive command prompt (also the default)")
    _output_option(shell, default=argparse.SUPPRESS)
    for name in ("sites", "devices", "clients", "networks", "wifi", "wan"):
        command = commands.add_parser(name, help=f"List all {name} (automatically paginated)")
        _output_option(command, default=argparse.SUPPRESS)
        command.add_argument("--limit", type=_positive, default=25, help="Page size")
        if name != "wan":
            command.add_argument("--filter", help="UniFi filter expression, if supported by the endpoint")
        if name != "sites":
            command.add_argument("--site", help="Site UUID (defaults to config site_id)")
    info = commands.add_parser("info", help="Show the Network application version")
    _output_option(info, default=argparse.SUPPRESS)
    for name in ("status", "device", "client", "ports", "stats", "find", "use"):
        command = commands.add_parser(name, help={
            "status": "Show a site summary screen with devices, clients, networks, Wi-Fi, and WAN",
            "stats": "Show a device's latest CPU, memory, uptime, and throughput statistics",
            "device": "Look up a device by name, IP, MAC, or UUID",
            "client": "Look up a client by name, IP, MAC, or UUID",
            "ports": "Show a device's ports, link speeds, and PoE information",
            "find": "Search devices and clients",
            "use": "Select a site by name or UUID for the interactive session",
        }[name])
        _output_option(command, default=argparse.SUPPRESS)
        if name != "use":
            command.add_argument("--site", help="Site UUID (overrides session and config)")
        if name != "status":
            command.add_argument("selector", help="Name or identifier; quote names containing spaces")
    watch = commands.add_parser("watch", help="Repeat a read command until Ctrl+C exits the utility")
    _output_option(watch, default=argparse.SUPPRESS)
    watch.add_argument("--interval", type=_interval, default=5, help="Refresh interval in seconds (default: 5)")
    watch.add_argument("--count", type=_positive, help="Stop after this many refreshes")
    watch.add_argument("target", choices=READ_COMMANDS)
    watch.add_argument("arguments", nargs=argparse.REMAINDER, help="Command options; --interval and --count may also follow the command")
    export = commands.add_parser("export", help="Export full read-command results to CSV")
    export.add_argument("--force", action="store_true", help="Overwrite an existing CSV file")
    export.add_argument("target", choices=READ_COMMANDS)
    export.add_argument("file", type=Path)
    export.add_argument("arguments", nargs=argparse.REMAINDER, help="Command options; selectors follow the filename")
    request = commands.add_parser("request", help="Call any endpoint relative to the configured API path")
    _output_option(request, default=argparse.SUPPRESS)
    request.add_argument("method", choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
    request.add_argument("path", help="For example: sites/<site-id>/networks")
    request.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    request.add_argument("--body", type=Path, help="JSON request body file")
    return parser


def _result(client, args, session):
    if args.command == "request":
        params = []
        for item in args.param:
            key, sep, value = item.partition("=")
            if not sep or not key:
                raise ValueError("--param must be KEY=VALUE")
            params.append((key, value))
        body = json.loads(args.body.read_text(encoding="utf-8-sig")) if args.body else None
        return client.request(args.method, args.path, params=params, body=body)
    return query(client, args, session)


def _nested_command(args):
    options = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    if args.command == "watch":
        options.add_argument("--interval", type=_interval, default=args.interval)
        options.add_argument("--count", type=_positive, default=args.count)
    else:
        options.add_argument("--force", action="store_true", default=args.force)
    wrapper, remaining = options.parse_known_args(args.arguments)
    nested = build_parser().parse_args([args.target] + remaining)
    if nested.config != "config.json":
        raise ValueError("Choose --config when starting the utility")
    if "--json" not in remaining:
        nested.output_format = getattr(args, "output_format", "table")
    return wrapper, nested


def execute(client, args, session=None):
    session = session if session is not None else Session()
    if args.command in {"watch", "export"}:
        wrapper, nested = _nested_command(args)
        if args.command == "export":
            # Refuse an accidental overwrite before making API requests.
            if args.file.exists() and not wrapper.force:
                raise ValueError("Export file already exists; use --force to overwrite it")
            count = export_csv(_result(client, nested, session), args.file, wrapper.force)
            print(f"Exported {count} row(s) to {args.file}")
            return
        count = 0
        while True:
            print(f"Updated {datetime.now().astimezone().isoformat(timespec='seconds')}", file=sys.stderr)
            execute(client, nested, session)
            count += 1
            if wrapper.count is not None and count >= wrapper.count:
                return
            time.sleep(wrapper.interval)
    result = _result(client, args, session)
    exclude_columns = {
        "sites": {"id", "uplinkDeviceId", "access.type"},
        "clients": {"id", "uplinkDeviceId", "access.type"},
        "devices": {"id"},
    }.get(args.command, ())
    if args.command == "status" and args.output_format == "table":
        print(render_status(result))
    elif args.command == "stats" and args.output_format == "table":
        print(render_vertical(result))
    else:
        print(render(result, args.output_format, exclude_columns=exclude_columns))


def _report_error(exc):
    message = "Invalid JSON request body" if isinstance(exc, json.JSONDecodeError) else str(exc)
    print(f"Error: {message}", file=sys.stderr)


_COMMANDS = [
    {"Command": "sites", "Description": "List sites"},
    {"Command": "devices [--site UUID]", "Description": "List adopted devices"},
    {"Command": "clients [--site UUID]", "Description": "List connected clients"},
    {"Command": "networks [--site UUID]", "Description": "List networks"},
    {"Command": "use NAME-OR-UUID", "Description": "Select a site for this session"},
    {"Command": "status", "Description": "Show the site summary screen"},
    {"Command": "device NAME-IP-MAC-OR-UUID", "Description": "Show device details"},
    {"Command": "client NAME-IP-MAC-OR-UUID", "Description": "Show client details"},
    {"Command": "ports DEVICE", "Description": "Show ports, link speeds, and PoE"},
    {"Command": "stats DEVICE", "Description": "Show latest device CPU, memory, uptime, and throughput"},
    {"Command": "info", "Description": "Show the Network application version"},
    {"Command": "wifi", "Description": "List Wi-Fi broadcasts and settings"},
    {"Command": "wan", "Description": "List WAN interface definitions"},
    {"Command": "find TEXT", "Description": "Search devices and clients"},
    {"Command": "watch COMMAND --interval 5", "Description": "Refresh a read command; Ctrl+C exits"},
    {"Command": "export COMMAND FILE.csv", "Description": "Export full results; --force overwrites"},
    {"Command": "request METHOD PATH", "Description": "Call an API endpoint; --param KEY=VALUE, --body FILE"},
    {"Command": "format table|json", "Description": "Set the session output format"},
    {"Command": "help [COMMAND]", "Description": "Show commands or command options"},
    {"Command": "exit / quit / Ctrl+C", "Description": "Close the prompt"},
]


def _enable_history():
    # Use native console editing on Windows; avoid third-party readline shims.
    if sys.platform == "win32":
        return
    # Importing readline gives input() line editing and Up/Down history on Unix,
    # including PyPy. Keep history in memory for this session only.
    try:
        import readline
    except ImportError:
        print("Command history unavailable: this Python build has no readline support.", file=sys.stderr)
        return
    if hasattr(readline, "set_auto_history"):
        readline.set_auto_history(True)


def interactive(client, output_format="table"):
    _enable_history()
    parser = build_parser()
    session = Session()
    print("UniFi Network command prompt. Up/Down: command history. Type help for commands; exit or Ctrl+C to quit.")
    print(render(_COMMANDS))
    while True:
        try:
            line = input("unifi> ")
            # Preserve Windows path backslashes while accepting quoted arguments.
            lexer = shlex.shlex(line, posix=True)
            lexer.whitespace_split = True
            lexer.commenters = ""
            lexer.escape = ""
            tokens = list(lexer)
            if not tokens:
                continue
            if tokens[0] in {"exit", "quit", "EOF"}:
                if len(tokens) != 1:
                    raise ValueError("exit and quit take no arguments")
                return 0
            if tokens[0] == "format":
                if len(tokens) != 2 or tokens[1] not in {"table", "json"}:
                    raise ValueError("Usage: format table|json")
                output_format = tokens[1]
                print(f"Output format: {output_format}")
                continue
            if tokens[0] == "help":
                if len(tokens) == 1:
                    print(render(_COMMANDS))
                    print("Add --json to any API command. List commands accept --limit and --filter.")
                    continue
                if len(tokens) != 2 or tokens[1] not in set(READ_COMMANDS) | {"use", "watch", "export", "request"}:
                    raise ValueError("Usage: help COMMAND (type help to list commands)")
                tokens = [tokens[1], "--help"]
            try:
                args = parser.parse_args(tokens)
            except SystemExit:
                # argparse help and invalid commands must not close the session.
                continue
            if args.command in (None, "shell"):
                raise ValueError("Already in the command prompt; type help to list commands")
            if args.config != "config.json":
                raise ValueError("Choose --config when starting the utility")
            if "--json" not in tokens:
                args.output_format = output_format
            try:
                execute(client, args, session)
            except SystemExit:
                # Nested watch/export argument errors also leave the prompt open.
                continue
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 130
        except (APIError, ValueError, OSError) as exc:
            _report_error(exc)


def main(argv=None):
    # Windows redirected output can default to cp1252, which lacks box drawing.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        client = UniFiClient.from_config(args.config)
        if not client.config.verify_ssl:
            print("Warning: TLS certificate verification is disabled in config.", file=sys.stderr)
        if args.command in (None, "shell"):
            return interactive(client, args.output_format)
        if args.command == "use":
            raise ValueError("use selects a site inside the interactive shell; use --site for direct commands")
        execute(client, args)
        return 0
    except (ConfigError, APIError, ValueError, OSError, ssl.SSLError) as exc:
        _report_error(exc)
        return 1
    except KeyboardInterrupt:
        return 130
