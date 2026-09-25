"""Offline companion analysis for the clinician toxicology survey.

Reads the long/tidy CSV exported from index.html and reports the statistics the
in-browser dashboard deliberately leaves out: association tests between respondent
characteristics and their answers. The HTML file is fully functional without this.

Usage:
    python analyze_survey.py clinician-tox-survey-long-<timestamp>.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from scipy import stats

Q18_SCORES = {"High": 3, "Medium": 2, "Low": 1, "No value": 0}
MIN_GROUP = 3


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str).fillna("")
    df["answer_numeric"] = pd.to_numeric(df["answer_numeric"], errors="coerce")
    return df


def wide_single(df: pd.DataFrame, question_id: str) -> pd.Series:
    """One value per respondent for a single-select or Likert question."""
    sub = df[df.question_id == question_id]
    return sub.set_index("response_id")["answer_label"]


def selected(df: pd.DataFrame, question_id: str) -> pd.DataFrame:
    """Respondent x option indicator frame for a multi-select question."""
    sub = df[df.question_id == question_id]
    if sub.empty:
        return pd.DataFrame()
    return pd.crosstab(sub.response_id, sub.item_text).clip(upper=1)


def chi_square(label: str, table: pd.DataFrame) -> None:
    table = table.loc[table.sum(axis=1) >= MIN_GROUP, table.sum(axis=0) >= MIN_GROUP]
    if table.shape[0] < 2 or table.shape[1] < 2:
        print(f"  {label}: too sparse to test")
        return
    chi2, p, dof, expected = stats.chi2_contingency(table)
    small = (expected < 5).mean()
    note = "  (>20% of expected counts <5, read as directional)" if small > 0.2 else ""
    print(f"  {label}: chi2={chi2:.2f}, dof={dof}, p={p:.4f}{note}")


def kruskal(label: str, groups: dict[str, list[float]]) -> None:
    usable = {k: v for k, v in groups.items() if len(v) >= MIN_GROUP}
    if len(usable) < 2:
        print(f"  {label}: too few groups with n>={MIN_GROUP}")
        return
    h, p = stats.kruskal(*usable.values())
    sizes = ", ".join(f"{k} n={len(v)}" for k, v in usable.items())
    print(f"  {label}: H={h:.2f}, p={p:.4f}  ({sizes})")


def main(path: Path) -> int:
    df = load(path)
    respondents = df.response_id.nunique()
    print(f"{respondents} respondents, {len(df)} answered items, from {path.name}\n")

    tenure = wide_single(df, "q3")
    confidence = df[df.question_id == "q5"].set_index("response_id")["answer_numeric"]
    familiarity = df[df.question_id == "q6"].set_index("response_id")["answer_numeric"]

    print("Confidence (Q5) and ASAM familiarity (Q6)")
    for name, series in (("Q5 confidence", confidence), ("Q6 familiarity", familiarity)):
        v = series.dropna()
        print(f"  {name}: n={len(v)}, mean={v.mean():.2f}, median={v.median():.1f}, sd={v.std(ddof=1):.2f}")
    joint = pd.concat([confidence, familiarity], axis=1, keys=["q5", "q6"]).dropna()
    if len(joint) >= MIN_GROUP:
        rho, p = stats.spearmanr(joint.q5, joint.q6)
        print(f"  Q5 vs Q6 Spearman rho={rho:.3f}, p={p:.4f}, n={len(joint)}")

    print("\nTenure (Q3) vs Likert scales")
    for name, series in (("Q5 confidence", confidence), ("Q6 familiarity", familiarity)):
        groups: dict[str, list[float]] = {}
        for rid, value in series.dropna().items():
            groups.setdefault(tenure.get(rid, "unknown"), []).append(value)
        kruskal(f"{name} by tenure", groups)

    print("\nRole (Q1) vs answers")
    roles = selected(df, "q1")
    for question_id, label in (("q14", "payer influence (Q14)"), ("q15", "education sufficient (Q15)"),
                               ("q16", "laboratory contact frequency (Q16)"), ("q19", "radiology analogy (Q19)")):
        answer = wide_single(df, question_id)
        if roles.empty or answer.empty:
            continue
        rows = []
        for role in roles.columns:
            for rid in roles.index[roles[role] == 1]:
                if rid in answer.index:
                    rows.append((role, answer.loc[rid]))
        if not rows:
            continue
        frame = pd.DataFrame(rows, columns=["role", "answer"])
        chi_square(f"role x {label}", pd.crosstab(frame.role, frame.answer))

    print("\nQ18 weighted value scores")
    q18 = df[(df.question_id == "q18") & (df.answer_label.isin(Q18_SCORES))]
    if not q18.empty:
        scores = q18.assign(score=q18.answer_label.map(Q18_SCORES))
        summary = scores.groupby("item_text").score.agg(["count", "mean"]).sort_values("mean", ascending=False)
        top3 = df[(df.question_id == "q18") & (df.answer_code == "top3")]
        picks = top3.item_text.str.replace(" (most clinical value)", "", regex=False).value_counts()
        summary["top3_picks"] = picks
        summary["top3_picks"] = summary["top3_picks"].fillna(0).astype(int)
        print(summary.sort_values(["top3_picks", "mean"], ascending=False).to_string(
            float_format=lambda v: f"{v:.2f}"))

    print("\nBiggest challenges (Q13) by setting (Q2)")
    settings = selected(df, "q2")
    challenges = selected(df, "q13")
    if not settings.empty and not challenges.empty:
        shared = settings.index.intersection(challenges.index)
        table = settings.loc[shared].T @ challenges.loc[shared]
        print(table.to_string())

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1])))
