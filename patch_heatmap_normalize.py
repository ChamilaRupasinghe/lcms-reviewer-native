from pathlib import Path
import shutil

path = Path("web_reviewer.py")
text = path.read_text(encoding="utf-8")
backup = path.with_suffix(".py.bak_heatmap_normalize")
shutil.copy2(path, backup)

old = '''HEATMAP_WELL_RE = re.compile(r"^\\s*([A-Ha-h])\\s*(?:-|\\s*)?([1-9]|1[0-2])\\s*$")


def normalize_well_label(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = HEATMAP_WELL_RE.match(text)
    if not match:
        return ""
    return f"{match.group(1).upper()}{int(match.group(2))}"
'''

new = '''HEATMAP_WELL_RE = re.compile(r"(?i)\\b([A-H])\\s*(?:-|\\s*)?([1-9]|1[0-2])\\b")


def normalize_well_label(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = HEATMAP_WELL_RE.search(text)
    if not match:
        return ""
    return f"{match.group(1).upper()}{int(match.group(2))}"
'''

if old not in text:
    raise SystemExit("Could not find normalize_well_label block to patch.")

text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")

print("Patched normalize_well_label in web_reviewer.py")
print(f"Backup: {backup.name}")
