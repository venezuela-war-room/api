"""
One-shot importer for consolidado.csv from ecrespo/OCR-data_Terremoto_Venezuela_24062026.

Usage:
    uv run python scripts/import_csv.py path/to/consolidado.csv --admin-key YOUR_KEY
    uv run python scripts/import_csv.py path/to/consolidado.csv --admin-key YOUR_KEY --api-url http://localhost:8000
"""

import argparse
import csv
import sys
from pathlib import Path

import httpx

COLUMN_MAP = {
    "Hospital / Área": "hospital",
    "Nombre": "full_name",
    "Edad": "age",
    "Cédula": "document_id",
    "Procedencia / Zona": "lugar_procedencia",
    "Servicio / Lista": "servicio",
    "Nota": "relevant_info",
}

BATCH_SIZE = 200


def parse_row(row: dict) -> dict | None:
    full_name = row.get("Nombre", "").strip()
    if not full_name or len(full_name) < 2:
        return None

    age_raw = row.get("Edad", "").strip()
    age = None
    if age_raw.isdigit():
        age = int(age_raw)
        if age > 150:
            age = None

    document_id_raw = row.get("Cédula", "").strip()
    document_id = "".join(c for c in document_id_raw if c.isdigit()) or None

    return {
        "full_name": full_name,
        "document_id": document_id,
        "age": age,
        "hospital": row.get("Hospital / Área", "").strip() or None,
        "servicio": row.get("Servicio / Lista", "").strip() or None,
        "lugar_procedencia": row.get("Procedencia / Zona", "").strip() or None,
        "relevant_info": row.get("Nota", "").strip() or None,
        "source_url": "https://github.com/ecrespo/OCR-data_Terremoto_Venezuela_24062026",
        "status": "verified",
    }


def import_csv(csv_path: Path, api_url: str, admin_key: str) -> None:
    records: list[dict] = []
    skipped = 0

    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = parse_row(row)
            if parsed:
                records.append(parsed)
            else:
                skipped += 1

    print(f"Parsed {len(records)} records ({skipped} skipped)")

    total_upserted = 0
    total_skipped = 0

    with httpx.Client(timeout=60) as client:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            r = client.post(
                f"{api_url}/api/v1/found-people/bulk",
                json={"people": batch},
                headers={"X-Admin-Key": admin_key},
            )
            if r.status_code != 201:
                print(f"  ERROR batch {i//BATCH_SIZE + 1}: {r.status_code} {r.text}", file=sys.stderr)
                continue
            body = r.json()
            total_upserted += body.get("upserted", 0)
            total_skipped += body.get("skipped", 0)
            print(f"  Batch {i//BATCH_SIZE + 1}: upserted={body.get('upserted')} skipped={body.get('skipped')}")

    print(f"\nDone. Total upserted: {total_upserted}, total skipped: {total_skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import consolidado.csv into the war-room API")
    parser.add_argument("csv_path", type=Path, help="Path to consolidado.csv")
    parser.add_argument("--admin-key", required=True, help="X-Admin-Key for the API")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Base URL of the API")
    args = parser.parse_args()

    if not args.csv_path.exists():
        print(f"File not found: {args.csv_path}", file=sys.stderr)
        sys.exit(1)

    import_csv(args.csv_path, args.api_url, args.admin_key)
