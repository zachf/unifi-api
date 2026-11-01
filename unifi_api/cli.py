import argparse
import json
import shlex
import ssl
import sys
from pathlib import Path

from .client import APIError, UniFiClient
from .config import ConfigError
from .output import render


def _positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
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
    for name in ("sites", "devices", "clients"):
        command = commands.add_parser(name, help=f"List all {name} (automatically paginated)")
        _output_option(command, default=argparse.SUPPRESS)
        command.add_argument("--limit", type=_positive, default=25, help="Page size")
        command.add_argument("--filter", help="UniFi filter expression, if supported by the endpoint")
        if name != "sites":
            command.add_argument("--site", help="Site UUID (defaults to config site_id)")
    request = commands.add_parser("request", help="Call any endpoint relative to the configured API path")
    _output_option(request, default=argparse.SUPPRESS)
    request.add_argument("method", choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
    request.add_argument("path", help="For example: sites/<site-id>/networks")
    request.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    request.add_argument("--body", type=Path, help="JSON request body file")
    return parser


def execute(client, args):
    if args.command == "request":
        params = []
        for item in args.param:
            key, sep, value = item.partition("=")
            if not sep or not key:
                raise ValueError("--param must be KEY=VALUE")
            params.append((key, value))
        body = json.loads(args.body.read_text(encoding="utf-8-sig")) if args.body else None
        result = client.request(args.method, args.path, params=params, body=body)
    else:
        kwargs = {"limit": args.limit, "filter": args.filter}
        if args.command != "sites":
            kwargs["site_id"] = args.site
        result = list(getattr(client, args.command)(**kwargs))
    exclude_columns = {"id", "uplinkDeviceId", "access.type"} if args.command in {"sites", "clients"} else ()
    print(render(result, args.output_format, exclude_columns=exclude_columns))


def _report_error(exc):
    message = "Invalid JSON request body" if isinstance(exc, json.JSONDecodeError) else str(exc)
    print(f"Error: {message}", file=sys.stderr)


_COMMANDS = [
    {"Command": "sites", "Description": "List sites"},
    {"Command": "devices [--site UUID]", "Description": "List adopted devices"},
    {"Command": "clients [--site UUID]", "Description": "List connected clients"},
    {"Command": "request METHOD PATH", "Description": "Call an API endpoint; --param KEY=VALUE, --body FILE"},
    {"Command": "format table|json", "Description": "Set the session output format"},
    {"Command": "help [COMMAND]", "Description": "Show commands or command options"},
    {"Command": "exit / quit", "Description": "Close the prompt (or press Ctrl+Z then Enter on Windows)"},
]


def interactive(client, output_format="table"):
    parser = build_parser()
    print("UniFi Network command prompt. Type help for commands; exit to quit.")
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
                if len(tokens) != 2 or tokens[1] not in {"sites", "devices", "clients", "request"}:
                    raise ValueError("Usage: help [sites|devices|clients|request]")
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
            execute(client, args)
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print("\nCommand cancelled. Type exit to quit.")
        except (APIError, ValueError, OSError) as exc:
            _report_error(exc)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        client = UniFiClient.from_config(args.config)
        if not client.config.verify_ssl:
            print("Warning: TLS certificate verification is disabled in config.", file=sys.stderr)
        if args.command in (None, "shell"):
            return interactive(client, args.output_format)
        execute(client, args)
        return 0
    except (ConfigError, APIError, ValueError, OSError, ssl.SSLError) as exc:
        _report_error(exc)
        return 1
    except KeyboardInterrupt:
        return 130
