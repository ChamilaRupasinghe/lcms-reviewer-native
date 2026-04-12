import argparse
import sqlite3
from pathlib import Path
import sys
import pandas as pd
import re

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lcms_parent_metabolite_analyzer as analyzer

HEATMAP_ROWS = "ABCDEFGH"
HEATMAP_DIRECT_WELL_RE = re.compile(r"^\s*([A-Ha-h])\s*(?:-|\s*)?([1-9]|1[0-2])\s*$")
HEATMAP_TRAILING_INT_RE = re.compile(r"(\d{1,3})\s*$")


def vial_number_to_well(vial_number: int | None) -> str:
    if vial_number is None or vial_number < 1 or vial_number > 96:
        return ""
    zero_based = vial_number - 1
    row = HEATMAP_ROWS[zero_based // 12]
    col = (zero_based % 12) + 1
    return f"{row}{col}"


def coerce_vial_number(value) -> int | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            number = int(value)
        except Exception:
            return None
        return number if 1 <= number <= 96 else None

    text = str(value).strip()
    if not text:
        return None

    if text.endswith(".0"):
        text = text[:-2]

    if text.isdigit():
        number = int(text)
        return number if 1 <= number <= 96 else None

    match = HEATMAP_TRAILING_INT_RE.search(text)
    if match:
        number = int(match.group(1))
        return number if 1 <= number <= 96 else None

    return None


def normalize_well_label(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    match = HEATMAP_DIRECT_WELL_RE.match(text)
    if match:
        return f"{match.group(1).upper()}{int(match.group(2))}"

    vial_number = coerce_vial_number(text)
    if vial_number is not None:
        return vial_number_to_well(vial_number)

    return ""


def norm_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def build_position_lookup(long_df: pd.DataFrame) -> dict[tuple[str, str], str]:
    if long_df is None or long_df.empty:
        return {}

    columns = list(long_df.columns)
    lower_map = {str(col).strip().lower(): col for col in columns}

    accession_col = lower_map.get("sample name") or lower_map.get("accession")
    source_file_col = lower_map.get("source_file")
    vial_position_col = (
        lower_map.get("sample vial position")
        or lower_map.get("vial position")
        or lower_map.get("well position")
    )
    sample_order_col = (
        lower_map.get("sample order")
        or lower_map.get("vial number")
        or lower_map.get("position number")
    )

    print("ACCESSION_COL:", accession_col)
    print("SOURCE_FILE_COL:", source_file_col)
    print("VIAL_POSITION_COL:", vial_position_col)
    print("SAMPLE_ORDER_COL:", sample_order_col)

    if accession_col is None:
        return {}

    lookup: dict[tuple[str, str], str] = {}
    preview = []

    for _, row in long_df.iterrows():
        accession = norm_text(row.get(accession_col))
        if not accession:
            continue

        source_file = norm_text(row.get(source_file_col)) if source_file_col is not None else ""

        raw_vial_position = norm_text(row.get(vial_position_col)) if vial_position_col is not None else ""
        raw_sample_order = row.get(sample_order_col) if sample_order_col is not None else None

        well = ""
        if raw_vial_position:
            well = normalize_well_label(raw_vial_position)

        if not well and raw_sample_order is not None:
            well = normalize_well_label(raw_sample_order)

        if well:
            lookup[(accession, source_file)] = well
            lookup.setdefault((accession, ""), well)
            if len(preview) < 20:
                preview.append((accession, source_file, raw_vial_position, raw_sample_order, well))

    print("LOOKUP_PREVIEW:")
    for item in preview:
        print(item)

    return lookup


# --- patch_lcms2_slot2_mapping:start ---
HEATMAP_ROWS = ("A", "B", "C", "D", "E", "F", "G", "H")
WELL_RE = re.compile(r"^\s*([A-Ha-h])\s*0?([1-9]|1[0-2])\s*$")
DRAWER_SLOT_RE = re.compile(r"drawer\s*\d+\s*:\s*slot\s*2\s*:\s*(\d{1,2})\s*$", re.IGNORECASE)
SLOT_ONLY_RE = re.compile(r"slot\s*2\s*:\s*(\d{1,2})\s*$", re.IGNORECASE)
PLAIN_VIAL_RE = re.compile(r"^\s*(\d{1,2})\s*$")


def vial_number_to_well(value):
    if value is None:
        return None

    s = str(value).strip()
    if not s:
        return None

    m = PLAIN_VIAL_RE.match(s)
    if not m:
        return None

    vial_num = int(m.group(1))
    if not (1 <= vial_num <= 96):
        return None

    row_idx = (vial_num - 1) // 12
    col_num = ((vial_num - 1) % 12) + 1
    return f"{HEATMAP_ROWS[row_idx]}{col_num}"


def normalize_well_label(value):
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    # Standard A1..H12
    m = WELL_RE.match(text)
    if m:
        return f"{m.group(1).upper()}{int(m.group(2))}"

    # LCMS2 format: Drawer 1:Slot2:1
    m = DRAWER_SLOT_RE.search(text)
    if m:
        return vial_number_to_well(m.group(1))

    # Variant: Slot2:1
    m = SLOT_ONLY_RE.search(text)
    if m:
        return vial_number_to_well(m.group(1))

    # Plain 1..96
    well = vial_number_to_well(text)
    if well:
        return well

    return None


def first_existing_column(df, candidates):
    for col in candidates:
        if col in df.columns:
            return col
    return None


def build_resolved_well_series(df):
    result = pd.Series([None] * len(df), index=df.index, dtype="object")

    related_well_col = first_existing_column(df, [
        "Related Well", "Related well", "related well", "related_well"
    ])
    vial_position_col = first_existing_column(df, [
        "Sample Vial Position", "Vial position", "Vial Position", "Sample vial position"
    ])
    vial_number_col = first_existing_column(df, [
        "Vial number", "Vial Number", "vial number", "vial_number"
    ])

    if related_well_col:
        result = result.where(result.notna(), df[related_well_col].map(normalize_well_label))

    if vial_position_col:
        result = result.where(result.notna(), df[vial_position_col].map(normalize_well_label))

    if vial_number_col:
        result = result.where(result.notna(), df[vial_number_col].map(vial_number_to_well))

    return result
# --- patch_lcms2_slot2_mapping:end ---

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()

    db_path = Path(r".\reviewer_data\lcms_reviewer.db")
    conn = sqlite3.connect(db_path)

    try:
        files = conn.execute("""
            SELECT original_name, stored_path
            FROM uploaded_files
            WHERE run_id = ?
            ORDER BY id
        """, (args.run_id,)).fetchall()

        existing_paths = []
        print("FILES:")
        for original_name, stored_path in files:
            p = Path(stored_path)
            print(f"  {original_name} | EXISTS={p.exists()} | {stored_path}")
            if p.exists():
                existing_paths.append(str(p))

        if not existing_paths:
            raise SystemExit("No uploaded files for this run exist on this machine.")

        discovered = analyzer.discover_excel_files(existing_paths)
        print("DISCOVERED:", discovered)

        long_df = analyzer.build_long_table(discovered)
        print("LONG_DF_ROWS:", len(long_df))
        print("LONG_DF_COLUMNS:", [str(c) for c in long_df.columns])

        lookup = build_position_lookup(long_df)
        print("LOOKUP_SIZE:", len(lookup))

        rows = conn.execute("""
            SELECT id, accession, source_file
            FROM specimens
            WHERE run_id = ?
            ORDER BY id
        """, (args.run_id,)).fetchall()

        updated = 0
        for specimen_id, accession, source_file in rows:
            accession = str(accession or "").strip()
            source_file = str(source_file or "").strip()
            well = lookup.get((accession, source_file)) or lookup.get((accession, ""))
            if well:
                conn.execute(
                    "UPDATE specimens SET well_position = ? WHERE id = ?",
                    (well, specimen_id),
                )
                updated += 1

        conn.commit()

        summary = conn.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN LENGTH(TRIM(COALESCE(well_position, ''))) > 0 THEN 1 ELSE 0 END)
            FROM specimens
            WHERE run_id = ?
        """, (args.run_id,)).fetchone()

        print("UPDATED_ROWS:", updated)
        print("RUN_SUMMARY:", summary)

        preview = conn.execute("""
            SELECT accession, source_file, well_position
            FROM specimens
            WHERE run_id = ?
            ORDER BY id
            LIMIT 20
        """, (args.run_id,)).fetchall()

        print("PREVIEW:")
        for row in preview:
            print(row)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
