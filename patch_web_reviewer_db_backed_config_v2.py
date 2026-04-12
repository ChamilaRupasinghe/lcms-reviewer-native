from pathlib import Path
import shutil
import re
import sys

TARGET = Path("web_reviewer.py")
if not TARGET.exists():
    raise SystemExit(f"Could not find {TARGET.resolve()}")

text = TARGET.read_text(encoding="utf-8").replace("\r\n", "\n")
backup = TARGET.with_name("web_reviewer.py.bak_db_backed_config")
shutil.copy2(TARGET, backup)

def insert_before(anchor: str, block: str, label: str):
    global text
    if block.strip() in text:
        return
    idx = text.find(anchor)
    if idx == -1:
        raise RuntimeError(f"Patch failed: could not find anchor for {label}")
    text = text[:idx] + block.rstrip() + "\n\n" + text[idx:]

def regex_replace(pattern: str, replacement: str, label: str):
    global text
    new_text, count = re.subn(pattern, replacement.rstrip() + "\n", text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"Patch failed: could not replace block for {label}")
    text = new_text

# ------------------------------------------------------------------
# 1) Insert runtime ORM models before create_engine_and_session
# ------------------------------------------------------------------
insert_before(
    "def create_engine_and_session() -> tuple:\n",
    '''
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
''',
    "runtime ORM models"
)

# ------------------------------------------------------------------
# 2) Insert DB-backed config helpers before export_dataframe
# ------------------------------------------------------------------
insert_before(
    "def export_dataframe(df: pd.DataFrame, path: Path) -> None:\n",
    '''
DEFAULT_CUTOFFS = dict(analyzer.CUTOFFS)
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
        if row.cutoff_value is not None:
            cutoff_map[row.analyte] = float(row.cutoff_value)
    return cutoff_map


def get_effective_rule_catalog(session) -> list[dict]:
    rows = session.scalars(
        select(RuntimeRuleCatalog).order_by(
            RuntimeRuleCatalog.sort_order.asc(),
            RuntimeRuleCatalog.rule_code.asc(),
        )
    ).all()
    if not rows:
        return [dict(item) for item in DEFAULT_RULE_CATALOG]

    catalog = []
    for row in rows:
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
''',
    "effective config helpers"
)

# ------------------------------------------------------------------
# 3) Replace friendly_logic
# ------------------------------------------------------------------
regex_replace(
    r'def friendly_logic\(rule_code: str\) -> str:\n.*?(?=\ndef analyte_level_meta\()',
    '''
def friendly_logic(rule_code: str, rule_lookup: dict | None = None) -> str:
    item = (rule_lookup or DEFAULT_RULE_LOOKUP).get(rule_code, {})
    return item.get("logic", "Stored review rule")
''',
    "friendly_logic"
)

# ------------------------------------------------------------------
# 4) Replace analyte_level_meta
# ------------------------------------------------------------------
regex_replace(
    r'def analyte_level_meta\(value: float \| None, analyte: str\) -> dict:\n.*?(?=\ndef format_percentage\()',
    '''
def analyte_level_meta(value: float | None, analyte: str, cutoff_map: dict[str, float] | None = None) -> dict:
    cutoff = (cutoff_map or DEFAULT_CUTOFFS).get(analyte)
    multiplier = None
    tone = "muted"
    label = "Reference only"
    short_label = "info"
    if value is None:
        return {
            "cutoff": cutoff,
            "multiplier": None,
            "tone": tone,
            "label": label,
            "short_label": short_label,
            "display_multiplier": "",
        }
    if cutoff and cutoff > 0:
        multiplier = value / cutoff
        if multiplier < 1:
            tone = "trace"
            label = "Detected below cutoff"
            short_label = "trace"
        elif multiplier < 5:
            tone = "positive"
            label = "Positive"
            short_label = "positive"
        elif multiplier < 20:
            tone = "high"
            label = "High positive"
            short_label = "high"
        else:
            tone = "extreme"
            label = "Very high signal"
            short_label = "extreme"
    return {
        "cutoff": cutoff,
        "multiplier": multiplier,
        "tone": tone,
        "label": label,
        "short_label": short_label,
        "display_multiplier": f"{multiplier:.1f}× cutoff" if multiplier is not None else "",
    }
''',
    "analyte_level_meta"
)

