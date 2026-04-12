from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parent
PY_FILE = ROOT / "web_reviewer.py"
HTML_FILE = ROOT / "templates" / "dashboard.html"

def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise RuntimeError(f"Could not find block for {label}")

def insert_before(text: str, marker: str, block: str, label: str) -> str:
    if block in text:
        return text
    idx = text.find(marker)
    if idx == -1:
        raise RuntimeError(f"Could not find marker for {label}")
    return text[:idx] + block + text[idx:]

def regex_replace_once(text: str, pattern: str, repl: str, label: str, flags=0) -> str:
    new_text, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count:
        return new_text
    if repl in text:
        return text
    raise RuntimeError(f"Could not regex-patch {label}")

py = PY_FILE.read_text(encoding="utf-8")
html = HTML_FILE.read_text(encoding="utf-8")

shutil.copy2(PY_FILE, PY_FILE.with_suffix(PY_FILE.suffix + ".bak_heatmap_fix"))
shutil.copy2(HTML_FILE, HTML_FILE.with_suffix(HTML_FILE.suffix + ".bak_heatmap_fix"))

# 1) Add well_position to Specimen model
py = replace_once(
    py,
    '    source_file: Mapped[str] = mapped_column(String(255), default="", nullable=False)\n    batch_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)\n',
    '    source_file: Mapped[str] = mapped_column(String(255), default="", nullable=False)\n    well_position: Mapped[str] = mapped_column(String(32), default="", nullable=False)\n    batch_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)\n',
    "Specimen.well_position field",
)

# 2) Persist well_position during specimen creation
py = replace_once(
    py,
    '            source_file=str(row.get("source_file", "") or ""),\n            batch_name=str(row.get("batch_name", "") or ""),\n',
    '''            source_file=str(row.get("source_file", "") or ""),
            well_position=str(
                row.get("well_position", "")
                or row.get("Well Position", "")
                or row.get("Sample Vial Position", "")
                or row.get("sample_vial_position", "")
                or ""
            ),
            batch_name=str(row.get("batch_name", "") or ""),
''',
    "specimen well_position assignment",
)

# 3) Add pretty run label helper
helper_block = '''

def build_heatmap_run_options(recent_runs: list[ReviewRun]) -> list[dict]:
    items: list[dict] = []
    for run in recent_runs:
        file_names = []
        for uploaded in (run.uploaded_files or []):
            name = str(getattr(uploaded, "original_name", "") or "").strip()
            if name:
                file_names.append(name)
        first_file = file_names[0] if file_names else (run.label or f"Run {run.id}")
        file_count = int(run.file_count or len(file_names) or 0)
        accession_count = int(run.accession_count or 0)
        created_text = run.created_at.strftime("%Y-%m-%d %H:%M") if getattr(run, "created_at", None) else ""

        if file_count > 1:
            label = f"#{run.id} — Batch upload ({file_count} files) — first file: {first_file} — {accession_count} accessions"
        else:
            label = f"#{run.id} — {first_file} — {accession_count} accessions"

        if created_text:
            label = f"{label} — {created_text}"

        items.append({
            "id": run.id,
            "label": label,
        })
    return items


'''
py = insert_before(py, '@app.route("/", methods=["GET"])', helper_block, "build_heatmap_run_options helper")

# 4) Dashboard route: build heatmap_runs and pass to template
py = replace_once(
    py,
    '    recent_runs = session.scalars(select(ReviewRun).order_by(ReviewRun.created_at.desc()).limit(12)).all()\n',
    '    recent_runs = session.scalars(select(ReviewRun).order_by(ReviewRun.created_at.desc()).limit(12)).all()\n    heatmap_runs = build_heatmap_run_options(recent_runs)\n',
    "dashboard heatmap_runs assignment",
)

py = replace_once(
    py,
    '        hot_rules=hot_rules,\n        quick_actions=build_quick_actions(recent_runs),\n    )\n',
    '        hot_rules=hot_rules,\n        quick_actions=build_quick_actions(recent_runs),\n        heatmap_runs=heatmap_runs,\n    )\n',
    "dashboard render_template heatmap_runs",
)

# 5) API grid route: return pretty run label too
py = replace_once(
    py,
    '    payload = build_heatmap_payload(session, run_id, analyte)\n    payload["run_label"] = run.label\n    return jsonify(payload)\n',
    '''    payload = build_heatmap_payload(session, run_id, analyte)
    pretty = build_heatmap_run_options([run])
    payload["run_label"] = pretty[0]["label"] if pretty else (run.label or f"Run {run.id}")
    return jsonify(payload)
''',
    "api_heatmap_grid pretty label",
)

# 6) Dashboard HTML: use heatmap_runs instead of recent_runs in the run selector
html = regex_replace_once(
    html,
    r'<select id="heatmap-run-select">.*?</select>',
    '''<select id="heatmap-run-select">
      <option value="">Choose a run...</option>
      {% for item in heatmap_runs %}
      <option value="{{ item.id }}">{{ item.label }}</option>
      {% endfor %}
    </select>''',
    "heatmap run select",
    flags=re.S,
)

PY_FILE.write_text(py, encoding="utf-8")
HTML_FILE.write_text(html, encoding="utf-8")

print("Patched:")
print(" - web_reviewer.py")
print(" - templates\\dashboard.html")
print("Backups:")
print(" - web_reviewer.py.bak_heatmap_fix")
print(" - templates\\dashboard.html.bak_heatmap_fix")
