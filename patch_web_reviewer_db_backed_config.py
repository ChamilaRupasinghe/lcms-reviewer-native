from pathlib import Path
import shutil
import sys

TARGET = Path("web_reviewer.py")
if not TARGET.exists():
    raise SystemExit(f"Could not find {TARGET.resolve()}")

text = TARGET.read_text(encoding="utf-8")
backup = TARGET.with_name("web_reviewer.py.bak_db_backed_config")
shutil.copy2(TARGET, backup)

def replace_once(old: str, new: str, label: str):
    global text
    if old not in text:
        raise RuntimeError(f"Patch failed: could not find block for {label}")
    text = text.replace(old, new, 1)

# ------------------------------------------------------------------
# 1) Add ORM models for runtime DB-backed threshold/rule tables
# ------------------------------------------------------------------
replace_once(
'''class RuleConfig(Base):
    __tablename__ = "rule_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="amber", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    logic: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


def create_engine_and_session() -> tuple:
''',
'''class RuleConfig(Base):
    __tablename__ = "rule_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="amber", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    logic: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


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


class RuntimeRuleCatalog(Base):
    __tablename__ = "rule_catalog"

    rule_code: Mapped[str] = mapped_column(String(120), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="amber", nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    analyte_scope: Mapped[str | None] = mapped_column(Text)
    logic_summary: Mapped[str | None] = mapped_column(Text)
    reviewer_guidance: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(80), default="default", nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


def create_engine_and_session() -> tuple:
''',
"runtime ORM models"
)

# ------------------------------------------------------------------
# 2) Add DB-backed default/effective config helpers
# ------------------------------------------------------------------
replace_once(
'''RULE_LOOKUP = {item["rule_code"]: item for item in analyzer.RULE_CATALOG}


def export_dataframe(df: pd.DataFrame, path: Path) -> None:
''',
'''DEFAULT_CUTOFFS = dict(analyzer.CUTOFFS)
DEFAULT_RULE_CATALOG = [dict(item) for item in analyzer.RULE_CATALOG]
DEFAULT_RULE_LOOKUP = {item["rule_code"]: item for item in DEFAULT_RULE_CATALOG}


def get_effective_cutoffs(session) -> dict[str, float]:
    rows = session.scalars(
        select(RuntimeAnalyteThreshold).order_by(
            RuntimeAnalyteThreshold.display_order.asc(),
            RuntimeAnalyteThreshold.analyte.asc(),
        )
    ).all()
    if not rows:
        return dict(DEFAULT_CUTOFFS)

    cutoff_map = dict(DEFAULT_CUTOFFS)
    for row in rows:
        if row.enabled and row.cutoff_value is not None:
            cutoff_map[row.analyte] = float(row.cutoff_value)
    return cutoff_map


def get_effective_rule_catalog(session) -> list[dict]:
    all_rows = session.scalars(
        select(RuntimeRuleCatalog).order_by(
            RuntimeRuleCatalog.sort_order.asc(),
            RuntimeRuleCatalog.rule_code.asc(),
        )
    ).all()
    if not all_rows:
        return [dict(item) for item in DEFAULT_RULE_CATALOG]

    catalog = []
    for row in all_rows:
        if not row.enabled:
            continue
        catalog.append(
            {
                "rule_code": row.rule_code,
                "severity": row.severity,
                "title": row.title,
                "logic": row.logic_summary or "",
                "rationale": row.reviewer_guidance or "",
            }
        )
    return catalog


def get_effective_rule_lookup(session) -> dict[str, dict]:
    return {item["rule_code"]: item for item in get_effective_rule_catalog(session)}


def positive_with_cutoffs(value, analyte: str, cutoff_map: dict[str, float] | None = None) -> bool:
    numeric = safe_num(value)
    if numeric is None:
        return False
    active_cutoffs = cutoff_map or DEFAULT_CUTOFFS
    cutoff = active_cutoffs.get(analyte)
    return numeric >= cutoff if cutoff is not None else True


def export_dataframe(df: pd.DataFrame, path: Path) -> None:
''',
"effective config helpers"
)

