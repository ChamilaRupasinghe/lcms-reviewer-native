from pathlib import Path
import sqlite3
import importlib.util
import sys

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "reviewer_data" / "lcms_reviewer.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def load_analyzer_module():
    candidates = [
        BASE / "lcms_parent_metabolite_analyzer.py",
        BASE.parent / "lcms_parent_metabolite_analyzer.py",
        BASE / "bundle" / "lcms_parent_metabolite_analyzer.py",
    ]
    for path in candidates:
        if path.exists():
            spec = importlib.util.spec_from_file_location("lcms_analyzer", path)
            module = importlib.util.module_from_spec(spec)
            if spec.loader is None:
                raise RuntimeError(f"Could not load analyzer from {path}")
            spec.loader.exec_module(module)
            return module, path
    raise FileNotFoundError(
        "Could not find lcms_parent_metabolite_analyzer.py in any expected location:\n"
        + "\n".join(str(p) for p in candidates)
    )

def migrate_schema(conn):
    conn.executescript("""
    PRAGMA foreign_keys = ON;
    PRAGMA journal_mode = WAL;
    PRAGMA synchronous = NORMAL;
    PRAGMA busy_timeout = 5000;

    CREATE TABLE IF NOT EXISTS app_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS analyte_thresholds (
        analyte TEXT PRIMARY KEY CHECK (trim(analyte) <> ''),
        cutoff_value REAL NOT NULL CHECK (cutoff_value >= 0),
        upper_limit_value REAL CHECK (upper_limit_value IS NULL OR upper_limit_value >= cutoff_value),
        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
        display_order INTEGER NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT 'default' CHECK (trim(source) <> ''),
        updated_by TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_thresholds_enabled
        ON analyte_thresholds(enabled, display_order, analyte);

    CREATE TABLE IF NOT EXISTS rule_catalog (
        rule_code TEXT PRIMARY KEY CHECK (trim(rule_code) <> ''),
        title TEXT NOT NULL CHECK (trim(title) <> ''),
        severity TEXT NOT NULL CHECK (severity IN ('red','amber','info')),
        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
        sort_order INTEGER NOT NULL DEFAULT 0,
        analyte_scope TEXT,
        logic_summary TEXT,
        reviewer_guidance TEXT,
        source TEXT NOT NULL DEFAULT 'default' CHECK (trim(source) <> ''),
        updated_by TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_rules_enabled
        ON rule_catalog(enabled, sort_order, rule_code);

    CREATE TABLE IF NOT EXISTS plate_position_map (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        drawer_no INTEGER NOT NULL CHECK (drawer_no >= 1),
        slot_no INTEGER NOT NULL CHECK (slot_no >= 1),
        slot_position INTEGER NOT NULL CHECK (slot_position >= 1),
        well_row TEXT NOT NULL CHECK (well_row IN ('A','B','C','D','E','F','G','H')),
        well_col INTEGER NOT NULL CHECK (well_col BETWEEN 1 AND 12),
        well_label TEXT NOT NULL CHECK (length(well_label) BETWEEN 2 AND 3),
        plate_index INTEGER NOT NULL DEFAULT 1 CHECK (plate_index >= 1),
        source_name TEXT,
        source_path TEXT,
        active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(drawer_no, slot_no, slot_position)
    );

    CREATE INDEX IF NOT EXISTS idx_plate_map_lookup
        ON plate_position_map(drawer_no, slot_no, slot_position, active);

    CREATE TABLE IF NOT EXISTS run_file_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        source_file TEXT NOT NULL CHECK (trim(source_file) <> ''),
        accession TEXT,
        sample_name TEXT,
        sample_order INTEGER,
        sample_vial_position TEXT,
        drawer_no INTEGER,
        slot_no INTEGER,
        slot_position INTEGER,
        well_row TEXT CHECK (well_row IS NULL OR well_row IN ('A','B','C','D','E','F','G','H')),
        well_col INTEGER CHECK (well_col IS NULL OR well_col BETWEEN 1 AND 12),
        well_label TEXT,
        mapping_status TEXT NOT NULL DEFAULT 'unmapped' CHECK (mapping_status IN ('mapped','unmapped','partial','error')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(run_id, source_file, accession)
    );

    CREATE INDEX IF NOT EXISTS idx_run_file_positions_lookup
        ON run_file_positions(run_id, source_file, well_label);

    CREATE INDEX IF NOT EXISTS idx_run_file_positions_accession
        ON run_file_positions(run_id, accession);

    CREATE TABLE IF NOT EXISTS config_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT NOT NULL CHECK (entity_type IN ('threshold','rule','plate_map','setting')),
        entity_key TEXT NOT NULL CHECK (trim(entity_key) <> ''),
        action TEXT NOT NULL CHECK (action IN ('insert','update','reset','import')),
        old_value_json TEXT,
        new_value_json TEXT,
        changed_by TEXT,
        changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_config_audit_entity
        ON config_audit_log(entity_type, entity_key, changed_at);
    """)

