"""
One-time migration script: move all flat reports/ files into date-based subfolders.

Each file's run date is read from its own JSON 'timestamp' field.
For CSV files (no timestamp), the date is inferred from the corresponding _final.json.
The cross-run summary.csv (single-row legacy file) is left at the root.
"""
import json
import shutil
from pathlib import Path


def main():
    reports_dir = Path("reports")
    if not reports_dir.is_dir():
        print("No reports/ directory found. Nothing to do.")
        return

    # Only process files directly in reports/ (not already in subfolders)
    flat_jsons = [f for f in reports_dir.iterdir() if f.is_file() and f.suffix == ".json"]
    flat_csvs  = [f for f in reports_dir.iterdir() if f.is_file() and f.suffix == ".csv"]

    date_map: dict[str, str] = {}  # filename -> YYYY-MM-DD

    # --- Build date map from JSON timestamps ---
    for jf in flat_jsons:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            ts = data.get("timestamp", "")
            if ts:
                date_map[jf.name] = ts[:10]
        except Exception as e:
            print(f"  WARN: could not read {jf.name}: {e}")

    # --- Infer CSV dates from corresponding _final.json ---
    for csv_f in flat_csvs:
        if csv_f.name == "summary.csv":
            continue  # top-level cross-run summary stays at root
        # e.g. KCoO2_Al_summary.csv -> stem = KCoO2_Al -> final = KCoO2_Al_final.json
        stem = csv_f.stem.replace("_summary", "")
        final_name = f"{stem}_final.json"
        if final_name in date_map:
            date_map[csv_f.name] = date_map[final_name]

    # --- Move files ---
    moved: list[tuple[str, str]] = []
    for fname, run_date in sorted(date_map.items()):
        src = reports_dir / fname
        if not src.exists():
            continue
        dest_dir = reports_dir / run_date
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / fname
        shutil.move(str(src), str(dest))
        moved.append((fname, run_date))

    # --- Summary ---
    if moved:
        print(f"Moved {len(moved)} file(s) into date folders:")
        for fname, d in moved:
            print(f"  reports/{d}/{fname}")
    else:
        print("Nothing to move — files may already be organized.")

    remaining = [f.name for f in reports_dir.iterdir() if f.is_file()]
    if remaining:
        print(f"\nFile(s) kept at reports/ root: {', '.join(remaining)}")


if __name__ == "__main__":
    main()
