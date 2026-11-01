"""Read-only network queries and session state."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .status import collect_status


READ_COMMANDS = ("sites", "devices", "clients", "networks", "wifi", "wan",
                 "status", "device", "client", "ports", "find", "stats", "info")


@dataclass
class Session:
    site_id: str = None


def _mac(value):
    value = re.sub(r"[:.\-]", "", value).lower()
    return value if re.fullmatch(r"[0-9a-f]{12}", value) else None


def matches(record, text, exact=False):
    for field in ("id", "name", "ipAddress", "macAddress"):
        value = str(record.get(field, ""))
        if value.casefold() == text.casefold():
            return True
        if field == "macAddress" and _mac(text) and _mac(text) == _mac(value):
            return True
        if not exact and text.casefold() in value.casefold():
            return True
    return False


def select(records, selector, kind):
    if not selector.strip():
        raise ValueError(f"Provide a {kind} name or identifier")
    records = list(records)
    found = [item for item in records if matches(item, selector, exact=True)]
    if not found:
        found = [item for item in records if matches(item, selector)]
    if not found:
        raise ValueError(f"No matching {kind}")
    if len(found) != 1:
        raise ValueError(f"Multiple matching {kind}s; use an exact name, UUID, IP, or MAC address")
    return found[0]


def _duration(start, now=None):
    try:
        started = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    except ValueError:
        return None
    if started.tzinfo is None:
        return None
    seconds = int(((now or datetime.now(timezone.utc)) - started).total_seconds())
    if seconds < 0:
        return None
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    return f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"


def enrich_clients(client, clients, site):
    # Resolve uplink device names only when a client references one.
    if any(c.get("uplinkDeviceId") for c in clients):
        names = {d["id"]: d.get("name", d.get("macAddress", d["id"])) for d in client.devices(site)}
    else:
        names = {}
    result = []
    for item in clients:
        row = dict(item)
        if item.get("uplinkDeviceId"):
            row["uplinkDevice"] = names.get(item["uplinkDeviceId"])
        if item.get("connectedAt"):
            row["connectedFor"] = _duration(item["connectedAt"])
        result.append(row)
    return result


def query(client, args, session):
    site = getattr(args, "site", None) or session.site_id
    command = args.command
    if command in {"sites", "devices", "clients", "networks", "wifi", "wan"}:
        kwargs = {"limit": args.limit}
        if command != "wan":
            kwargs["filter"] = args.filter
        if command != "sites":
            kwargs["site_id"] = site
        items = list(getattr(client, command)(**kwargs))
        return enrich_clients(client, items, site) if command == "clients" else items
    if command == "info":
        return client.info()
    if command == "stats":
        item = select(client.devices(site), args.selector, "device")
        stats = client.device_statistics(item["id"], site) or {}
        return dict({key: item[key] for key in ("name", "model", "state") if key in item}, **stats)
    if command == "use":
        selected = select(client.sites(), args.selector, "site")
        session.site_id = selected["id"]
        return {"site": selected.get("name", selected["id"]), "site_id": selected["id"]}
    if command == "status":
        return collect_status(client, site)
    if command == "find":
        if not args.selector.strip():
            raise ValueError("Search text must not be empty")
        result = []
        for kind, items in (("device", client.devices(site)), ("client", client.clients(site))):
            for item in items:
                if matches(item, args.selector):
                    row = {"kind": kind}
                    row.update({key: item[key] for key in ("id", "name", "ipAddress", "macAddress", "state", "type") if key in item})
                    result.append(row)
        return result
    if command == "client":
        item = select(client.clients(site), args.selector, "client")
        return dict(item, **client.client_details(item["id"], site))
    if command in {"device", "ports"}:
        item = select(client.devices(site), args.selector, "device")
        detail = dict(item, **client.device_details(item["id"], site))
        if command == "device":
            return detail
        # Some versions expose only the upstream device, without a port index.
        # Preserve raw port fields and never guess client-to-port associations.
        ports = detail.get("interfaces", {}).get("ports", [])
        upstream_clients = [c for c in client.clients(site) if c.get("uplinkDeviceId") == item["id"]] if ports else []
        mapped = all(c.get("uplinkPortIdx") is not None for c in upstream_clients)
        return [dict(port, connectedClients=[c.get("name", c.get("macAddress", c["id"])) for c in upstream_clients
                                            if c["uplinkPortIdx"] == port.get("idx")] if mapped else None)
                for port in ports]
    raise ValueError("Unsupported query command")
