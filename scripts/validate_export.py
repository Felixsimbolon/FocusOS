"""Validate a downloaded application export locally. Never imports or creates events."""
import argparse
import json
from pathlib import Path
TABLES={"profiles","projects","tasks","source_items","memories","approval_requests"}
FORBIDDEN={"access_token","refresh_token","ciphertext","lease_token","encrypted_access_token","encrypted_refresh_token","service_role_key"}
def validate_export(data):
    if not isinstance(data,dict) or data.get("schema_version")!=1: raise ValueError("Unknown export version")
    tables=data.get("tables")
    if not isinstance(tables,dict) or set(tables)!=TABLES: raise ValueError("Missing or unknown tables")
    def walk(value):
        if isinstance(value,dict):
            if FORBIDDEN.intersection(value): raise ValueError("Credentials must not appear in export")
            for child in value.values():walk(child)
        elif isinstance(value,list):
            for child in value:walk(child)
    walk(data)
    for name,rows in tables.items():
        if not isinstance(rows,list) or len(rows)>1000 or any(not isinstance(row,dict) for row in rows):raise ValueError("Invalid table: "+name)
    truncated=data.get("truncated")
    if not isinstance(truncated,dict) or set(truncated)!=TABLES or any(type(value) is not bool for value in truncated.values()):raise ValueError("Missing completeness metadata")
    if any(truncated.values()):raise ValueError("Export is truncated; use a database backup for full recovery")
    return {name:len(rows) for name,rows in tables.items()}
def main():
    parser=argparse.ArgumentParser();parser.add_argument("file",type=Path);args=parser.parse_args()
    if args.file.stat().st_size>8_000_000:raise SystemExit("Export exceeds safe size")
    try:counts=validate_export(json.loads(args.file.read_text(encoding="utf-8")))
    except (ValueError,KeyError) as exc:raise SystemExit(str(exc))
    print("Valid complete application export. No data was restored.")
    print(json.dumps(counts))
if __name__=="__main__":main()