# ------------------------------------------------------------------
# 3) Make friendly_logic DB-aware
# ------------------------------------------------------------------
replace_once(
'''def friendly_logic(rule_code: str) -> str:
    item = RULE_LOOKUP.get(rule_code, {})
    return item.get("logic", "Stored review rule")
''',
'''def friendly_logic(rule_code: str, rule_lookup: dict | None = None) -> str:
    item = (rule_lookup or DEFAULT_RULE_LOOKUP).get(rule_code, {})
    return item.get("logic", "Stored review rule")
''',
"friendly_logic"
)

# ------------------------------------------------------------------
# 4) Make analyte_level_meta use DB-backed cutoffs
# ------------------------------------------------------------------
replace_once(
'''def analyte_level_meta(value: float | None, analyte: str) -> dict:
    cutoff = analyzer.CUTOFFS.get(analyte)
''',
'''def analyte_level_meta(value: float | None, analyte: str, cutoff_map: dict[str, float] | None = None) -> dict:
    cutoff = (cutoff_map or DEFAULT_CUTOFFS).get(analyte)
''',
"analyte_level_meta"
)

# ------------------------------------------------------------------
# 5) Make flag summaries use DB-backed rule lookup
# ------------------------------------------------------------------
replace_once(
'''def build_flag_rule_summary(flags: List[Flag], limit: int = 6) -> List[dict]:
''',
'''def build_flag_rule_summary(flags: List[Flag], rule_lookup: dict | None = None, limit: int = 6) -> List[dict]:
''',
"build_flag_rule_summary signature"
)

replace_once(
'''                "logic": friendly_logic(flag.rule_code),
''',
'''                "logic": friendly_logic(flag.rule_code, rule_lookup),
''',
"build_flag_rule_summary logic"
)

# ------------------------------------------------------------------
# 6) Make specimen analyte rows use DB-backed cutoffs
# ------------------------------------------------------------------
replace_once(
'''def build_specimen_analyte_rows(analytes: List[AnalyteResult]) -> tuple[list[dict], dict, dict]:
''',
'''def build_specimen_analyte_rows(analytes: List[AnalyteResult], cutoff_map: dict[str, float] | None = None) -> tuple[list[dict], dict, dict]:
''',
"build_specimen_analyte_rows signature"
)

replace_once(
'''        meta = analyte_level_meta(item.value, item.analyte)
''',
'''        meta = analyte_level_meta(item.value, item.analyte, cutoff_map=cutoff_map)
''',
"build_specimen_analyte_rows meta"
)

# ------------------------------------------------------------------
# 7) Make suspect-peak cards use DB-backed cutoffs/rules
# ------------------------------------------------------------------
replace_once(
'''def build_suspect_peak_cards(analyte_rows: List[dict], value_map: dict, flags: List[Flag]) -> List[dict]:
''',
'''def build_suspect_peak_cards(
    analyte_rows: List[dict],
    value_map: dict,
    flags: List[Flag],
    rule_lookup: dict | None = None,
    cutoff_map: dict[str, float] | None = None,
) -> List[dict]:
''',
"build_suspect_peak_cards signature"
)

replace_once(
'''    cards = []
    seen = set()
''',
'''    cards = []
    seen = set()
    cutoff_map = cutoff_map or DEFAULT_CUTOFFS
''',
"build_suspect_peak_cards cutoff init"
)

replace_once(
'''                "logic": friendly_logic(flag.rule_code),
''',
'''                "logic": friendly_logic(flag.rule_code, rule_lookup),
''',
"build_suspect_peak_cards flag logic"
)

replace_once(
'''        if p_value is None or not analyzer.positive(p_value, parent):
''',
'''        if p_value is None or not positive_with_cutoffs(p_value, parent, cutoff_map):
''',
"build_suspect_peak_cards parent positive"
)

