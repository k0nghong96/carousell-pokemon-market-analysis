"""Replace seller usernames with stable pseudonyms before publishing data.

Accepts CSV or JSON (whatever the scraper wrote) and emits both formats.

    python anonymize_data.py data/carousell_pokemon_surface_20260728_2237.csv
    python anonymize_data.py data/carousell_pokemon_surface_20260728_2237.json
    python anonymize_data.py --all data/

Writes <name>_anon.csv and <name>_anon.json next to the input.

The mapping is deterministic within a run, so seller-concentration analysis
still works exactly as before - you just can't trace a row to a real account.
"""

import csv
import json
import os
import sys

csv.field_size_limit(10_000_000)


def load(path):
    """Return a list of dicts from either a .csv or .json file."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise SystemExit(f"{path}: expected a JSON list of records.")
        return data
    if ext in (".csv", ".tsv"):
        delim = "\t" if ext == ".tsv" else ","
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f, delimiter=delim))
    raise SystemExit(f"{path}: unsupported file type '{ext}'. Use .csv or .json.")


def anonymize(path):
    if not os.path.exists(path):
        raise SystemExit(f"File not found: {path}")

    rows = load(path)
    if not rows:
        raise SystemExit(f"{path}: no records found.")
    if "seller" not in rows[0]:
        raise SystemExit(
            f"{path}: no 'seller' column. Columns present: {', '.join(rows[0])[:120]}"
        )

    mapping = {}
    for r in rows:
        name = (r.get("seller") or "").strip()
        if name:
            if name not in mapping:
                mapping[name] = f"seller_{len(mapping) + 1:04d}"
            r["seller"] = mapping[name]
        r.pop("sellerUrl", None)   # profile link is directly identifying

    stem = os.path.splitext(path)[0]
    json_out, csv_out = f"{stem}_anon.json", f"{stem}_anon.csv"

    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"  {os.path.basename(path)}")
    print(f"    {len(rows)} rows, {len(mapping)} sellers pseudonymised")
    print(f"    -> {os.path.basename(json_out)}")
    print(f"    -> {os.path.basename(csv_out)}")


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit(
            "usage: python anonymize_data.py <file.csv|file.json>\n"
            "       python anonymize_data.py --all data/"
        )

    if args[0] == "--all":
        folder = args[1] if len(args) > 1 else "data"
        targets = sorted(
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith((".csv", ".json")) and "_anon" not in f
        )
        if not targets:
            raise SystemExit(f"No .csv or .json files in {folder}/")
        print(f"Anonymising {len(targets)} file(s) in {folder}/\n")
        for t in targets:
            anonymize(t)
    else:
        for path in args:
            anonymize(path)

    print("\nDone. Commit the *_anon files and remove the originals from git.")


if __name__ == "__main__":
    main()