# ------------------------------------------------------------------
# 5) Replace build_flag_rule_summary
# ------------------------------------------------------------------
regex_replace(
    r'def build_flag_rule_summary\(flags: List\[Flag\], limit: int = 6\) -> List\[dict\]:\n.*?(?=\ndef build_instrument_summary\()',
    '''
def build_flag_rule_summary(flags: List[Flag], rule_lookup: dict | None = None, limit: int = 6) -> List[dict]:
    grouped: dict[str, dict] = {}
    counts = Counter(flag.flag_title for flag in flags)
    for flag in flags:
        if flag.flag_title not in grouped:
            grouped[flag.flag_title] = {
                "title": flag.flag_title,
                "severity": flag.severity,
                "count": counts[flag.flag_title],
                "rule_code": flag.rule_code,
                "logic": friendly_logic(flag.rule_code, rule_lookup),
            }
    ordered = sorted(grouped.values(), key=lambda item: (-item["count"], -severity_rank(item["severity"]), item["title"]))
    return ordered[:limit]
''',
    "build_flag_rule_summary"
)

# ------------------------------------------------------------------
# 6) Replace build_specimen_analyte_rows
# ------------------------------------------------------------------
regex_replace(
    r'def build_specimen_analyte_rows\(analytes: List\[AnalyteResult\]\) -> tuple\[list\[dict\], dict, dict\]:\n.*?(?=\ndef build_suspect_peak_cards\()',
    '''
def build_specimen_analyte_rows(analytes: List[AnalyteResult], cutoff_map: dict[str, float] | None = None) -> tuple[list[dict], dict, dict]:
    rows = []
    value_map = {}
    counts = {"positive": 0, "extreme": 0, "high": 0, "trace": 0}
    for item in analytes:
        meta = analyte_level_meta(item.value, item.analyte, cutoff_map=cutoff_map)
        row = {
            "id": item.id,
            "analyte": item.analyte,
            "value": item.value,
            "is_positive": bool(item.is_positive),
            **meta,
        }
        rows.append(row)
        value_map[item.analyte] = float(item.value)
        if row["is_positive"]:
            counts["positive"] += 1
        if meta["tone"] == "extreme":
            counts["extreme"] += 1
        elif meta["tone"] == "high":
            counts["high"] += 1
        elif meta["tone"] == "trace":
            counts["trace"] += 1
    rows.sort(key=lambda row: (0 if row["is_positive"] else 1, -safe_num(row["value"]) if row["value"] is not None else 0, row["analyte"]))
    return rows, value_map, counts
''',
    "build_specimen_analyte_rows"
)

