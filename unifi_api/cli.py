import argparse
import json
import ssl
import sys
from pathlib import Path

from .client import APIError, UniFiClient
from .config import ConfigError


def _positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description="UniFi Network REST API client")
    parser.add_argument("--config", default="config.json", help="JSON config file (default: config.json)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("sites", "devices", "clients"):
        command = commands.add_parser(name, help=f"List all {name} (automatically paginated)")
        command.add_argument("--limit", type=_positive, default=25, help="Page size")
        command.add_argument("--filter", help="UniFi filter expression, if supported by the endpoint")
        if name != "sites":
            command.add_argument("--site", help="Site UUID (defaults to config site_id)")
    request = commands.add_parser("request", help="Call any endpoint relative to the configured API path")
    request.add_argument("method", choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
    request.add_argument("path", help="For example: sites/<site-id>/networks")
    request.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    request.add_argument("--body", type=Path, help="JSON request body file")
    args = parser.parse_args(argv)
    try:
        client = UniFiClient.from_config(args.config)
        if not client.config.verify_ssl:
            print("Warning: TLS certificate verification is disabled in config.", file=sys.stderr)
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
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ConfigError, APIError, ValueError, OSError, ssl.SSLError) as exc:
        # JSON parse errors can contain source content; show only a generic error.
        message = "Invalid JSON request body" if isinstance(exc, json.JSONDecodeError) else str(exc)
        print(f"Error: {message}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
