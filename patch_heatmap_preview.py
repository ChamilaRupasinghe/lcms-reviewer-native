from pathlib import Path
import shutil
import sys

ROOT = Path(".")
WEB = ROOT / "web_reviewer.py"
DASH = ROOT / "templates" / "dashboard.html"
CSS = ROOT / "static" / "style.css"

for path in (WEB, DASH, CSS):
    if not path.exists():
        raise SystemExit(f"Missing required file: {path.resolve()}")

def backup_file(path: Path):
    backup = path.with_name(path.name + ".bak_heatmap_preview")
    shutil.copy2(path, backup)
    return backup

def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Patch failed: could not find block for {label}")
    return text.replace(old, new, 1)

# ------------------------------------------------------------------
# Patch web_reviewer.py
# ------------------------------------------------------------------
web_text = WEB.read_text(encoding="utf-8").replace("\r\n", "\n")
backup_file(WEB)

# 1) import jsonify
web_text = replace_once(
    web_text,
    'from flask import Flask, flash, redirect, render_template, request, send_file, url_for\n',
    'from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, url_for\n',
    "Flask jsonify import",
)

# 2) add RuntimeAnalyteThreshold model before create_engine_and_session
runtime_model_block = '''
class RuntimeAnalyteThreshold(Base):
    __tablename__ = "analyte_thresholds"

    analyte: Mapped[str] = mapped_column(String(120), primary_key=True)
    cutoff_value: Mapped[float] = mapped_column(Float, nullable=False)
    upper_limit_value: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="default", nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


'''
if 'class RuntimeAnalyteThreshold(Base):' not in web_text:
    anchor = 'def create_engine_and_session() -> tuple:\n'
    if anchor not in web_text:
        raise RuntimeError("Patch failed: could not find create_engine_and_session anchor")
    web_text = web_text.replace(anchor, runtime_model_block + anchor, 1)

# 3) insert heatmap helpers before export_dataframe
heatmap_helpers = '''
HEATMAP_ROWS = "ABCDEFGH"
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


def get_runtime_cutoff(session, analyte: str) -> float | None:
    row = session.get(RuntimeAnalyteThreshold, analyte)
    if row and row.enabled and row.cutoff_value is not None:
        return float(row.cutoff_value)
    cutoff = analyzer.CUTOFFS.get(analyte)
    return float(cutoff) if cutoff is not None else None


def heatmap_state(value: float | None, cutoff: float | None) -> str:
    if value is None:
        return "empty"
    if cutoff is None or cutoff <= 0:
        return "filled"
    ratio = value / cutoff
    if ratio >= 1.5:
        return "red"
    if ratio >= 1.0:
        return "orange"
    if ratio >= 0.5:
        return "green"
    return "low"


def build_empty_heatmap_cells() -> list[dict]:
    cells = []
    for row in HEATMAP_ROWS:
        for col in HEATMAP_COLS:
            cells.append(
                {
                    "well": f"{row}{col}",
                    "row": row,
                    "col": col,
                    "accession": "",
                    "value": None,
                    "state": "empty",
                    "instrument": "",
                    "source_file": "",
                }
            )
    return cells


def build_heatmap_payload(session, run_id: int, analyte: str) -> dict:
    cutoff = get_runtime_cutoff(session, analyte)
    cells = {cell["well"]: cell for cell in build_empty_heatmap_cells()}

    stmt = (
        select(Specimen, AnalyteResult)
        .join(AnalyteResult, AnalyteResult.specimen_id == Specimen.id)
        .where(Specimen.run_id == run_id, AnalyteResult.analyte == analyte)
    )
    rows = session.execute(stmt).all()

    mapped_count = 0
    for specimen, analyte_result in rows:
        well = normalize_well_label(specimen.well_position)
        if not well or well not in cells:
            continue
        mapped_count += 1
        value = safe_num(analyte_result.value)
        cells[well].update(
            {
                "accession": specimen.accession,
                "value": value,
                "state": heatmap_state(value, cutoff),
                "instrument": specimen.instrument or "",
                "source_file": specimen.source_file or "",
            }
        )

    return {
        "run_id": run_id,
        "analyte": analyte,
        "cutoff": cutoff,
        "mapped_count": mapped_count,
        "cells": [cells[f"{row}{col}"] for row in HEATMAP_ROWS for col in HEATMAP_COLS],
        "message": (
            "No mapped well positions were found for this run. This preview heatmap needs A1-H12 well_position values to color cells."
            if mapped_count == 0
            else f"Loaded {mapped_count} mapped well(s) for {analyte}."
        ),
    }


'''
if 'HEATMAP_ROWS = "ABCDEFGH"' not in web_text:
    anchor = 'def export_dataframe(df: pd.DataFrame, path: Path) -> None:\n'
    if anchor not in web_text:
        raise RuntimeError("Patch failed: could not find export_dataframe anchor")
    web_text = web_text.replace(anchor, heatmap_helpers + anchor, 1)

