from pathlib import Path
import shutil

ROOT = Path(".")
DASH = ROOT / "templates" / "dashboard.html"
CSS = ROOT / "static" / "style.css"


def backup_file(path: Path) -> None:
    bak = path.with_name(path.name + ".bak_heatmap_ui_frontend")
    shutil.copy2(path, bak)
    print(f"Backup created: {bak.name}")


def patch_dashboard() -> None:
    text = DASH.read_text(encoding="utf-8")

    marker = "heatmap-ui-frontend-enhancements"
    if marker in text:
        print("dashboard.html already patched")
        return

    injection = r'''
<script id="heatmap-ui-frontend-enhancements">
document.addEventListener("DOMContentLoaded", () => {
  const runSelect = document.getElementById("heatmap-run-select");
  const analyteSelect = document.getElementById("heatmap-analyte-select");
  const loadButton = document.getElementById("heatmap-load-btn");
  const heatmapGrid = document.getElementById("heatmap-grid");
  const heatmapStatus = document.getElementById("heatmap-status");
  if (!runSelect || !analyteSelect || !loadButton || !heatmapGrid || !heatmapStatus) return;

  let selectedWell = null;
  let chipRefreshToken = 0;

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
    empty: "Empty",
    blue: "Pattern insight"
  }[state] || state || "");

  function ensureShell() {
    const legend = document.querySelector(".heatmap-legend");
    if (legend && !legend.dataset.uiEnhanced) {
      legend.dataset.uiEnhanced = "1";
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
      chipBar.innerHTML = `<div class="heatmap-chip-status">Choose a run to load color-coded analyte chips.</div>`;
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
          <div><span class="label">State</span><span id="detail-state">—</span></div>
          <div><span class="label">Row</span><span id="detail-row">—</span></div>
          <div><span class="label">Column</span><span id="detail-col">—</span></div>
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
  }

  function noteKey(well) {
    return ["heatmapNote", runSelect.value || "", analyteSelect.value || "", well || ""].join(":");
  }

  function loadNote(well) {
    try {
      return JSON.parse(sessionStorage.getItem(noteKey(well)) || "{}");
    } catch {
      return {};
    }
  }

  function saveNote(tag, noteText) {
    if (!selectedWell) return;
    sessionStorage.setItem(noteKey(selectedWell.well), JSON.stringify({
      tag: tag || "",
      note: noteText || ""
    }));
  }

  function paintStoredTags() {
    [...heatmapGrid.querySelectorAll(".heatmap-cell")].forEach((cell) => {
      cell.classList.remove("review-tag-red", "review-tag-orange", "review-tag-blue", "review-tag-green");
      const note = loadNote(cell.dataset.well || "");
      if (note.tag) cell.classList.add(`review-tag-${note.tag}`);
    });
  }

  function updateDetailPanel(data) {
    const note = loadNote(data?.well || "");
    const setText = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = value || "—";
    };

    setText("detail-well", data?.well || "—");
    setText("detail-accession", data?.accession || "—");
    setText("detail-analyte", analyteSelect.value || "—");
    setText("detail-value", data?.value == null ? "—" : fmt(data.value));
    setText("detail-state", reviewLabel(data?.state));
    setText("detail-row", data?.row || "—");
    setText("detail-col", data?.col || "—");
    setText("detail-source", data?.source_file || "—");

    const box = document.getElementById("heatmap-review-note");
    if (box) box.value = note.note || "";

    document.querySelectorAll(".review-tag-btn").forEach((btn) => {
      btn.classList.toggle("is-active", (btn.dataset.reviewTag || "") === (note.tag || ""));
    });
  }

  function clearFocus() {
    selectedWell = null;
    [...heatmapGrid.querySelectorAll(".heatmap-cell")].forEach((cell) => {
      cell.classList.remove("is-selected", "is-related", "is-dimmed");
    });
    updateDetailPanel(null);
  }

  function isRelated(a, b) {
    if (!a || !b || a.well === b.well) return false;
    return (
      (a.row && b.row && a.row === b.row) ||
      (a.col && b.col && a.col === b.col) ||
      (a.state && b.state && a.state === b.state && a.state !== "empty") ||
      (a.source_file && b.source_file && a.source_file === b.source_file)
    );
  }

  function applyFocus(meta) {
    selectedWell = meta;
    [...heatmapGrid.querySelectorAll(".heatmap-cell")].forEach((cell) => {
      const current = {
        well: cell.dataset.well || "",
        row: cell.dataset.row || "",
        col: cell.dataset.col || "",
        state: cell.dataset.state || "",
        source_file: cell.dataset.sourceFile || ""
      };
      cell.classList.remove("is-selected", "is-related", "is-dimmed");
      if (current.well === meta.well) {
        cell.classList.add("is-selected");
      } else if (isRelated(meta, current)) {
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
        const activeTag = document.querySelector(".review-tag-btn.is-active")?.dataset.reviewTag || "";
        saveNote(activeTag, noteBox.value);
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
        const noteText = document.getElementById("heatmap-review-note")?.value || "";
        saveNote(btn.dataset.reviewTag || "", noteText);
        paintStoredTags();
      });
    });
  }

  function classifyFromCells(cells) {
    const states = (cells || []).map((c) => c.state || "empty");
    if (states.includes("red")) return "red";
    if (states.includes("orange")) return "orange";
    if (states.includes("green")) return "green";
    if (states.includes("low")) return "low";
    return "empty";
  }

  function enhanceRenderedGrid() {
    [...heatmapGrid.querySelectorAll(".heatmap-cell")].forEach((cell) => {
      const well = (cell.querySelector(".cell-well")?.textContent || "").trim();
      const valueNode = cell.querySelector(".cell-value");
      const accessionNode = cell.querySelector(".cell-accession");
      const rawValue = valueNode ? valueNode.textContent.trim() : "";
      const n = Number(rawValue);

      if (valueNode && rawValue && Number.isFinite(n)) {
        valueNode.textContent = n.toFixed(2);
      }

      const classes = [...cell.classList];
      const stateClass = classes.find((name) => name.startsWith("state-")) || "state-empty";
      const state = stateClass.replace("state-", "");

      cell.dataset.well = well;
      cell.dataset.row = well ? well.slice(0, 1) : "";
      cell.dataset.col = well ? well.slice(1) : "";
      cell.dataset.state = state;
      cell.dataset.accession = accessionNode ? accessionNode.textContent.trim() : "";
      cell.dataset.sourceFile = cell.dataset.sourceFile || "";
      cell.dataset.value = Number.isFinite(n) ? String(n) : "";

      if (!cell.dataset.bound) {
        cell.dataset.bound = "1";
        cell.addEventListener("click", () => {
          const meta = {
            well: cell.dataset.well || "",
            row: cell.dataset.row || "",
            col: cell.dataset.col || "",
            state: cell.dataset.state || "",
            accession: cell.dataset.accession || "",
            source_file: cell.dataset.sourceFile || "",
            value: cell.dataset.value ? Number(cell.dataset.value) : null
          };
          if (selectedWell && selectedWell.well === meta.well) {
            clearFocus();
          } else {
            applyFocus(meta);
          }
        });
      }
    });

    bindDetailActions();
    paintStoredTags();
  }

  async function refreshAnalyteChips() {
    const token = ++chipRefreshToken;
    const chipBar = document.getElementById("heatmap-analyte-chip-bar");
    if (!chipBar) return;

    const runId = runSelect.value;
    if (!runId) {
      chipBar.innerHTML = `<div class="heatmap-chip-status">Choose a run to see analyte review chips.</div>`;
      return;
    }

    chipBar.innerHTML = `<div class="heatmap-chip-status">Loading analyte review chips...</div>`;

    const analyteResp = await fetch(`/api/heatmap/analytes/${encodeURIComponent(runId)}`);
    const analyteData = await analyteResp.json();
    const analytes = analyteData.items || [];

    const results = await Promise.all(
      analytes.map(async (name) => {
        const resp = await fetch(`/api/heatmap/grid?run_id=${encodeURIComponent(runId)}&analyte=${encodeURIComponent(name)}`);
        const payload = await resp.json();
        return {
          analyte: name,
          mapped_count: payload.mapped_count || 0,
          state: classifyFromCells(payload.cells || []),
          message: payload.message || ""
        };
      })
    );

    if (token !== chipRefreshToken) return;

    results.sort((a, b) => {
      const rank = { red: 0, orange: 1, green: 2, low: 3, empty: 4 };
      return (rank[a.state] ?? 99) - (rank[b.state] ?? 99) || b.mapped_count - a.mapped_count || a.analyte.localeCompare(b.analyte);
    });

    chipBar.innerHTML = results.map((item) => `
      <button type="button" class="analyte-summary-chip state-${item.state}" data-analyte="${esc(item.analyte)}" title="${esc(item.message)}">
        <span class="chip-name">${esc(item.analyte)}</span>
        <span class="chip-meta">${item.mapped_count} mapped</span>
      </button>
    `).join("");

    chipBar.querySelectorAll(".analyte-summary-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        const analyte = btn.dataset.analyte || "";
        analyteSelect.disabled = false;
        if (![...analyteSelect.options].some((o) => o.value === analyte)) {
          analyteSelect.appendChild(new Option(analyte, analyte));
        }
        analyteSelect.value = analyte;
        loadButton.click();
      });
    });
  }

  ensureShell();
  enhanceRenderedGrid();

  const observer = new MutationObserver(() => {
    enhanceRenderedGrid();
  });
  observer.observe(heatmapGrid, { childList: true, subtree: true });

  runSelect.addEventListener("change", () => {
    clearFocus();
    refreshAnalyteChips().catch(console.error);
  });

  loadButton.addEventListener("click", () => {
    setTimeout(() => {
      clearFocus();
      enhanceRenderedGrid();
    }, 120);
  });

  refreshAnalyteChips().catch(console.error);
});
</script>
'''
    if "</body>" in text:
        text = text.replace("</body>", injection + "\n</body>", 1)
    else:
        text += "\n" + injection + "\n"

    DASH.write_text(text, encoding="utf-8")
    print("Patched dashboard.html")


def patch_css() -> None:
    text = CSS.read_text(encoding="utf-8")

    marker = "heatmap-ui-frontend-enhancements"
    if marker in text:
        print("style.css already patched")
        return

    addition = r'''
/* heatmap-ui-frontend-enhancements */
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

.heatmap-detail-panel {
  margin-top: 16px;
  padding: 16px;
  border-radius: 16px;
  border: 1px solid rgba(51, 65, 85, 0.9);
  background: rgba(15, 23, 42, 0.88);
}

.heatmap-detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.heatmap-detail-header h4 {
  margin: 0;
}

.ghost-btn,
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
'''
    text += "\n" + addition + "\n"
    CSS.write_text(text, encoding="utf-8")
    print("Patched style.css")


def main() -> None:
    for path in (DASH, CSS):
        if not path.exists():
            raise SystemExit(f"Missing file: {path}")
        backup_file(path)

    patch_dashboard()
    patch_css()
    print("Frontend heatmap UI patch completed.")


if __name__ == "__main__":
    main()
