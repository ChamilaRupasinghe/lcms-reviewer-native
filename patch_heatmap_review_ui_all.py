from pathlib import Path
import shutil

ROOT = Path(".")
WEB = ROOT / "web_reviewer.py"
DASH = ROOT / "templates" / "dashboard.html"
CSS = ROOT / "static" / "style.css"


def backup_file(path: Path) -> None:
    bak = path.with_name(path.name + ".bak_review_ui_all")
    shutil.copy2(path, bak)
    print(f"Backup created: {bak.name}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Could not find patch anchor for {label}")
    return text.replace(old, new, 1)


def patch_web_reviewer() -> None:
    text = WEB.read_text(encoding="utf-8")

    if "def get_effective_threshold_rows(session) -> list[dict]:" not in text:
        anchor = '''def get_effective_rule_lookup(session) -> dict[str, dict]:
    return {item["rule_code"]: item for item in get_effective_rule_catalog(session)}


'''
        insert = '''def get_effective_threshold_rows(session) -> list[dict]:
    runtime_rows = session.scalars(
        select(RuntimeAnalyteThreshold).order_by(RuntimeAnalyteThreshold.display_order.asc(), RuntimeAnalyteThreshold.analyte.asc())
    ).all()
    runtime_map = {row.analyte: row for row in runtime_rows}
    analyte_names = sorted(set(analyzer.CUTOFFS.keys()) | set(runtime_map.keys()), key=lambda item: str(item).lower())

    items = []
    for idx, analyte_name in enumerate(analyte_names, start=1):
        row = runtime_map.get(analyte_name)
        default_cutoff = analyzer.CUTOFFS.get(analyte_name)
        items.append(
            {
                "analyte": analyte_name,
                "cutoff_value": float(row.cutoff_value) if row and row.cutoff_value is not None else (float(default_cutoff) if default_cutoff is not None else None),
                "upper_limit_value": float(row.upper_limit_value) if row and row.upper_limit_value is not None else None,
                "enabled": int(row.enabled) if row else 1,
                "display_order": int(row.display_order) if row else idx,
                "source": str(row.source) if row and row.source else "default",
                "updated_at": str(row.updated_at) if row and row.updated_at else "",
            }
        )

    items.sort(key=lambda item: (int(item.get("display_order", 0) or 0), str(item.get("analyte", "")).lower()))
    return items


'''
        text = replace_once(text, anchor, anchor + insert, "threshold helper")

    if "def build_heatmap_analyte_summary(session, run_id: int) -> list[dict]:" not in text:
        anchor = '''def export_dataframe(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)


'''
        insert = '''def build_heatmap_analyte_summary(session, run_id: int) -> list[dict]:
    analytes = session.scalars(
        select(AnalyteResult.analyte)
        .join(Specimen, AnalyteResult.specimen_id == Specimen.id)
        .where(Specimen.run_id == run_id)
        .distinct()
        .order_by(AnalyteResult.analyte.asc())
    ).all()

    rank = {"red": 0, "orange": 1, "green": 2, "low": 3, "filled": 3, "empty": 4}
    items = []

    for analyte_name in analytes:
        payload = build_heatmap_payload(session, run_id, analyte_name)
        counts = {"red": 0, "orange": 0, "green": 0, "low": 0, "filled": 0, "empty": 0}
        max_value = None

        for cell in payload.get("cells", []):
            state = str(cell.get("state") or "empty")
            counts[state] = counts.get(state, 0) + 1
            value = safe_num(cell.get("value"))
            if value is not None and (max_value is None or value > max_value):
                max_value = value

        review_class = (
            "red"
            if counts.get("red", 0)
            else "orange"
            if counts.get("orange", 0)
            else "green"
            if counts.get("green", 0)
            else "low"
            if payload.get("mapped_count", 0)
            else "empty"
        )

        cutoff = payload.get("cutoff")
        max_ratio = (max_value / cutoff) if (max_value is not None and cutoff not in (None, 0)) else None

        items.append(
            {
                "analyte": analyte_name,
                "mapped_count": int(payload.get("mapped_count", 0) or 0),
                "cutoff": cutoff,
                "review_class": review_class,
                "counts": counts,
                "max_value": max_value,
                "max_ratio": max_ratio,
                "message": payload.get("message", ""),
            }
        )

    items.sort(key=lambda item: (rank.get(item["review_class"], 99), -item["mapped_count"], item["analyte"].lower()))
    return items


'''
        text = replace_once(text, anchor, insert + anchor, "analyte summary helper")

    if "runtime_thresholds=get_effective_threshold_rows(session)" not in text:
        old = '''        rule_catalog=effective_rule_catalog,
        instrument_summary=instrument_summary,
'''
        new = '''        rule_catalog=effective_rule_catalog,
        runtime_thresholds=get_effective_threshold_rows(session),
        instrument_summary=instrument_summary,
'''
        text = replace_once(text, old, new, "dashboard context")

    if '@app.route("/api/heatmap/analyte-summary/<int:run_id>")' not in text:
        anchor = '''@app.route("/api/heatmap/grid")
def api_heatmap_grid():
'''
        insert = '''@app.route("/api/heatmap/analyte-summary/<int:run_id>")
def api_heatmap_analyte_summary(run_id: int):
    session = SessionLocal()
    run = session.get(ReviewRun, run_id)
    if not run:
        return jsonify({"items": [], "error": "Run not found"}), 404
    return jsonify({"run_id": run_id, "items": build_heatmap_analyte_summary(session, run_id)})


@app.route("/api/settings/thresholds", methods=["POST"])
def api_save_thresholds():
    session = SessionLocal()
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows") or []
    saved = 0

    for idx, item in enumerate(rows, start=1):
        analyte_name = str(item.get("analyte") or "").strip()
        if not analyte_name:
            continue

        cutoff_value = safe_num(item.get("cutoff_value"))
        default_cutoff = analyzer.CUTOFFS.get(analyte_name)
        if cutoff_value is None and default_cutoff is not None:
            cutoff_value = float(default_cutoff)
        if cutoff_value is None:
            continue

        upper_limit_value = safe_num(item.get("upper_limit_value"))
        enabled = 0 if str(item.get("enabled", 1)).strip().lower() in {"0", "false", "no", "off"} else 1
        display_order = int(item.get("display_order", idx) or idx)

        row = session.get(RuntimeAnalyteThreshold, analyte_name)
        if not row:
            row = RuntimeAnalyteThreshold(
                analyte=analyte_name,
                cutoff_value=float(cutoff_value),
                upper_limit_value=upper_limit_value,
                enabled=enabled,
                display_order=display_order,
                source="dashboard",
                updated_by="dashboard",
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(row)
        else:
            row.cutoff_value = float(cutoff_value)
            row.upper_limit_value = upper_limit_value
            row.enabled = enabled
            row.display_order = display_order
            row.source = "dashboard"
            row.updated_by = "dashboard"
            row.updated_at = datetime.now(timezone.utc).isoformat()
        saved += 1

    session.commit()
    return jsonify({"ok": True, "saved": saved, "rows": get_effective_threshold_rows(session)})


@app.route("/api/settings/rules", methods=["POST"])
def api_save_rules():
    session = SessionLocal()
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows") or []
    saved = 0

    for idx, item in enumerate(rows, start=1):
        rule_code = str(item.get("rule_code") or "").strip()
        title = str(item.get("title") or "").strip()
        if not rule_code or not title:
            continue

        severity = str(item.get("severity") or "amber").strip().lower()
        if severity not in {"red", "amber", "green", "blue"}:
            severity = "amber"

        enabled = 0 if str(item.get("enabled", 1)).strip().lower() in {"0", "false", "no", "off"} else 1
        sort_order = int(item.get("sort_order", idx) or idx)

        row = session.get(RuntimeRuleCatalog, rule_code)
        if not row:
            row = RuntimeRuleCatalog(
                rule_code=rule_code,
                title=title,
                severity=severity,
                enabled=enabled,
                sort_order=sort_order,
                analyte_scope=str(item.get("analyte_scope") or ""),
                logic_summary=str(item.get("logic_summary") or ""),
                reviewer_guidance=str(item.get("reviewer_guidance") or ""),
                source="dashboard",
                updated_by="dashboard",
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(row)
        else:
            row.title = title
            row.severity = severity
            row.enabled = enabled
            row.sort_order = sort_order
            row.analyte_scope = str(item.get("analyte_scope") or "")
            row.logic_summary = str(item.get("logic_summary") or "")
            row.reviewer_guidance = str(item.get("reviewer_guidance") or "")
            row.source = "dashboard"
            row.updated_by = "dashboard"
            row.updated_at = datetime.now(timezone.utc).isoformat()
        saved += 1

    session.commit()
    return jsonify({"ok": True, "saved": saved, "rows": get_effective_rule_catalog(session)})


'''
        text = replace_once(text, anchor, insert + anchor, "api routes")

    WEB.write_text(text, encoding="utf-8")
    print("Patched web_reviewer.py")