# ------------------------------------------------------------------
# 7) Replace build_suspect_peak_cards
# ------------------------------------------------------------------
regex_replace(
    r'def build_suspect_peak_cards\(analyte_rows: List\[dict\], value_map: dict, flags: List\[Flag\]\) -> List\[dict\]:\n.*?(?=\ndef build_quick_actions\()',
    '''
def build_suspect_peak_cards(
    analyte_rows: List[dict],
    value_map: dict,
    flags: List[Flag],
    rule_lookup: dict | None = None,
    cutoff_map: dict[str, float] | None = None,
) -> List[dict]:
    cards = []
    seen = set()
    cutoff_map = cutoff_map or DEFAULT_CUTOFFS

    for flag in flags:
        details = []
        if flag.analyte_a:
            details.append(f"{flag.analyte_a} {analyzer.fmt_num(flag.value_a) if flag.value_a is not None else ''}".strip())
        if flag.analyte_b:
            details.append(f"{flag.analyte_b} {analyzer.fmt_num(flag.value_b) if flag.value_b is not None else ''}".strip())
        ratio_text = ""
        if flag.ratio_name and flag.ratio_value is not None:
            ratio_text = f"{flag.ratio_name}: {analyzer.fmt_ratio(flag.ratio_value)}"
        key = (flag.rule_code, flag.analyte_a, flag.analyte_b)
        if key in seen:
            continue
        seen.add(key)
        cards.append(
            {
                "severity": flag.severity,
                "title": flag.flag_title,
                "summary": flag.comment,
                "detail": " · ".join(part for part in [", ".join(details), ratio_text] if part),
                "logic": friendly_logic(flag.rule_code, rule_lookup),
                "source": "Rule-based flag",
            }
        )

    flag_related_analytes = {flag.analyte_a for flag in flags if flag.analyte_a} | {flag.analyte_b for flag in flags if flag.analyte_b}
    for row in analyte_rows:
        if row["tone"] != "extreme" or row["analyte"] in flag_related_analytes:
            continue
        cards.append(
            {
                "severity": "info",
                "title": f"Review very high {row['analyte']} signal",
                "summary": "Level is far above the decision cutoff. If unexpected clinically, review chromatographic integration, calibration context, and specimen history.",
                "detail": f"{analyzer.fmt_num(row['value'])} ng/mL · {row['display_multiplier']}",
                "logic": "QC review suggestion",
                "source": "Analyte intensity screen",
            }
        )

    for scenario in REVIEW_SCENARIOS:
        parent = scenario["parent"]
        metabolite = scenario["metabolite"]
        p_value = value_map.get(parent)
        m_value = value_map.get(metabolite)
        if p_value is None or not positive_with_cutoffs(p_value, parent, cutoff_map):
            continue
        p_cutoff = cutoff_map.get(parent, 0) or 0
        m_cutoff = cutoff_map.get(metabolite, 0) or 0
        ratio = (m_value / p_value) if (m_value is not None and p_value) else None
        key = (scenario["label"], round(ratio or -1, 6), round(p_value, 4), round(m_value or -1, 4))
        if key in seen:
            continue

        severity = None
        summary = None
        detail = None
        if scenario["kind"] == "ratio_min":
            if (m_value is None or m_value < m_cutoff) and p_value >= scenario.get("parent_review_floor", p_cutoff):
                severity = "red" if scenario.get("red_ratio") is not None else "amber"
                summary = f"{metabolite} is absent or below cutoff despite positive {parent}."
            elif ratio is not None and scenario.get("red_ratio") is not None and ratio < scenario["red_ratio"]:
                severity = "red"
                summary = f"{metabolite}:{parent} ratio is below the strong-suspicion threshold."
            elif ratio is not None and ratio < scenario.get("warn_ratio", 0):
                severity = "amber"
                summary = f"{metabolite}:{parent} ratio is below the expected reviewer threshold."
            if ratio is not None:
                detail = f"Ratio {analyzer.fmt_ratio(ratio)}"
        elif scenario["kind"] == "metabolite_required":
            if (m_value is None or m_value < m_cutoff) and p_value >= scenario.get("parent_review_floor", p_cutoff):
                severity = "amber"
                summary = f"Expected metabolite {metabolite} is absent or below cutoff."
                detail = f"{parent} {analyzer.fmt_num(p_value)} ng/mL"
            elif ratio is not None and scenario.get("warn_ratio") and ratio < scenario["warn_ratio"]:
                severity = "amber"
                summary = f"{metabolite}:{parent} ratio is lower than the practical review band."
                detail = f"Ratio {analyzer.fmt_ratio(ratio)}"
        elif scenario["kind"] == "minor_metabolite_max" and ratio is not None:
            if ratio > scenario.get("red_ratio", 999):
                severity = "red"
                summary = f"{metabolite} is disproportionately high for expected minor metabolite formation."
            elif ratio > scenario.get("warn_ratio", 999):
                severity = "amber"
                summary = f"{metabolite} exceeds the conservative minor-metabolite review range."
            if severity:
                detail = f"Observed {format_percentage(ratio)} of {parent}"
        elif scenario["kind"] == "impurity_max" and ratio is not None and m_value is not None and positive_with_cutoffs(m_value, metabolite, cutoff_map):
            if ratio > scenario.get("warn_ratio", 999):
                severity = "amber"
                summary = f"{metabolite} is too high to be comfortably explained as trace impurity alone."
                detail = f"Observed {format_percentage(ratio)} of {parent}"

        if severity and summary:
            seen.add(key)
            cards.append(
                {
                    "severity": severity,
                    "title": scenario["label"],
                    "summary": summary,
                    "detail": detail or "",
                    "logic": scenario["explanation"],
                    "source": "Pattern review",
                }
            )

    return sorted(cards, key=lambda item: (-severity_rank(item["severity"]), item["title"]))
''',
    "build_suspect_peak_cards"
)

# ------------------------------------------------------------------
# 8) Replace analyze_saved_files
# ------------------------------------------------------------------
regex_replace(
    r'def analyze_saved_files\(saved_paths: List\[Path\], label: str = ""\) -> int:\n.*?(?=\ndef save_uploaded_files\()',
    '''
def analyze_saved_files(saved_paths: List[Path], label: str = "") -> int:
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
# 9) Replace dashboard route
# ------------------------------------------------------------------
regex_replace(
    r'@app\.route\("/", methods=\["GET"\]\)\ndef dashboard\(\):\n.*?(?=\n\n@app\.route\("/upload", methods=\["POST"\]\))',
    '''
@app.route("/", methods=["GET"])
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
# 10) Replace run_detail route
# ------------------------------------------------------------------
regex_replace(
    r'@app\.route\("/runs/<int:run_id>"\)\ndef run_detail\(run_id: int\):\n.*?(?=\n\n@app\.route\("/specimens/<int:specimen_id>"\))',
    '''
@app.route("/runs/<int:run_id>")
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
# 11) Replace specimen_detail route
# ------------------------------------------------------------------
regex_replace(
    r'@app\.route\("/specimens/<int:specimen_id>"\)\ndef specimen_detail\(specimen_id: int\):\n.*?(?=\n\n@app\.route\("/download/<int:run_id>/<string:asset>"\))',
    '''
@app.route("/specimens/<int:specimen_id>")
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
