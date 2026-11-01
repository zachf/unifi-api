"""Collect a site summary without per-device detail requests."""

from collections import Counter
from datetime import datetime

from .client import APIError


def collect_status(client, site_id=None):
    warnings = []
    site_id = site_id or client.config.site_id
    try:
        sites = list(client.sites())
    except APIError as exc:
        if not site_id:
            raise
        sites = []
        warnings.append("Site name unavailable: " + str(exc))
    if not site_id:
        if len(sites) != 1:
            raise ValueError("Select a site with use, provide --site, or set site_id in the config file")
        site_id = sites[0]["id"]
    site_name = next((s.get("name", site_id) for s in sites if s["id"] == site_id), site_id)
    devices = list(client.devices(site_id))
    clients = list(client.clients(site_id))
    device_states = dict(Counter(str(d.get("state", "UNKNOWN")) for d in devices))
    client_types = dict(Counter(str(c.get("type", "UNKNOWN")) for c in clients))
    updates = sum(d.get("firmwareUpdatable") is True for d in devices)
    alerts = [f"{count} device(s) report {state}" for state, count in sorted(device_states.items())
              if state.upper() not in {"ONLINE", "CONNECTED"}]
    if updates:
        alerts.append(f"Firmware updates available for {updates} device(s)")
    uplinks = Counter(c.get("uplinkDeviceId") for c in clients)
    rows = []
    for device in devices:
        row = {k: device[k] for k in ("id", "name", "model", "ipAddress", "state", "firmwareVersion", "firmwareUpdatable") if k in device}
        row["clients"] = uplinks[device.get("id")] if device.get("id") else 0
        rows.append(row)
    result = {"site_id": site_id, "siteName": site_name,
              "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
              "devices": len(devices), "deviceStates": device_states,
              "connectedClients": len(clients), "clientTypes": client_types,
              "firmwareUpdates": updates, "deviceDetails": rows, "alerts": alerts,
              "warnings": warnings}
    # Optional endpoints may be unsupported or forbidden on older controllers.
    # None means unavailable, whereas [] means a successfully queried empty list.
    for key, method in (("networks", client.networks), ("wifi", client.wifi), ("wan", client.wan)):
        try:
            result[key] = list(method(site_id))
        except APIError as exc:
            result[key] = None
            warnings.append(f"{key}: {exc}")
    return result