# 4) insert heatmap routes before /health
heatmap_routes = '''
@app.route("/api/heatmap/analytes/<int:run_id>")
def api_heatmap_analytes(run_id: int):
    session = SessionLocal()
    run = session.get(ReviewRun, run_id)
    if not run:
        return jsonify({"items": [], "error": "Run not found"}), 404

    analytes = session.scalars(
        select(AnalyteResult.analyte)
        .join(Specimen, AnalyteResult.specimen_id == Specimen.id)
        .where(Specimen.run_id == run_id)
        .distinct()
        .order_by(AnalyteResult.analyte.asc())
    ).all()
    return jsonify({"run_id": run_id, "items": analytes})


@app.route("/api/heatmap/grid")
def api_heatmap_grid():
    run_id = request.args.get("run_id", type=int)
    analyte = (request.args.get("analyte") or "").strip()

    if not run_id:
        return jsonify({"error": "Missing run_id"}), 400
    if not analyte:
        return jsonify({"error": "Missing analyte"}), 400

    session = SessionLocal()
    run = session.get(ReviewRun, run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404

    payload = build_heatmap_payload(session, run_id, analyte)
    payload["run_label"] = run.label
    return jsonify(payload)


'''
if '@app.route("/api/heatmap/grid")' not in web_text:
    anchor = '@app.route("/health")\n'
    if anchor not in web_text:
        raise RuntimeError("Patch failed: could not find /health route anchor")
    web_text = web_text.replace(anchor, heatmap_routes + anchor, 1)

WEB.write_text(web_text, encoding="utf-8")

# ------------------------------------------------------------------
# Patch templates/dashboard.html
# ------------------------------------------------------------------
dash_text = DASH.read_text(encoding="utf-8").replace("\r\n", "\n")
backup_file(DASH)

# 1) add dashboard tabs before stat cards
dash_text = replace_once(
    dash_text,
    '<section class="card-grid compact-gap">\n',
    '''<section class="dashboard-tabs">
  <button class="dashboard-tab active" type="button" data-target="dashboard-overview-panel">Overview</button>
  <button class="dashboard-tab" type="button" data-target="dashboard-heatmap-panel">Heatmap</button>
</section>

<div id="dashboard-overview-panel" class="dashboard-tab-panel active">
<section class="card-grid compact-gap">
''',
    "dashboard tab shell",
)

# 2) close overview panel and add heatmap panel before content endblock
dash_text = replace_once(
    dash_text,
    '{% endblock %}\n\n{% block extra_scripts %}\n',
    '''</div>

<section id="dashboard-heatmap-panel" class="panel dashboard-tab-panel">
  <div class="section-head">
    <h2>96-well heatmap preview</h2>
    <span class="pill">First visible version</span>
  </div>
  <p class="muted-copy">This preview tab renders a simple 8×12 plate from saved run data. It uses stored <code>well_position</code> values when available. If a run has no mapped A1-H12 positions yet, the grid will still appear but remain blank.</p>

  {% if recent_runs %}
  <div class="heatmap-toolbar">
    <label>Run
      <select id="heatmap-run-select">
        <option value="">Choose a run</option>
        {% for run in recent_runs %}
          <option value="{{ run.id }}">#{{ run.id }} — {{ run.label }}</option>
        {% endfor %}
      </select>
    </label>

    <label>Analyte
      <select id="heatmap-analyte-select" disabled>
        <option value="">Choose an analyte</option>
      </select>
    </label>

    <button id="heatmap-load-btn" type="button">Load heatmap</button>
  </div>

  <div class="heatmap-legend">
    <span class="legend-chip empty">Empty</span>
    <span class="legend-chip low">&lt; 50% cutoff</span>
    <span class="legend-chip green">≈ 50% cutoff</span>
    <span class="legend-chip orange">At cutoff</span>
    <span class="legend-chip red">High positive</span>
  </div>

  <p id="heatmap-status" class="muted-copy">Choose a run to load analytes.</p>
  <div id="heatmap-grid" class="heatmap-grid"></div>
  {% else %}
  <p class="empty">No runs saved yet. Upload a batch to enable the heatmap preview.</p>
  {% endif %}
</section>

{% endblock %}

{% block extra_scripts %}
''',
    "heatmap panel",
)