replace_once(
'''        p_cutoff = analyzer.CUTOFFS.get(parent, 0) or 0
        m_cutoff = analyzer.CUTOFFS.get(metabolite, 0) or 0
''',
'''        p_cutoff = cutoff_map.get(parent, 0) or 0
        m_cutoff = cutoff_map.get(metabolite, 0) or 0
''',
"build_suspect_peak_cards cutoffs"
)

replace_once(
'''        elif scenario["kind"] == "impurity_max" and ratio is not None and m_value is not None and analyzer.positive(m_value, metabolite):
''',
'''        elif scenario["kind"] == "impurity_max" and ratio is not None and m_value is not None and positive_with_cutoffs(m_value, metabolite, cutoff_map):
''',
"build_suspect_peak_cards impurity positive"
)

# ------------------------------------------------------------------
# 8) Replace analyze_saved_files so uploads use runtime DB-backed config
# ------------------------------------------------------------------
replace_once(
'''def analyze_saved_files(saved_paths: List[Path], label: str = "") -> int:
    session = SessionLocal()
    discovered = analyzer.discover_excel_files([str(p) for p in saved_paths])
    if not discovered:
        raise ValueError("No .xlsx files were provided.")

    run_slug = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    output_dir = OUTPUT_ROOT / run_slug
    output_dir.mkdir(parents=True, exist_ok=True)

    long_df = analyzer.build_long_table(discovered)
    wide_df = analyzer.build_wide_table(long_df)
    flags_df = analyzer.apply_rules(wide_df)
    local_refs_df = analyzer.local_reference_stats(wide_df)
    metabolite_only_df = analyzer.expected_metabolite_only_summary(wide_df)
    specimen_df = analyzer.specimen_summary_table(wide_df, flags_df)

    report_path = output_dir / "lcms_parent_metabolite_report.html"
    flags_csv_path = output_dir / "lcms_flags.csv"
    summary_csv_path = output_dir / "lcms_accession_summary.csv"
    local_refs_csv_path = output_dir / "lcms_local_ratio_reference.csv"

    analyzer.render_report(discovered, wide_df, flags_df, local_refs_df, metabolite_only_df, specimen_df, report_path)
    export_dataframe(flags_df, flags_csv_path)
    export_dataframe(specimen_df, summary_csv_path)
    export_dataframe(local_refs_df, local_refs_csv_path)
    export_dataframe(metabolite_only_df, output_dir / "lcms_expected_metabolite_only.csv")

    bundle_base = OUTPUT_ROOT / f"{run_slug}_lcms_reviewer_outputs"
    bundle_zip = shutil.make_archive(str(bundle_base), "zip", root_dir=output_dir)

    run = ReviewRun(
        label=label.strip() or f"Run {run_slug}",
        status="completed",
        file_count=len(discovered),
        accession_count=int(wide_df["Sample Name"].nunique()),
        flagged_accession_count=int(specimen_df[specimen_df["FlagCount"] > 0]["Accession"].nunique()),
        red_count=int((flags_df["Severity"] == "red").sum()) if not flags_df.empty else 0,
        amber_count=int((flags_df["Severity"] == "amber").sum()) if not flags_df.empty else 0,
        upload_folder=str(saved_paths[0].parent),
        output_folder=str(output_dir),
        report_path=str(report_path),
        flags_csv_path=str(flags_csv_path),
        summary_csv_path=str(summary_csv_path),
        local_refs_csv_path=str(local_refs_csv_path),
        bundle_zip_path=str(bundle_zip),
    )
    session.add(run)
    session.flush()

    for file_path in discovered:
        session.add(UploadedFile(run_id=run.id, original_name=file_path.name, stored_path=str(file_path)))

    specimen_map = {}
    analyte_columns = [c for c in wide_df.columns if c not in {"Sample Name", "instrument_id", "source_file", "batch_name", "run_date"}]
    specimen_summary_lookup = {row["Accession"]: row for _, row in specimen_df.iterrows()}

    for _, row in wide_df.iterrows():
        accession = str(row["Sample Name"])
        summary_row = specimen_summary_lookup.get(accession, {})
        specimen = Specimen(
            run_id=run.id,
            accession=accession,
            instrument=str(row.get("instrument_id", "") or ""),
            source_file=str(row.get("source_file", "") or ""),
            batch_name=str(row.get("batch_name", "") or ""),
            run_date_text=str(row.get("run_date", "") or ""),
            flag_count=int(summary_row.get("FlagCount", 0) or 0),
            highest_severity=str(summary_row.get("HighestSeverity", "") or ""),
            positive_analytes=str(summary_row.get("PositiveAnalytes", "") or ""),
        )
        session.add(specimen)
        session.flush()
        specimen_map[accession] = specimen

        analyte_rows = []
        for analyte in analyte_columns:
            value = safe_num(row.get(analyte))
            if value is None:
                continue
            analyte_rows.append(
                AnalyteResult(
                    specimen_id=specimen.id,
                    analyte=analyte,
                    value=value,
                    is_positive=1 if analyzer.positive(value, analyte) else 0,
                )
            )
        session.add_all(analyte_rows)

    if not flags_df.empty:
        for _, row in flags_df.iterrows():
            specimen = specimen_map[str(row["Accession"])]
            session.add(
                Flag(
                    specimen_id=specimen.id,
                    severity=str(row.get("Severity", "") or ""),
                    rule_code=str(row.get("RuleCode", "") or ""),
                    flag_title=str(row.get("FlagTitle", "") or ""),
                    analyte_a=str(row.get("AnalyteA", "") or ""),
                    value_a=safe_num(row.get("ValueA")),
                    analyte_b=str(row.get("AnalyteB", "") or ""),
                    value_b=safe_num(row.get("ValueB")),
                    ratio_name=str(row.get("RatioName", "") or ""),
                    ratio_value=safe_num(row.get("RatioValue")),
                    comment=str(row.get("Comment", "") or ""),
                )
            )

    for _, row in local_refs_df.iterrows():
        session.add(
            LocalRatioReference(
                run_id=run.id,
                pair_label=str(row.get("Pair", "") or ""),
                n_value=int(row.get("N", 0) or 0),
                p05=safe_num(row.get("P05")),
                median=safe_num(row.get("Median")),
                p95=safe_num(row.get("P95")),
            )
        )

    for _, row in metabolite_only_df.iterrows():
        session.add(
            MetaboliteOnlyPattern(
                run_id=run.id,
                pattern=str(row.get("Pattern", "") or ""),
                count=int(row.get("Count", 0) or 0),
                interpretation=str(row.get("Interpretation", "") or ""),
            )
        )

    session.commit()
    return run.id
''',
'''def analyze_saved_files(saved_paths: List[Path], label: str = "") -> int:
    session = SessionLocal()
    discovered = analyzer.discover_excel_files([str(p) for p in saved_paths])
    if not discovered:
        raise ValueError("No .xlsx files were provided.")

    effective_cutoffs = get_effective_cutoffs(session)
    effective_rule_catalog = get_effective_rule_catalog(session)

    old_cutoffs = dict(analyzer.CUTOFFS)
    old_rule_catalog = [dict(item) for item in analyzer.RULE_CATALOG]

    try:
        analyzer.CUTOFFS = dict(effective_cutoffs)
        analyzer.RULE_CATALOG = [dict(item) for item in effective_rule_catalog]

        run_slug = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        output_dir = OUTPUT_ROOT / run_slug
        output_dir.mkdir(parents=True, exist_ok=True)

        long_df = analyzer.build_long_table(discovered)
        wide_df = analyzer.build_wide_table(long_df)
        flags_df = analyzer.apply_rules(wide_df)
        local_refs_df = analyzer.local_reference_stats(wide_df)
        metabolite_only_df = analyzer.expected_metabolite_only_summary(wide_df)
        specimen_df = analyzer.specimen_summary_table(wide_df, flags_df)

        report_path = output_dir / "lcms_parent_metabolite_report.html"
        flags_csv_path = output_dir / "lcms_flags.csv"
        summary_csv_path = output_dir / "lcms_accession_summary.csv"
        local_refs_csv_path = output_dir / "lcms_local_ratio_reference.csv"

        analyzer.render_report(discovered, wide_df, flags_df, local_refs_df, metabolite_only_df, specimen_df, report_path)
        export_dataframe(flags_df, flags_csv_path)
        export_dataframe(specimen_df, summary_csv_path)
        export_dataframe(local_refs_df, local_refs_csv_path)
        export_dataframe(metabolite_only_df, output_dir / "lcms_expected_metabolite_only.csv")
    finally:
        analyzer.CUTOFFS = old_cutoffs
        analyzer.RULE_CATALOG = old_rule_catalog

    bundle_base = OUTPUT_ROOT / f"{run_slug}_lcms_reviewer_outputs"
    bundle_zip = shutil.make_archive(str(bundle_base), "zip", root_dir=output_dir)

    run = ReviewRun(
        label=label.strip() or f"Run {run_slug}",
        status="completed",
        file_count=len(discovered),
        accession_count=int(wide_df["Sample Name"].nunique()),
        flagged_accession_count=int(specimen_df[specimen_df["FlagCount"] > 0]["Accession"].nunique()),
        red_count=int((flags_df["Severity"] == "red").sum()) if not flags_df.empty else 0,
        amber_count=int((flags_df["Severity"] == "amber").sum()) if not flags_df.empty else 0,
        upload_folder=str(saved_paths[0].parent),
        output_folder=str(output_dir),
        report_path=str(report_path),
        flags_csv_path=str(flags_csv_path),
        summary_csv_path=str(summary_csv_path),
        local_refs_csv_path=str(local_refs_csv_path),
        bundle_zip_path=str(bundle_zip),
    )
    session.add(run)
    session.flush()

    for file_path in discovered:
        session.add(UploadedFile(run_id=run.id, original_name=file_path.name, stored_path=str(file_path)))

    specimen_map = {}
    analyte_columns = [c for c in wide_df.columns if c not in {"Sample Name", "instrument_id", "source_file", "batch_name", "run_date"}]
    specimen_summary_lookup = {row["Accession"]: row for _, row in specimen_df.iterrows()}

    for _, row in wide_df.iterrows():
        accession = str(row["Sample Name"])
        summary_row = specimen_summary_lookup.get(accession, {})
        specimen = Specimen(
            run_id=run.id,
            accession=accession,
            instrument=str(row.get("instrument_id", "") or ""),
            source_file=str(row.get("source_file", "") or ""),
            batch_name=str(row.get("batch_name", "") or ""),
            run_date_text=str(row.get("run_date", "") or ""),
            flag_count=int(summary_row.get("FlagCount", 0) or 0),
            highest_severity=str(summary_row.get("HighestSeverity", "") or ""),
            positive_analytes=str(summary_row.get("PositiveAnalytes", "") or ""),
        )
        session.add(specimen)
        session.flush()
        specimen_map[accession] = specimen

        analyte_rows = []
        for analyte in analyte_columns:
            value = safe_num(row.get(analyte))
            if value is None:
                continue
            analyte_rows.append(
                AnalyteResult(
                    specimen_id=specimen.id,
                    analyte=analyte,
                    value=value,
                    is_positive=1 if positive_with_cutoffs(value, analyte, effective_cutoffs) else 0,
                )
            )
        session.add_all(analyte_rows)

    if not flags_df.empty:
        for _, row in flags_df.iterrows():
            specimen = specimen_map[str(row["Accession"])]
            session.add(
                Flag(
                    specimen_id=specimen.id,
                    severity=str(row.get("Severity", "") or ""),
                    rule_code=str(row.get("RuleCode", "") or ""),
                    flag_title=str(row.get("FlagTitle", "") or ""),
                    analyte_a=str(row.get("AnalyteA", "") or ""),
                    value_a=safe_num(row.get("ValueA")),
                    analyte_b=str(row.get("AnalyteB", "") or ""),
                    value_b=safe_num(row.get("ValueB")),
                    ratio_name=str(row.get("RatioName", "") or ""),
                    ratio_value=safe_num(row.get("RatioValue")),
                    comment=str(row.get("Comment", "") or ""),
                )
            )

    for _, row in local_refs_df.iterrows():
        session.add(
            LocalRatioReference(
                run_id=run.id,
                pair_label=str(row.get("Pair", "") or ""),
                n_value=int(row.get("N", 0) or 0),
                p05=safe_num(row.get("P05")),
                median=safe_num(row.get("Median")),
                p95=safe_num(row.get("P95")),
            )
        )

    for _, row in metabolite_only_df.iterrows():
        session.add(
            MetaboliteOnlyPattern(
                run_id=run.id,
                pattern=str(row.get("Pattern", "") or ""),
                count=int(row.get("Count", 0) or 0),
                interpretation=str(row.get("Interpretation", "") or ""),
            )
        )

    session.commit()
    return run.id
''',
"analyze_saved_files"
)