def patch_dashboard_html() -> None:
    text = DASH.read_text(encoding="utf-8")

    if 'id="dashboard-settings-data"' in text:
        print("dashboard.html already enhanced")
        return

    injection = '''
<script id="dashboard-settings-data" type="application/json">{{ {"runtime_thresholds": runtime_thresholds, "rule_catalog": rule_catalog}|tojson }}</script>
<script id="heatmap-review-enhancements">
document.addEventListener("DOMContentLoaded", () => {
  const runSelect = document.getElementById("heatmap-run-select");
  const analyteSelect = document.getElementById("heatmap-analyte-select");
  const loadButton = document.getElementById("heatmap-load-btn");
  const heatmapGrid = document.getElementById("heatmap-grid");
  const heatmapStatus = document.getElementById("heatmap-status");
  if (!runSelect || !analyteSelect || !loadButton || !heatmapGrid || !heatmapStatus) return;

  let lastPayload = null;
  let selectedWell = null;

  const esc = (value) => String(value == null ? "" : value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

  const fmt = (value) => {
    if (value === null || value === undefined || value === "") return "";
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(2) : String(value);
  };

  const reviewLabel = (state) => ({
    red: "Immediate review",
    orange: "Review recommended",
    green: "Within practical expectations",
    low: "Detected / below review threshold",
    blue: "Pattern insight",
    empty: "Empty"
  }[state] || state || "");

  const getConfig = () => {
    const node = document.getElementById("dashboard-settings-data");
    if (!node) return { runtime_thresholds: [], rule_catalog: [] };
    try { return JSON.parse(node.textContent || "{}"); }
    catch { return { runtime_thresholds: [], rule_catalog: [] }; }
  };

  function ensureShell() {
    const legend = document.querySelector(".heatmap-legend");
    if (legend && !legend.dataset.enhanced) {
      legend.dataset.enhanced = "1";
      legend.innerHTML = `
        <span class="review-chip state-empty">Empty</span>
        <span class="review-chip state-low">Below 50% cutoff</span>
        <span class="review-chip state-green">Within practical expectations</span>
        <span class="review-chip state-orange">Review recommended</span>
        <span class="review-chip state-red">Immediate review</span>
        <span class="review-chip state-blue">Pattern insight / related</span>
      `;
    }

    if (!document.getElementById("heatmap-analyte-chip-bar")) {
      const chipBar = document.createElement("div");
      chipBar.id = "heatmap-analyte-chip-bar";
      chipBar.className = "heatmap-analyte-chip-bar";
      chipBar.innerHTML = '<div class="heatmap-chip-status">Click a color-coded analyte chip to load that heatmap.</div>';
      heatmapStatus.insertAdjacentElement("afterend", chipBar);
    }

    if (!document.getElementById("heatmap-detail-panel")) {
      const panel = document.createElement("div");
      panel.id = "heatmap-detail-panel";
      panel.className = "heatmap-detail-panel";
      panel.innerHTML = `
        <div class="heatmap-detail-header">
          <h4>Selected well</h4>
          <button type="button" class="ghost-btn" id="heatmap-clear-focus-btn">Clear focus</button>
        </div>
        <div class="heatmap-detail-grid">
          <div><span class="label">Well</span><span id="detail-well">—</span></div>
          <div><span class="label">Accession</span><span id="detail-accession">—</span></div>
          <div><span class="label">Analyte</span><span id="detail-analyte">—</span></div>
          <div><span class="label">Value</span><span id="detail-value">—</span></div>
          <div><span class="label">Cutoff</span><span id="detail-cutoff">—</span></div>
          <div><span class="label">State</span><span id="detail-state">—</span></div>
          <div><span class="label">Instrument</span><span id="detail-instrument">—</span></div>
          <div><span class="label">Source file</span><span id="detail-source">—</span></div>
        </div>
        <div class="heatmap-note-shell">
          <div class="label">Review tag</div>
          <div class="heatmap-note-actions">
            <button type="button" class="review-tag-btn state-red" data-review-tag="red">Immediate review</button>
            <button type="button" class="review-tag-btn state-orange" data-review-tag="orange">Review recommended</button>
            <button type="button" class="review-tag-btn state-blue" data-review-tag="blue">Pattern insight</button>
            <button type="button" class="review-tag-btn state-green" data-review-tag="green">Within expectations</button>
            <button type="button" class="review-tag-btn state-empty" data-review-tag="">Clear tag</button>
          </div>
          <div class="label">Reviewer note</div>
          <textarea id="heatmap-review-note" rows="3" placeholder="Type a note for the selected well..."></textarea>
        </div>
      `;
      heatmapGrid.insertAdjacentElement("afterend", panel);
    }

    if (!document.getElementById("dashboard-review-settings")) {
      const settings = document.createElement("section");
      settings.id = "dashboard-review-settings";
      settings.className = "dashboard-review-settings";
      settings.innerHTML = `
        <div class="settings-editor-shell">
          <div class="settings-section-header">
            <h3>Review settings editor</h3>
            <div id="settings-save-status" class="settings-save-status">Edit cutoff values, upper limits, and rule catalog here.</div>
          </div>

          <details class="settings-block" open>
            <summary>Analyte thresholds</summary>
            <div class="settings-table-wrap">
              <table class="settings-table" id="threshold-editor-table">
                <thead>
                  <tr>
                    <th>Analyte</th>
                    <th>Cutoff</th>
                    <th>Upper limit</th>
                    <th>Enabled</th>
                    <th>Order</th>
                  </tr>
                </thead>
                <tbody></tbody>
              </table>
            </div>
            <div class="settings-actions">
              <button type="button" class="primary-btn" id="save-thresholds-btn">Save thresholds</button>
            </div>
          </details>

          <details class="settings-block">
            <summary>Rule catalog</summary>
            <div class="settings-table-wrap">
              <table class="settings-table" id="rule-editor-table">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Title</th>
                    <th>Severity</th>
                    <th>Enabled</th>
                    <th>Order</th>
                    <th>Analyte scope</th>
                    <th>Logic summary</th>
                    <th>Reviewer guidance</th>
                  </tr>
                </thead>
                <tbody></tbody>
              </table>
            </div>
            <div class="settings-actions">
              <button type="button" class="primary-btn" id="save-rules-btn">Save rules</button>
            </div>
          </details>
        </div>
      `;
      const detailPanel = document.getElementById("heatmap-detail-panel");
      detailPanel.insertAdjacentElement("afterend", settings);
    }
  }

  const noteKey = (well) => ["heatmapNote", runSelect.value || "", analyteSelect.value || "", well || ""].join(":");

  const loadNote = (well) => {
    try { return JSON.parse(sessionStorage.getItem(noteKey(well)) || "{}"); }
    catch { return {}; }
  };

  const saveNote = (tag, noteText) => {
    if (!selectedWell) return;
    sessionStorage.setItem(noteKey(selectedWell.well), JSON.stringify({ tag: tag || "", note: noteText || "" }));
  };

  function paintStoredTags() {
    [...heatmapGrid.querySelectorAll(".heatmap-cell")].forEach((cell) => {
      cell.classList.remove("review-tag-red", "review-tag-orange", "review-tag-blue", "review-tag-green");
      const note = loadNote(cell.dataset.well || "");
      if (note.tag) cell.classList.add(`review-tag-${note.tag}`);
    });
  }

  function updateDetailPanel(cellData) {
    const note = loadNote(cellData?.well || "");
    const setText = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = value || "—";
    };
    setText("detail-well", cellData?.well || "—");
    setText("detail-accession", cellData?.accession || "—");
    setText("detail-analyte", analyteSelect.value || "—");
    setText("detail-value", cellData?.value == null ? "—" : fmt(cellData.value));
    setText("detail-cutoff", lastPayload?.cutoff == null ? "—" : fmt(lastPayload.cutoff));
    setText("detail-state", reviewLabel(cellData?.state));
    setText("detail-instrument", cellData?.instrument || "—");
    setText("detail-source", cellData?.source_file || "—");

    const noteBox = document.getElementById("heatmap-review-note");
    if (noteBox) noteBox.value = note.note || "";

    document.querySelectorAll(".review-tag-btn").forEach((btn) => {
      btn.classList.toggle("is-active", (btn.dataset.reviewTag || "") === (note.tag || ""));
    });
  }

  function relatedTo(selected, candidate) {
    if (!selected || !candidate) return false;
    if (selected.well === candidate.well) return false;
    const sameSource = selected.source_file && candidate.source_file && selected.source_file === candidate.source_file;
    const sameRow = selected.row && candidate.row && selected.row === candidate.row;
    const sameCol = selected.col && candidate.col && selected.col === candidate.col;
    const sameState = selected.state && candidate.state && selected.state === candidate.state && selected.state !== "empty";
    return sameSource || sameRow || sameCol || sameState;
  }

  function clearFocus() {
    selectedWell = null;
    [...heatmapGrid.querySelectorAll(".heatmap-cell")].forEach((cell) => {
      cell.classList.remove("is-selected", "is-related", "is-dimmed");
    });
    updateDetailPanel(null);
  }

  function applyFocus(meta) {
    selectedWell = meta;
    [...heatmapGrid.querySelectorAll(".heatmap-cell")].forEach((cell) => {
      const candidate = {
        well: cell.dataset.well || "",
        row: cell.dataset.row || "",
        col: cell.dataset.col || "",
        state: cell.dataset.state || "",
        source_file: cell.dataset.sourceFile || ""
      };
      cell.classList.remove("is-selected", "is-related", "is-dimmed");
      if (candidate.well === meta.well) {
        cell.classList.add("is-selected");
      } else if (relatedTo(meta, candidate)) {
        cell.classList.add("is-related");
      } else {
        cell.classList.add("is-dimmed");
      }
    });
    updateDetailPanel(meta);
  }

  function bindDetailActions() {
    const clearBtn = document.getElementById("heatmap-clear-focus-btn");
    if (clearBtn && !clearBtn.dataset.bound) {
      clearBtn.dataset.bound = "1";
      clearBtn.addEventListener("click", clearFocus);
    }

    const noteBox = document.getElementById("heatmap-review-note");
    if (noteBox && !noteBox.dataset.bound) {
      noteBox.dataset.bound = "1";
      noteBox.addEventListener("input", () => {
        const tag = document.querySelector(".review-tag-btn.is-active")?.dataset.reviewTag || "";
        saveNote(tag, noteBox.value);
        paintStoredTags();
      });
    }

    document.querySelectorAll(".review-tag-btn").forEach((btn) => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", () => {
        if (!selectedWell) return;
        document.querySelectorAll(".review-tag-btn").forEach((node) => node.classList.remove("is-active"));
        btn.classList.add("is-active");
        saveNote(btn.dataset.reviewTag || "", document.getElementById("heatmap-review-note")?.value || "");
        paintStoredTags();
      });
    });
  }

  function enhanceGrid(payload) {
    lastPayload = payload;
    const lookup = {};
    (payload?.cells || []).forEach((cell) => lookup[cell.well] = cell);

    [...heatmapGrid.querySelectorAll(".heatmap-cell")].forEach((cellEl) => {
      const well = (cellEl.querySelector(".cell-well")?.textContent || "").trim();
      const data = lookup[well] || { well, row: well.slice(0,1), col: well.slice(1), state: "empty" };

      cellEl.dataset.well = data.well || "";
      cellEl.dataset.row = data.row || "";
      cellEl.dataset.col = data.col || "";
      cellEl.dataset.state = data.state || "empty";
      cellEl.dataset.accession = data.accession || "";
      cellEl.dataset.sourceFile = data.source_file || "";
      cellEl.dataset.instrument = data.instrument || "";
      cellEl.dataset.value = data.value == null ? "" : String(data.value);

      const valueNode = cellEl.querySelector(".cell-value");
      if (valueNode) valueNode.textContent = data.value == null ? "" : fmt(data.value);

      cellEl.classList.toggle("has-value", data.value != null);
      cellEl.title = [
        data.well || "",
        data.accession || "",
        data.value == null ? "" : `Value ${fmt(data.value)}`,
        data.source_file || ""
      ].filter(Boolean).join(" • ");

      if (!cellEl.dataset.bound) {
        cellEl.dataset.bound = "1";
        cellEl.addEventListener("click", () => {
          const meta = {
            well: cellEl.dataset.well || "",
            row: cellEl.dataset.row || "",
            col: cellEl.dataset.col || "",
            state: cellEl.dataset.state || "",
            accession: cellEl.dataset.accession || "",
            source_file: cellEl.dataset.sourceFile || "",
            instrument: cellEl.dataset.instrument || "",
            value: cellEl.dataset.value === "" ? null : Number(cellEl.dataset.value)
          };
          if (selectedWell && selectedWell.well === meta.well) clearFocus();
          else applyFocus(meta);
        });
      }
    });

    paintStoredTags();
    bindDetailActions();
  }

  async function fetchGrid(runId, analyteName) {
    const resp = await fetch(`/api/heatmap/grid?run_id=${encodeURIComponent(runId)}&analyte=${encodeURIComponent(analyteName)}`);
    return await resp.json();
  }

  async function loadAnalytes(runId) {
    if (!runId) return;
    const resp = await fetch(`/api/heatmap/analytes/${encodeURIComponent(runId)}`);
    const data = await resp.json();
    const current = analyteSelect.value;
    analyteSelect.innerHTML = "";
    (data.items || []).forEach((item) => {
      analyteSelect.appendChild(new Option(item, item));
    });
    analyteSelect.disabled = !(data.items || []).length;
    if (current && [...analyteSelect.options].some((o) => o.value === current)) analyteSelect.value = current;
  }

  async function loadAnalyteSummary(runId) {
    const bar = document.getElementById("heatmap-analyte-chip-bar");
    if (!bar) return;
    if (!runId) {
      bar.innerHTML = '<div class="heatmap-chip-status">Choose a run to see analyte review chips.</div>';
      return;
    }

    bar.innerHTML = '<div class="heatmap-chip-status">Loading analyte review chips...</div>';
    const resp = await fetch(`/api/heatmap/analyte-summary/${encodeURIComponent(runId)}`);
    const data = await resp.json();
    const items = data.items || [];

    if (!items.length) {
      bar.innerHTML = '<div class="heatmap-chip-status">No analytes found for this run.</div>';
      return;
    }

    bar.innerHTML = items.map((item) => `
      <button type="button" class="analyte-summary-chip state-${item.review_class || "empty"}" data-analyte="${esc(item.analyte)}" title="${esc(item.message || "")}">
        <span class="chip-name">${esc(item.analyte)}</span>
        <span class="chip-meta">${item.mapped_count || 0} mapped</span>
      </button>
    `).join("");

    bar.querySelectorAll(".analyte-summary-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        const analyteName = btn.dataset.analyte || "";
        if (![...analyteSelect.options].some((o) => o.value === analyteName)) {
          analyteSelect.appendChild(new Option(analyteName, analyteName));
        }
        analyteSelect.disabled = false;
        analyteSelect.value = analyteName;
        loadButton.click();
      });
    });
  }

  function renderThresholdTable(rows) {
    const tbody = document.querySelector("#threshold-editor-table tbody");
    if (!tbody) return;
    tbody.innerHTML = (rows || []).map((row) => `
      <tr>
        <td><input type="text" class="settings-input analyte" value="${esc(row.analyte || "")}"></td>
        <td><input type="number" step="0.01" class="settings-input cutoff_value" value="${row.cutoff_value ?? ""}"></td>
        <td><input type="number" step="0.01" class="settings-input upper_limit_value" value="${row.upper_limit_value ?? ""}"></td>
        <td><input type="checkbox" class="settings-check enabled" ${row.enabled ? "checked" : ""}></td>
        <td><input type="number" step="1" class="settings-input display_order" value="${row.display_order ?? ""}"></td>
      </tr>
    `).join("");
  }

  function renderRuleTable(rows) {
    const tbody = document.querySelector("#rule-editor-table tbody");
    if (!tbody) return;
    tbody.innerHTML = (rows || []).map((row) => `
      <tr>
        <td><input type="text" class="settings-input rule_code" value="${esc(row.rule_code || "")}"></td>
        <td><input type="text" class="settings-input title" value="${esc(row.title || "")}"></td>
        <td>
          <select class="settings-input severity">
            <option value="red" ${row.severity === "red" ? "selected" : ""}>red</option>
            <option value="amber" ${row.severity === "amber" ? "selected" : ""}>amber</option>
            <option value="green" ${row.severity === "green" ? "selected" : ""}>green</option>
            <option value="blue" ${row.severity === "blue" ? "selected" : ""}>blue</option>
          </select>
        </td>
        <td><input type="checkbox" class="settings-check enabled" ${row.enabled ? "checked" : ""}></td>
        <td><input type="number" step="1" class="settings-input sort_order" value="${row.sort_order ?? ""}"></td>
        <td><input type="text" class="settings-input analyte_scope" value="${esc(row.analyte_scope || "")}"></td>
        <td><input type="text" class="settings-input logic_summary" value="${esc(row.logic_summary || "")}"></td>
        <td><input type="text" class="settings-input reviewer_guidance" value="${esc(row.reviewer_guidance || "")}"></td>
      </tr>
    `).join("");
  }

  function collectThresholdRows() {
    return [...document.querySelectorAll("#threshold-editor-table tbody tr")].map((tr) => ({
      analyte: tr.querySelector(".analyte")?.value?.trim() || "",
      cutoff_value: tr.querySelector(".cutoff_value")?.value || "",
      upper_limit_value: tr.querySelector(".upper_limit_value")?.value || "",
      enabled: tr.querySelector(".enabled")?.checked ? 1 : 0,
      display_order: tr.querySelector(".display_order")?.value || ""
    })).filter((row) => row.analyte);
  }

  function collectRuleRows() {
    return [...document.querySelectorAll("#rule-editor-table tbody tr")].map((tr) => ({
      rule_code: tr.querySelector(".rule_code")?.value?.trim() || "",
      title: tr.querySelector(".title")?.value?.trim() || "",
      severity: tr.querySelector(".severity")?.value || "amber",
      enabled: tr.querySelector(".enabled")?.checked ? 1 : 0,
      sort_order: tr.querySelector(".sort_order")?.value || "",
      analyte_scope: tr.querySelector(".analyte_scope")?.value || "",
      logic_summary: tr.querySelector(".logic_summary")?.value || "",
      reviewer_guidance: tr.querySelector(".reviewer_guidance")?.value || ""
    })).filter((row) => row.rule_code && row.title);
  }

  async function saveThresholds() {
    const status = document.getElementById("settings-save-status");
    if (status) status.textContent = "Saving thresholds...";
    const resp = await fetch("/api/settings/thresholds", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows: collectThresholdRows() })
    });
    const data = await resp.json();
    renderThresholdTable(data.rows || []);
    if (status) status.textContent = data.ok ? `Saved ${data.saved} threshold row(s).` : "Threshold save failed.";
  }

  async function saveRules() {
    const status = document.getElementById("settings-save-status");
    if (status) status.textContent = "Saving rule catalog...";
    const resp = await fetch("/api/settings/rules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows: collectRuleRows() })
    });
    const data = await resp.json();
    renderRuleTable(data.rows || []);
    if (status) status.textContent = data.ok ? `Saved ${data.saved} rule row(s).` : "Rule save failed.";
  }

  async function refreshHeatmap() {
    const runId = runSelect.value;
    const analyteName = analyteSelect.value;
    if (!runId || !analyteName) return;
    clearFocus();
    const payload = await fetchGrid(runId, analyteName);
    setTimeout(() => enhanceGrid(payload), 80);
  }

  async function init() {
    ensureShell();

    const cfg = getConfig();
    renderThresholdTable(cfg.runtime_thresholds || []);
    renderRuleTable(cfg.rule_catalog || []);

    document.getElementById("save-thresholds-btn")?.addEventListener("click", saveThresholds);
    document.getElementById("save-rules-btn")?.addEventListener("click", saveRules);

    runSelect.addEventListener("change", async () => {
      await loadAnalytes(runSelect.value);
      await loadAnalyteSummary(runSelect.value);
    });

    loadButton.addEventListener("click", refreshHeatmap);

    if (runSelect.value) {
      await loadAnalytes(runSelect.value);
      await loadAnalyteSummary(runSelect.value);
      if (analyteSelect.value) await refreshHeatmap();
    }
  }

  init().catch((err) => console.error("heatmap enhancement init failed", err));
});
</script>
'''
    if "</body>" in text:
        text = text.replace("</body>", injection + "\n</body>", 1)
    else:
        text += "\n" + injection + "\n"

    DASH.write_text(text, encoding="utf-8")
    print("Patched templates/dashboard.html")