def seed_meta(conn):
    conn.executemany(
        "INSERT OR IGNORE INTO app_meta (key, value) VALUES (?, ?)",
        [
            ("schema_version", "1"),
            ("schema_name", "runtime_config_heatmap_base"),
            ("seed_source", "analyzer_defaults_20260409"),
            ("upper_limit_seed_note", "Only explicitly confirmed upper limits are seeded here; import the full upper-limit table later."),
        ],
    )

def seed_thresholds(conn, analyzer):
    cutoffs = dict(getattr(analyzer, "CUTOFFS", {}))

    # Add any explicitly provided defaults not present in analyzer CUTOFFS
    if "Ethyl Sulfate" not in cutoffs:
        cutoffs["Ethyl Sulfate"] = 200.0

    upper_limits = {
        "Amphetamine": 1000.0,
        "Ethyl Sulfate": 200000.0,
    }

    rows = []
    for i, analyte in enumerate(cutoffs.keys(), start=1):
        rows.append((
            analyte,
            float(cutoffs[analyte]),
            upper_limits.get(analyte),
            1,
            i * 10,
            "analyzer_default" if analyte != "Ethyl Sulfate" else "user_provided_default",
        ))

    conn.executemany("""
        INSERT OR IGNORE INTO analyte_thresholds
        (analyte, cutoff_value, upper_limit_value, enabled, display_order, source)
        VALUES (?, ?, ?, ?, ?, ?)
    """, rows)

def seed_rules(conn, analyzer):
    rules = list(getattr(analyzer, "RULE_CATALOG", []))
    rows = []

    for i, rule in enumerate(rules, start=1):
        rows.append((
            rule.get("rule_code"),
            rule.get("title"),
            rule.get("severity"),
            1,
            i * 10,
            None,
            rule.get("logic"),
            rule.get("rationale"),
            "analyzer_default",
        ))

    conn.executemany("""
        INSERT OR IGNORE INTO rule_catalog
        (rule_code, title, severity, enabled, sort_order, analyte_scope, logic_summary, reviewer_guidance, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)

def main():
    analyzer, analyzer_path = load_analyzer_module()

    conn = sqlite3.connect(DB_PATH)
    try:
        migrate_schema(conn)
        seed_meta(conn)
        seed_thresholds(conn, analyzer)
        seed_rules(conn, analyzer)
        conn.commit()

        cur = conn.cursor()
        tables = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        threshold_count = cur.execute("SELECT COUNT(*) FROM analyte_thresholds").fetchone()[0]
        rule_count = cur.execute("SELECT COUNT(*) FROM rule_catalog").fetchone()[0]

        print("Migration applied successfully.")
        print(f"Analyzer source: {analyzer_path}")
        print(f"Database: {DB_PATH}")
        print(f"Tables: {tables}")
        print(f"Threshold rows: {threshold_count}")
        print(f"Rule rows: {rule_count}")

        sample_thresholds = cur.execute("""
            SELECT analyte, cutoff_value, upper_limit_value
            FROM analyte_thresholds
            WHERE analyte IN ('Amphetamine', 'Ethyl Sulfate', 'Methadone')
            ORDER BY analyte
        """).fetchall()
        print(f"Sample thresholds: {sample_thresholds}")

    finally:
        conn.close()

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise


