from pathlib import Path
from datetime import datetime
import shutil
import re
import sys

ROOT = Path(__file__).resolve().parent
WEB_REVIEWER = ROOT / "web_reviewer.py"
BACKFILL = ROOT / "backfill_well_positions.py"


WEB_BLOCK = r'''
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
        row = m.group(1).upper()
        col = int(m.group(2))
        return f"{row}{col}"

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
# --- patch_lcms2_slot2_mapping:end ---
'''.lstrip("\n")


BACKFILL_BLOCK = r'''
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
'''.lstrip("\n")


def backup_file(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak_lcms2_slot2_mapping_{timestamp}")
    shutil.copy2(path, backup)
    return backup


def ensure_imports(text: str, filename: str) -> str:
    if "import re" not in text and "from re import" not in text:
        text = "import re\n" + text

    if filename == "backfill_well_positions.py":
        if "import pandas as pd" not in text and "from pandas import" not in text:
            text = "import pandas as pd\n" + text

    return text


def patch_web_reviewer(text: str) -> tuple[str, list[str]]:
    actions = []

    if "patch_lcms2_slot2_mapping:start" in text:
        actions.append("web_reviewer.py already contains LCMS2 patch block")
        return text, actions

    text = ensure_imports(text, "web_reviewer.py")

    anchor_patterns = [
        r'(?m)^def heatmap_state\s*\(',
        r'(?m)^def build_empty_heatmap_cells\s*\(',
        r'(?m)^def build_heatmap_payload\s*\(',
    ]

    for pat in anchor_patterns:
        m = re.search(pat, text)
        if m:
            idx = m.start()
            text = text[:idx] + WEB_BLOCK + "\n" + text[idx:]
            actions.append("Inserted LCMS2 normalize block into web_reviewer.py")
            return text, actions

    raise RuntimeError("Could not find insertion anchor in web_reviewer.py")


def patch_backfill(text: str) -> tuple[str, list[str]]:
    actions = []

    if "patch_lcms2_slot2_mapping:start" in text:
        actions.append("backfill_well_positions.py already contains LCMS2 patch block")
        return text, actions

    text = ensure_imports(text, "backfill_well_positions.py")

    # Insert helper block before main or before __main__ guard
    anchor_patterns = [
        r'(?m)^def main\s*\(',
        r'(?m)^if __name__ == [\'"]__main__[\'"]\s*:',
    ]

    inserted = False
    for pat in anchor_patterns:
        m = re.search(pat, text)
        if m:
            idx = m.start()
            text = text[:idx] + BACKFILL_BLOCK + "\n" + text[idx:]
            actions.append("Inserted LCMS2 resolve block into backfill_well_positions.py")
            inserted = True
            break

    if not inserted:
        raise RuntimeError("Could not find insertion anchor in backfill_well_positions.py")

    # Surgical replacements for common well-position assignments
    replacements = [
        (
            r'(?m)^(\s*)(df|lookup_df)\[\s*[\'"]resolved_well_position[\'"]\s*\]\s*=\s*.*$',
            r'\1\2["resolved_well_position"] = build_resolved_well_series(\2)',
            "Replaced resolved_well_position assignment with build_resolved_well_series(...)",
        ),
        (
            r'(?m)^(\s*)(df|lookup_df)\[\s*[\'"]well_position[\'"]\s*\]\s*=\s*.*normalize_well_label.*$',
            r'\1\2["well_position"] = build_resolved_well_series(\2)',
            "Replaced well_position normalize assignment with build_resolved_well_series(...)",
        ),
        (
            r'(?m)^(\s*)(df|lookup_df)\[\s*[\'"]well_position[\'"]\s*\]\s*=\s*.*Sample Vial Position.*$',
            r'\1\2["well_position"] = build_resolved_well_series(\2)',
            "Replaced direct Sample Vial Position assignment with build_resolved_well_series(...)",
        ),
    ]

    for pattern, repl, label in replacements:
        new_text, count = re.subn(pattern, repl, text)
        if count > 0:
            text = new_text
            actions.append(f"{label} [{count}]")

    return text, actions


def patch_file(path: Path, patcher):
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    original = path.read_text(encoding="utf-8")
    updated, actions = patcher(original)

    if updated == original:
        print(f"[SKIP] {path.name}: no changes needed")
        for a in actions:
            print(f"       - {a}")
        return

    backup = backup_file(path)
    path.write_text(updated, encoding="utf-8", newline="\n")

    print(f"[OK] Patched {path.name}")
    print(f"     Backup: {backup.name}")
    for a in actions:
        print(f"     - {a}")


def main():
    try:
        patch_file(WEB_REVIEWER, patch_web_reviewer)
        patch_file(BACKFILL, patch_backfill)
        print("\nDone.")
        print("Next step: py_compile both files, then run backfill for the LCMS2 run(s).")
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