def patch_css() -> None:
    text = CSS.read_text(encoding="utf-8")

    if "/* heatmap-review-enhancements */" in text:
        print("style.css already enhanced")
        return

    addition = '''
/* heatmap-review-enhancements */
.review-chip,
.analyte-summary-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.78);
  color: #e2e8f0;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
}

.heatmap-analyte-chip-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 10px 0 14px;
}

.heatmap-chip-status {
  color: #94a3b8;
  font-size: 13px;
}

.review-chip.state-empty,
.analyte-summary-chip.state-empty {
  color: #cbd5e1;
  border-color: #334155;
  background: rgba(15, 23, 42, 0.92);
}

.review-chip.state-low,
.analyte-summary-chip.state-low {
  color: #dbeafe;
  border-color: rgba(96, 165, 250, 0.28);
  background: rgba(30, 41, 59, 0.95);
}

.review-chip.state-green,
.analyte-summary-chip.state-green {
  color: #d1fae5;
  border-color: rgba(16, 185, 129, 0.55);
  background: rgba(5, 46, 22, 0.72);
}

.review-chip.state-orange,
.analyte-summary-chip.state-orange {
  color: #fde68a;
  border-color: rgba(245, 158, 11, 0.64);
  background: rgba(120, 53, 15, 0.72);
}

.review-chip.state-red,
.analyte-summary-chip.state-red {
  color: #fecaca;
  border-color: rgba(248, 113, 113, 0.74);
  background: rgba(127, 29, 29, 0.78);
}

.review-chip.state-blue,
.analyte-summary-chip.state-blue {
  color: #bfdbfe;
  border-color: rgba(96, 165, 250, 0.66);
  background: rgba(30, 64, 175, 0.50);
}

.analyte-summary-chip {
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.12s ease, border-color 0.12s ease;
}

.analyte-summary-chip:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 18px rgba(15, 23, 42, 0.22);
}

.analyte-summary-chip .chip-name {
  font-weight: 800;
}

.analyte-summary-chip .chip-meta {
  opacity: 0.86;
}

.heatmap-cell {
  position: relative;
  transition: opacity 0.15s ease, transform 0.12s ease, box-shadow 0.15s ease, border-color 0.15s ease, filter 0.15s ease;
}

.heatmap-cell .cell-value {
  font-size: 14px;
  font-weight: 800;
  letter-spacing: 0.01em;
}

.heatmap-cell.state-empty {
  background: #0f172a;
  border-color: #22304a;
  color: #8fa4be;
}

.heatmap-cell.state-low {
  background: linear-gradient(180deg, rgba(22, 34, 53, 1), rgba(17, 24, 39, 1));
  border-color: rgba(71, 85, 105, 0.85);
  color: #dbeafe;
}

.heatmap-cell.state-green {
  background: linear-gradient(180deg, rgba(6, 46, 25, 0.95), rgba(6, 95, 70, 0.45));
  border-color: rgba(16, 185, 129, 0.70);
  color: #ecfdf5;
}

.heatmap-cell.state-orange {
  background: linear-gradient(180deg, rgba(120, 53, 15, 0.95), rgba(180, 83, 9, 0.36));
  border-color: rgba(245, 158, 11, 0.78);
  color: #fff7ed;
}

.heatmap-cell.state-red {
  background: linear-gradient(180deg, rgba(127, 29, 29, 0.96), rgba(185, 28, 28, 0.44));
  border-color: rgba(248, 113, 113, 0.88);
  color: #fff1f2;
}

.heatmap-cell.has-value {
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);
}

.heatmap-cell.is-selected {
  border-color: #7dd3fc !important;
  box-shadow: 0 0 0 2px rgba(125, 211, 252, 0.40), 0 0 20px rgba(56, 189, 248, 0.24);
  transform: translateY(-1px) scale(1.01);
  z-index: 2;
}

.heatmap-cell.is-related {
  border-color: rgba(96, 165, 250, 0.84) !important;
  box-shadow: 0 0 0 1px rgba(96, 165, 250, 0.34);
}

.heatmap-cell.is-dimmed {
  opacity: 0.20;
  filter: saturate(0.65);
}

.heatmap-cell.review-tag-red::after,
.heatmap-cell.review-tag-orange::after,
.heatmap-cell.review-tag-blue::after,
.heatmap-cell.review-tag-green::after {
  content: "";
  position: absolute;
  top: 7px;
  right: 7px;
  width: 9px;
  height: 9px;
  border-radius: 999px;
  box-shadow: 0 0 0 2px rgba(15, 23, 42, 0.85);
}

.heatmap-cell.review-tag-red::after { background: #f87171; }
.heatmap-cell.review-tag-orange::after { background: #f59e0b; }
.heatmap-cell.review-tag-blue::after { background: #60a5fa; }
.heatmap-cell.review-tag-green::after { background: #34d399; }

.heatmap-detail-panel,
.dashboard-review-settings {
  margin-top: 16px;
  padding: 16px;
  border-radius: 16px;
  border: 1px solid rgba(51, 65, 85, 0.9);
  background: rgba(15, 23, 42, 0.88);
}

.heatmap-detail-header,
.settings-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.heatmap-detail-header h4,
.settings-section-header h3 {
  margin: 0;
}

.ghost-btn,
.primary-btn,
.review-tag-btn {
  border: 1px solid rgba(71, 85, 105, 0.9);
  border-radius: 10px;
  padding: 8px 12px;
  cursor: pointer;
}

.ghost-btn {
  background: rgba(15, 23, 42, 0.8);
  color: #e2e8f0;
}

.primary-btn {
  background: linear-gradient(180deg, #2563eb, #1d4ed8);
  border-color: rgba(96, 165, 250, 0.6);
  color: white;
  font-weight: 700;
}

.review-tag-btn {
  color: #e2e8f0;
  background: rgba(15, 23, 42, 0.8);
}

.review-tag-btn.is-active {
  box-shadow: 0 0 0 2px rgba(255,255,255,0.18);
}

.review-tag-btn.state-red { border-color: rgba(248, 113, 113, 0.7); }
.review-tag-btn.state-orange { border-color: rgba(245, 158, 11, 0.7); }
.review-tag-btn.state-blue { border-color: rgba(96, 165, 250, 0.7); }
.review-tag-btn.state-green { border-color: rgba(52, 211, 153, 0.7); }
.review-tag-btn.state-empty { border-color: rgba(148, 163, 184, 0.5); }

.heatmap-detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 1fr));
  gap: 12px 16px;
}

.heatmap-detail-grid .label,
.heatmap-note-shell .label {
  display: block;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #94a3b8;
  margin-bottom: 4px;
}

.heatmap-note-shell {
  margin-top: 14px;
}

.heatmap-note-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

#heatmap-review-note {
  width: 100%;
  border-radius: 12px;
  border: 1px solid rgba(71, 85, 105, 0.9);
  background: rgba(2, 6, 23, 0.72);
  color: #e2e8f0;
  padding: 10px 12px;
}

.settings-block {
  margin-top: 14px;
}

.settings-table-wrap {
  overflow-x: auto;
  margin-top: 12px;
}

.settings-table {
  width: 100%;
  border-collapse: collapse;
}

.settings-table th,
.settings-table td {
  border-bottom: 1px solid rgba(51, 65, 85, 0.75);
  padding: 8px;
  vertical-align: top;
}

.settings-table th {
  text-align: left;
  font-size: 12px;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.settings-input,
.settings-table select {
  width: 100%;
  min-width: 110px;
  border-radius: 10px;
  border: 1px solid rgba(71, 85, 105, 0.85);
  background: rgba(2, 6, 23, 0.70);
  color: #e2e8f0;
  padding: 7px 9px;
}

.settings-check {
  transform: scale(1.15);
}

.settings-actions {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

.settings-save-status {
  color: #94a3b8;
  font-size: 13px;
}
'''
    text += "\n" + addition + "\n"
    CSS.write_text(text, encoding="utf-8")
    print("Patched static/style.css")


def main() -> None:
    for path in (WEB, DASH, CSS):
        if not path.exists():
            raise SystemExit(f"Missing file: {path}")
        backup_file(path)

    patch_web_reviewer()
    patch_dashboard_html()
    patch_css()
    print("Patch completed successfully.")


if __name__ == "__main__":
    main()