# ------------------------------------------------------------------
# 9) Dashboard route uses DB-backed rule catalog
# ------------------------------------------------------------------
replace_once(
'''@app.route("/", methods=["GET"])
def dashboard():
    session = SessionLocal()
    totals = {
        "runs": session.scalar(select(func.count(ReviewRun.id))) or 0,
        "specimens": session.scalar(select(func.count(Specimen.id))) or 0,
        "flags": session.scalar(select(func.count(Flag.id))) or 0,
        "red": session.scalar(select(func.count(Flag.id)).where(Flag.severity == "red")) or 0,
        "amber": session.scalar(select(func.count(Flag.id)).where(Flag.severity == "amber")) or 0,
    }
    recent_runs = session.scalars(select(ReviewRun).order_by(ReviewRun.created_at.desc()).limit(12)).all()
    latest_flags = session.scalars(
        select(Flag).join(Flag.specimen).join(Specimen.run).order_by(ReviewRun.created_at.desc(), Flag.id.desc()).limit(20)
    ).all()
    all_specimens = session.scalars(select(Specimen).order_by(Specimen.id.desc())).all()
    all_flags = session.scalars(select(Flag).order_by(Flag.id.desc())).all()
    instrument_summary = build_dashboard_instrument_summary(all_specimens)
    hot_rules = build_flag_rule_summary(all_flags, limit=5)
    return render_template(
        "dashboard.html",
        totals=totals,
        recent_runs=recent_runs,
        latest_flags=latest_flags,
        rule_catalog=analyzer.RULE_CATALOG,
        instrument_summary=instrument_summary,
        hot_rules=hot_rules,
        quick_actions=build_quick_actions(recent_runs),
    )
''',
'''@app.route("/", methods=["GET"])
def dashboard():
    session = SessionLocal()
    effective_rule_catalog = get_effective_rule_catalog(session)
    effective_rule_lookup = {item["rule_code"]: item for item in effective_rule_catalog}

    totals = {
        "runs": session.scalar(select(func.count(ReviewRun.id))) or 0,
        "specimens": session.scalar(select(func.count(Specimen.id))) or 0,
        "flags": session.scalar(select(func.count(Flag.id))) or 0,
        "red": session.scalar(select(func.count(Flag.id)).where(Flag.severity == "red")) or 0,
        "amber": session.scalar(select(func.count(Flag.id)).where(Flag.severity == "amber")) or 0,
    }
    recent_runs = session.scalars(select(ReviewRun).order_by(ReviewRun.created_at.desc()).limit(12)).all()
    latest_flags = session.scalars(
        select(Flag).join(Flag.specimen).join(Specimen.run).order_by(ReviewRun.created_at.desc(), Flag.id.desc()).limit(20)
    ).all()
    all_specimens = session.scalars(select(Specimen).order_by(Specimen.id.desc())).all()
    all_flags = session.scalars(select(Flag).order_by(Flag.id.desc())).all()
    instrument_summary = build_dashboard_instrument_summary(all_specimens)
    hot_rules = build_flag_rule_summary(all_flags, rule_lookup=effective_rule_lookup, limit=5)
    return render_template(
        "dashboard.html",
        totals=totals,
        recent_runs=recent_runs,
        latest_flags=latest_flags,
        rule_catalog=effective_rule_catalog,
        instrument_summary=instrument_summary,
        hot_rules=hot_rules,
        quick_actions=build_quick_actions(recent_runs),
    )
''',
"dashboard route"
)