# 3) replace existing extra_scripts block with expanded JS
dash_text = replace_once(
    dash_text,
    '''<script>
  bindTableSearch('run-search', 'table tbody tr', 'td');
  bindDataFilter('.filter-chip', '#latest-flag-list .flag-box', 'severity');
</script>
''',
    '''<script>
  bindTableSearch('run-search', 'table tbody tr', 'td');
  bindDataFilter('.filter-chip', '#latest-flag-list .flag-box', 'severity');

  const dashboardTabs = Array.from(document.querySelectorAll('.dashboard-tab'));
  const dashboardPanels = Array.from(document.querySelectorAll('.dashboard-tab-panel'));

  dashboardTabs.forEach((button) => {
    button.addEventListener('click', () => {
      const targetId = button.dataset.target;
      dashboardTabs.forEach((item) => item.classList.remove('active'));
      dashboardPanels.forEach((panel) => panel.classList.remove('active'));
      button.classList.add('active');
      const panel = document.getElementById(targetId);
      if (panel) panel.classList.add('active');
    });
  });

  const runSelect = document.getElementById('heatmap-run-select');
  const analyteSelect = document.getElementById('heatmap-analyte-select');
  const loadButton = document.getElementById('heatmap-load-btn');
  const heatmapGrid = document.getElementById('heatmap-grid');
  const heatmapStatus = document.getElementById('heatmap-status');

  function renderEmptyHeatmapPlaceholder(message) {
    if (!heatmapGrid) return;
    heatmapGrid.innerHTML = '';
    if (heatmapStatus) heatmapStatus.textContent = message || 'No heatmap data loaded.';
  }

  function renderHeatmap(payload) {
    if (!heatmapGrid) return;
    heatmapGrid.innerHTML = '';

    const cells = payload.cells || [];
    cells.forEach((cell) => {
      const el = document.createElement('button');
      el.type = 'button';
      el.className = `heatmap-cell state-${cell.state || 'empty'}`;
      el.innerHTML = `
        <span class="cell-well">${cell.well}</span>
        <span class="cell-value">${cell.value == null ? '' : cell.value}</span>
        <span class="cell-accession">${cell.accession || ''}</span>
      `;
      el.title = [
        cell.well,
        cell.accession || 'No accession',
        cell.value == null ? 'No value' : `Value: ${cell.value}`,
        payload.cutoff == null ? '' : `Cutoff: ${payload.cutoff}`
      ].filter(Boolean).join(' | ');
      heatmapGrid.appendChild(el);
    });

    if (heatmapStatus) {
      const cutoffText = payload.cutoff == null ? 'No cutoff' : `Cutoff ${payload.cutoff}`;
      heatmapStatus.textContent = `${payload.message} ${cutoffText}.`;
    }
  }

  async function loadAnalytesForRun(runId) {
    if (!analyteSelect) return;
    analyteSelect.innerHTML = '<option value="">Loading analytes...</option>';
    analyteSelect.disabled = true;

    if (!runId) {
      analyteSelect.innerHTML = '<option value="">Choose an analyte</option>';
      renderEmptyHeatmapPlaceholder('Choose a run to load analytes.');
      return;
    }

    try {
      const response = await fetch(`/api/heatmap/analytes/${encodeURIComponent(runId)}`);
      const payload = await response.json();
      const items = payload.items || [];

      analyteSelect.innerHTML = '<option value="">Choose an analyte</option>';
      items.forEach((name) => {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        analyteSelect.appendChild(option);
      });
      analyteSelect.disabled = items.length === 0;
      renderEmptyHeatmapPlaceholder(items.length ? 'Choose an analyte, then click Load heatmap.' : 'No analytes found for that run.');
    } catch (error) {
      analyteSelect.innerHTML = '<option value="">Choose an analyte</option>';
      analyteSelect.disabled = true;
      renderEmptyHeatmapPlaceholder('Failed to load analytes.');
    }
  }

  async function loadHeatmap() {
    if (!runSelect || !analyteSelect) return;
    const runId = runSelect.value;
    const analyte = analyteSelect.value;

    if (!runId || !analyte) {
      renderEmptyHeatmapPlaceholder('Choose both a run and an analyte.');
      return;
    }

    if (heatmapStatus) heatmapStatus.textContent = 'Loading heatmap...';

    try {
      const response = await fetch(`/api/heatmap/grid?run_id=${encodeURIComponent(runId)}&analyte=${encodeURIComponent(analyte)}`);
      const payload = await response.json();
      renderHeatmap(payload);
    } catch (error) {
      renderEmptyHeatmapPlaceholder('Failed to load heatmap grid.');
    }
  }

  if (runSelect) {
    runSelect.addEventListener('change', () => loadAnalytesForRun(runSelect.value));
  }
  if (loadButton) {
    loadButton.addEventListener('click', loadHeatmap);
  }
</script>
''',
    "dashboard extra scripts",
)

DASH.write_text(dash_text, encoding="utf-8")

# ------------------------------------------------------------------
# Patch static/style.css
# ------------------------------------------------------------------
css_text = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")
backup_file(CSS)

# 1) include select in input styling
css_text = replace_once(
    css_text,
    'input[type="text"], input[type="file"], input[type="search"] {\n',
    'input[type="text"], input[type="file"], input[type="search"], select {\n',
    "select input styling",
)

# 2) add heatmap styles before media queries
heatmap_css = '''
.dashboard-tabs {
  display: flex;
  gap: 10px;
  margin: 0 0 18px;
  flex-wrap: wrap;
}

.dashboard-tab {
  background: #0f1829;
  border: 1px solid var(--line);
  color: #dbe8ff;
}

.dashboard-tab.active {
  border-color: rgba(108, 180, 255, 0.45);
  background: rgba(108, 180, 255, 0.12);
}

.dashboard-tab-panel {
  display: none;
}

.dashboard-tab-panel.active {
  display: block;
}

.heatmap-toolbar {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  align-items: end;
  margin: 16px 0 14px;
}

.heatmap-legend {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin: 8px 0 14px;
}

.legend-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid var(--line);
  font-size: 0.82rem;
  font-weight: 700;
  background: #0b1322;
}

.legend-chip.empty { color: var(--muted); }
.legend-chip.low { color: #c6d4ef; }
.legend-chip.green { color: var(--green); border-color: rgba(82, 211, 155, 0.35); }
.legend-chip.orange { color: var(--amber); border-color: rgba(255, 202, 102, 0.45); }
.legend-chip.red { color: var(--red); border-color: rgba(255, 132, 132, 0.45); }

.heatmap-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(72px, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.heatmap-cell {
  min-height: 78px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: #0b1322;
  color: var(--text);
  padding: 8px;
  display: grid;
  align-content: start;
  gap: 4px;
  text-align: left;
}

.heatmap-cell .cell-well {
  font-weight: 800;
  font-size: 0.84rem;
}

.heatmap-cell .cell-value {
  font-size: 0.88rem;
  font-weight: 700;
}

.heatmap-cell .cell-accession {
  font-size: 0.72rem;
  color: var(--muted);
  line-height: 1.2;
  word-break: break-word;
}

.heatmap-cell.state-empty {
  opacity: 0.72;
}

.heatmap-cell.state-low {
  border-color: rgba(198, 212, 239, 0.22);
  background: rgba(198, 212, 239, 0.05);
}

.heatmap-cell.state-green {
  border-color: rgba(82, 211, 155, 0.45);
  background: rgba(82, 211, 155, 0.12);
}

.heatmap-cell.state-orange {
  border-color: rgba(255, 202, 102, 0.45);
  background: rgba(255, 202, 102, 0.14);
}

.heatmap-cell.state-red {
  border-color: rgba(255, 132, 132, 0.45);
  background: rgba(255, 132, 132, 0.14);
}

.heatmap-cell.state-filled {
  border-color: rgba(108, 180, 255, 0.35);
  background: rgba(108, 180, 255, 0.10);
}
'''
if '.heatmap-grid {' not in css_text:
    anchor = '.static-card { height: 100%; }\n'
    if anchor not in css_text:
        raise RuntimeError("Patch failed: could not find CSS anchor")
    css_text = css_text.replace(anchor, heatmap_css + '\n' + anchor, 1)

CSS.write_text(css_text, encoding="utf-8")

print("Patched files successfully:")
print(f" - {WEB}")
print(f" - {DASH}")
print(f" - {CSS}")
print("Backups created with suffix .bak_heatmap_preview")
