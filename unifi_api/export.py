"""CSV export of full query results, independent of table column visibility."""

import csv
import json
from pathlib import Path

from .output import _flatten


def export_csv(result, filename, force=False):
    if isinstance(result, dict) and isinstance(result.get("data"), list):
        result = result["data"]
    records = result if isinstance(result, list) else ([] if result is None else [result])
    rows = [_flatten(row) if isinstance(row, dict) else {"Value": row} for row in records]
    columns = list(dict.fromkeys(key for row in rows for key in row))
    path = Path(filename)
    with path.open("w" if force else "x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        if columns:
            writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, bool))
                             else "" if value is None else value for key, value in row.items()})
    return len(rows)