# ------------------------------------------------------------------
# 10) Run detail route uses DB-backed rule lookup
# ------------------------------------------------------------------
replace_once(
'''@app.route("/runs/<int:run_id>")
def run_detail(run_id: int):
    session = SessionLocal()
    run = session.get(ReviewRun, run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("dashboard"))
    specimens = session.scalars(
        select(Specimen).where(Specimen.run_id == run_id).order_by(Specimen.flag_count.desc(), Specimen.accession.asc())
    ).all()
    refs = session.scalars(select(LocalRatioReference).where(LocalRatioReference.run_id == run_id).order_by(LocalRatioReference.pair_label.asc())).all()
    patterns = session.scalars(select(MetaboliteOnlyPattern).where(MetaboliteOnlyPattern.run_id == run_id).order_by(MetaboliteOnlyPattern.pattern.asc())).all()
    files = session.scalars(select(UploadedFile).where(UploadedFile.run_id == run_id).order_by(UploadedFile.original_name.asc())).all()
    flags = session.scalars(
        select(Flag).join(Flag.specimen).where(Specimen.run_id == run_id).order_by(Flag.severity.asc(), Specimen.accession.asc())
    ).all()
    flagged_specimens = [specimen for specimen in specimens if specimen.flag_count > 0][:10]
    instrument_summary = build_instrument_summary(specimens, flags)
    top_rules = build_flag_rule_summary(flags, limit=8)
    return render_template(
        "run_detail.html",
        run=run,
        files=files,
        specimens=specimens,
        refs=refs,
        patterns=patterns,
        flags=flags,
        rule_lookup=RULE_LOOKUP,
        instrument_summary=instrument_summary,
        top_rules=top_rules,
        flagged_specimens=flagged_specimens,
        review_scenarios=REVIEW_SCENARIOS,
        run_status=run_status(run),
    )
''',
'''@app.route("/runs/<int:run_id>")
def run_detail(run_id: int):
    session = SessionLocal()
    run = session.get(ReviewRun, run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("dashboard"))

    effective_rule_lookup = get_effective_rule_lookup(session)

    specimens = session.scalars(
        select(Specimen).where(Specimen.run_id == run_id).order_by(Specimen.flag_count.desc(), Specimen.accession.asc())
    ).all()
    refs = session.scalars(select(LocalRatioReference).where(LocalRatioReference.run_id == run_id).order_by(LocalRatioReference.pair_label.asc())).all()
    patterns = session.scalars(select(MetaboliteOnlyPattern).where(MetaboliteOnlyPattern.run_id == run_id).order_by(MetaboliteOnlyPattern.pattern.asc())).all()
    files = session.scalars(select(UploadedFile).where(UploadedFile.run_id == run_id).order_by(UploadedFile.original_name.asc())).all()
    flags = session.scalars(
        select(Flag).join(Flag.specimen).where(Specimen.run_id == run_id).order_by(Flag.severity.asc(), Specimen.accession.asc())
    ).all()
    flagged_specimens = [specimen for specimen in specimens if specimen.flag_count > 0][:10]
    instrument_summary = build_instrument_summary(specimens, flags)
    top_rules = build_flag_rule_summary(flags, rule_lookup=effective_rule_lookup, limit=8)
    return render_template(
        "run_detail.html",
        run=run,
        files=files,
        specimens=specimens,
        refs=refs,
        patterns=patterns,
        flags=flags,
        rule_lookup=effective_rule_lookup,
        instrument_summary=instrument_summary,
        top_rules=top_rules,
        flagged_specimens=flagged_specimens,
        review_scenarios=REVIEW_SCENARIOS,
        run_status=run_status(run),
    )
''',
"run_detail route"
)

