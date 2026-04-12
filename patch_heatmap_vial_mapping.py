from pathlib import Path
import re
import shutil

path = Path("web_reviewer.py")
text = path.read_text(encoding="utf-8")
backup = path.with_suffix(".py.bak_vial_mapping")
shutil.copy2(path, backup)

def must_replace(src: str, old: str, new: str, label: str) -> str:
    if old in src:
        return src.replace(old, new, 1)
    if new in src:
        return src
    raise SystemExit(f"Could not find block for {label}")

# 1) Ensure Specimen has well_position
needle = '    source_file: Mapped[str] = mapped_column(String(255), default="", nullable=False)\n'
insert = needle + '    well_position: Mapped[str] = mapped_column(String(32), default="", nullable=False)\n'
if 'well_position: Mapped[str]' not in text:
    if needle not in text:
        raise SystemExit("Could not find Specimen.source_file field to insert well_position.")
    text = text.replace(needle, insert, 1)

# 2) Replace the old heatmap well parser with vial-number-aware logic
old_heatmap_block = '''HEATMAP_ROWS = "ABCDEFGH"
HEATMAP_COLS = list(range(1, 13))
HEATMAP_WELL_RE = re.compile(r"^\\s*([A-Ha-h])\\s*(?:-|\\s*)?([1-9]|1[0-2])\\s*$")


def normalize_well_label(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = HEATMAP_WELL_RE.match(text)
    if not match:
        return ""
    return f"{match.group(1).upper()}{int(match.group(2))}"
'''

new_heatmap_block = '''HEATMAP_ROWS = "ABCDEFGH"
HEATMAP_COLS = list(range(1, 13))
HEATMAP_DIRECT_WELL_RE = re.compile(r"^\\s*([A-Ha-h])\\s*(?:-|\\s*)?([1-9]|1[0-2])\\s*$")
HEATMAP_TRAILING_VIAL_RE = re.compile(r":\\s*(\\d{1,3})\\s*$")
HEATMAP_ENDING_INT_RE = re.compile(r"(\\d{1,3})\\s*$")


def vial_number_to_well(vial_number: int | None) -> str:
    if vial_number is None:
        return ""
    if vial_number < 1 or vial_number > 96:
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
            numeric = int(value)
        except Exception:
            return None
        return numeric if 1 <= numeric <= 96 else None

    text = str(value).strip()
    if not text:
        return None

    match = HEATMAP_TRAILING_VIAL_RE.search(text)
    if match:
        numeric = int(match.group(1))
        return numeric if 1 <= numeric <= 96 else None

    match = HEATMAP_ENDING_INT_RE.search(text)
    if match:
        numeric = int(match.group(1))
        return numeric if 1 <= numeric <= 96 else None

    if text.isdigit():
        numeric = int(text)
        return numeric if 1 <= numeric <= 96 else None

    return None


def normalize_well_label(value: str | None) -> str:
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
'''

text = must_replace(text, old_heatmap_block, new_heatmap_block, "heatmap mapping block")

# 3) Insert helpers to extract/save positions from analyzer output
helper_marker = 'def export_dataframe(df: pd.DataFrame, path: Path) -> None:\n'
helper_block = '''

POSITION_TEXT_HINTS = (
    "sample vial position",
    "vial position",
    "well position",
    "sample position",
)

POSITION_ORDER_HINTS = (
    "sample order",
    "vial number",
    "position number",
)


def _norm_text(value) -> str:
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
    accession_col = lower_map.get("accession")
    source_file_col = lower_map.get("source_file")

    if accession_col is None:
        return {}

    text_cols = [
        col for col in columns
        if any(hint in str(col).strip().lower() for hint in POSITION_TEXT_HINTS)
    ]
    order_cols = [
        col for col in columns
        if any(hint in str(col).strip().lower() for hint in POSITION_ORDER_HINTS)
    ]

    lookup: dict[tuple[str, str], str] = {}

    for _, row in long_df.iterrows():
        accession = _norm_text(row.get(accession_col))
        if not accession:
            continue

        source_file = _norm_text(row.get(source_file_col)) if source_file_col is not None else ""

        well = ""
        for col in text_cols:
            raw = _norm_text(row.get(col))
            if raw:
                well = normalize_well_label(raw)
                if well:
                    break

        if not well:
            for col in order_cols:
                vial_num = coerce_vial_number(row.get(col))
                well = vial_number_to_well(vial_num)
                if well:
                    break

        if well:
            lookup[(accession, source_file)] = well
            lookup.setdefault((accession, ""), well)

    return lookup


def resolve_specimen_well_position(accession: str, row: pd.Series, position_lookup: dict[tuple[str, str], str]) -> str:
    accession = str(accession or "").strip()
    source_file = str(row.get("source_file", "") or "").strip()

    if not accession:
        return ""

    well = position_lookup.get((accession, source_file)) or position_lookup.get((accession, ""))
    if well:
        return well

    direct_candidates = [
        row.get("well_position", ""),
        row.get("Well Position", ""),
        row.get("Sample Vial Position", ""),
        row.get("sample_vial_position", ""),
        row.get("Vial Position", ""),
        row.get("vial_position", ""),
        row.get("Sample Order", ""),
        row.get("sample_order", ""),
    ]

    for candidate in direct_candidates:
        normalized = normalize_well_label(candidate)
        if normalized:
            return normalized

    return ""


'''
if helper_block not in text:
    if helper_marker not in text:
        raise SystemExit("Could not find export_dataframe marker for helper insertion.")
    text = text.replace(helper_marker, helper_block + helper_marker, 1)

# 4) Build lookup right after long_df is created
text = must_replace(
    text,
    '        long_df = analyzer.build_long_table(discovered)\n        wide_df = analyzer.build_wide_table(long_df)\n',
    '        long_df = analyzer.build_long_table(discovered)\n        position_lookup = build_position_lookup(long_df)\n        wide_df = analyzer.build_wide_table(long_df)\n',
    "position lookup initialization",
)

# 5) Save normalized well_position into Specimen during ingest
pattern = re.compile(
    r'            source_file=str\(row\.get\("source_file", ""\) or ""\),\n(?:            well_position=.*?\n)?            batch_name=str\(row\.get\("batch_name", ""\) or ""\),',
    re.S,
)
replacement = '''            source_file=str(row.get("source_file", "") or ""),
            well_position=resolve_specimen_well_position(accession, row, position_lookup),
            batch_name=str(row.get("batch_name", "") or ""),'''
text, count = pattern.subn(replacement, text, count=1)
if count == 0 and replacement not in text:
    raise SystemExit("Could not patch specimen well_position assignment.")

path.write_text(text, encoding="utf-8")
print("Patched web_reviewer.py")
print(f"Backup: {backup.name}")
