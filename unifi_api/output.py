"""Dependency-free table and JSON output."""

import json
import textwrap


def _cell(value):
    if isinstance(value, str):
        return "".join(c if c.isprintable() else c.encode("unicode_escape").decode("ascii") for c in value)
    return json.dumps(value, ensure_ascii=False)


def _flatten(record, prefix=""):
    result = {}
    for key, value in record.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and value:
            result.update(_flatten(value, name))
        else:
            result[name] = value
    return result


def _table(records, exclude_columns=()):
    if not records:
        return "No results."
    rows = [_flatten(row) if isinstance(row, dict) else {"Value": row} for row in records]
    columns = list(dict.fromkeys(key for row in rows for key in row if key not in exclude_columns))
    if not columns:
        return f"{len(rows)} empty object(s)."
    headers = [_cell(column) for column in columns]
    cells = [[_cell(row[column]) if column in row else "" for column in columns] for row in rows]
    widths = [min(40, max(1, len(headers[i]), *(len(row[i]) for row in cells))) for i in range(len(columns))]
    def border(left, junction, right):
        return left + junction.join("─" * (width + 2) for width in widths) + right

    lines = [border("┌", "┬", "┐")]

    def append_row(row):
        wrapped = [textwrap.wrap(value, width=width, replace_whitespace=False, drop_whitespace=False) or [""] for value, width in zip(row, widths)]
        for index in range(max(map(len, wrapped))):
            lines.append("│ " + " │ ".join((value[index] if index < len(value) else "").ljust(width) for value, width in zip(wrapped, widths)) + " │")

    append_row(headers)
    lines.append(border("├", "┼", "┤"))
    for index, row in enumerate(cells):
        append_row(row)
        lines.append(border("└", "┴", "┘") if index == len(cells) - 1 else border("├", "┼", "┤"))
    return "\n".join(lines)


def render(result, output_format="table", *, exclude_columns=()):
    if output_format == "json":
        return json.dumps(result, indent=2, ensure_ascii=False)
    if result is None:
        return "Request completed (no response body)."
    if isinstance(result, dict) and isinstance(result.get("data"), list):
        metadata = {key: value for key, value in result.items() if key != "data"}
        return (_table([metadata]) + "\n" if metadata else "") + _table(result["data"], exclude_columns)
    if isinstance(result, list):
        return _table(result, exclude_columns)
    return _table([result], exclude_columns)


def render_status(summary):
    """Render the status snapshot as readable sections instead of one wide row."""
    lines = ["UNIFI NETWORK STATUS", f"Site: {_cell(summary['siteName'])}",
             f"Updated: {_cell(summary['updatedAt'])}"]

    def section(title, rows):
        lines.extend(["", title, _table(rows)])

    def count(key):
        return "Unavailable" if summary[key] is None else len(summary[key])

    section("Overview", [
        {"Metric": "Devices", "Value": summary["devices"]},
        {"Metric": "Connected clients", "Value": summary["connectedClients"]},
        {"Metric": "Firmware updates available", "Value": summary["firmwareUpdates"]},
        {"Metric": "Networks", "Value": count("networks")},
        {"Metric": "Wi-Fi broadcasts", "Value": count("wifi")},
        {"Metric": "WAN definitions", "Value": count("wan")},
    ])
    section("Device states / client types", [
        {"Category": category, "State / type": state, "Count": number}
        for category, counts in (("Device", summary["deviceStates"]), ("Client", summary["clientTypes"]))
        for state, number in sorted(counts.items())
    ])
    section("Devices (clients grouped by reported upstream device)", [
        {"Name": d.get("name", "Unknown"), "Model": d.get("model", "Unknown"),
         "State": d.get("state", "UNKNOWN"), "IP address": d.get("ipAddress", "Unavailable"),
         "Clients": d["clients"], "Update": "Available" if d.get("firmwareUpdatable") is True else
         "No" if d.get("firmwareUpdatable") is False else "Unknown"}
        for d in summary["deviceDetails"]
    ])
    for key, title, fields in (
        ("networks", "Networks", (("name", "Name"), ("vlanId", "VLAN"), ("enabled", "Enabled"))),
        ("wifi", "Wi-Fi broadcasts", (("name", "Name"), ("enabled", "Enabled"),
                                       ("broadcastingFrequenciesGHz", "Bands (GHz)"),
                                       ("securityConfiguration.type", "Security"))),
        ("wan", "WAN interface definitions", (("name", "Name"),)),
    ):
        if summary[key] is None:
            lines.extend(["", title, "Unavailable (see collection warnings below)."])
        else:
            rows = [_flatten(item) for item in summary[key]]
            section(title, [{label: row.get(field, "Unavailable") for field, label in fields} for row in rows])
    lines.extend(["", "WAN definitions do not indicate internet connectivity."])
    if summary["alerts"]:
        section("Needs review", [{"Observation": item} for item in summary["alerts"]])
    if summary["warnings"]:
        section("Collection warnings", [{"Warning": item} for item in summary["warnings"]])
    return "\n".join(lines)