# ------------------------------------------------------------------
# 11) Specimen detail route uses DB-backed thresholds/rules
# ------------------------------------------------------------------
replace_once(
'''@app.route("/specimens/<int:specimen_id>")
def specimen_detail(specimen_id: int):
    session = SessionLocal()
    specimen = session.get(Specimen, specimen_id)
    if not specimen:
        flash("Specimen not found.", "error")
        return redirect(url_for("dashboard"))
    analytes = session.scalars(
        select(AnalyteResult).where(AnalyteResult.specimen_id == specimen_id).order_by(AnalyteResult.is_positive.desc(), AnalyteResult.analyte.asc())
    ).all()
    flags = session.scalars(select(Flag).where(Flag.specimen_id == specimen_id).order_by(Flag.severity.asc(), Flag.id.asc())).all()
    analyte_rows, analyte_values, analyte_counts = build_specimen_analyte_rows(analytes)
    suspect_peak_cards = build_suspect_peak_cards(analyte_rows, analyte_values, flags)
    return render_template(
        "specimen_detail.html",
        specimen=specimen,
        analytes=analyte_rows,
        flags=flags,
        rule_lookup=RULE_LOOKUP,
        suspect_peak_cards=suspect_peak_cards,
        analyte_counts=analyte_counts,
        severity_labels=SEVERITY_LABELS,
        review_scenarios=REVIEW_SCENARIOS,
    )
''',
'''@app.route("/specimens/<int:specimen_id>")
def specimen_detail(specimen_id: int):
    session = SessionLocal()
    specimen = session.get(Specimen, specimen_id)
    if not specimen:
        flash("Specimen not found.", "error")
        return redirect(url_for("dashboard"))

    effective_rule_lookup = get_effective_rule_lookup(session)
    effective_cutoffs = get_effective_cutoffs(session)

    analytes = session.scalars(
        select(AnalyteResult).where(AnalyteResult.specimen_id == specimen_id).order_by(AnalyteResult.is_positive.desc(), AnalyteResult.analyte.asc())
    ).all()
    flags = session.scalars(select(Flag).where(Flag.specimen_id == specimen_id).order_by(Flag.severity.asc(), Flag.id.asc())).all()
    analyte_rows, analyte_values, analyte_counts = build_specimen_analyte_rows(analytes, cutoff_map=effective_cutoffs)
    suspect_peak_cards = build_suspect_peak_cards(
        analyte_rows,
        analyte_values,
        flags,
        rule_lookup=effective_rule_lookup,
        cutoff_map=effective_cutoffs,
    )
    return render_template(
        "specimen_detail.html",
        specimen=specimen,
        analytes=analyte_rows,
        flags=flags,
        rule_lookup=effective_rule_lookup,
        suspect_peak_cards=suspect_peak_cards,
        analyte_counts=analyte_counts,
        severity_labels=SEVERITY_LABELS,
        review_scenarios=REVIEW_SCENARIOS,
    )
''',
"specimen_detail route"
)

TARGET.write_text(text, encoding="utf-8")
print(f"Patched {TARGET}")
print(f"Backup created at {backup}")
