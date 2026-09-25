# Clinician Toxicology Survey Platform

A single self-contained HTML file that collects the Yale / Progressive Diagnostics
Clinician Toxicology Survey (9.17.26 instrument), stores responses in the browser,
and analyses them in a built-in dashboard. No server, no install, no build step,
no network calls.

## Running it

- **Locally:** double-click `index.html`.
- **Shared:** put `index.html` on any static host, cloud drive share, or email it.
  Every copy is independent; responses live in whichever browser opened the file.

Opened from disk (`file://`) Chrome blocks IndexedDB, so the page falls back to
`localStorage` and says so in a banner. Served over http(s) it uses IndexedDB.

## Tabs

| Tab | What it does |
|---|---|
| Survey | The fillable instrument, Sections 1–7, with autosave and a resumable draft |
| Dashboard | Distributions, Likert descriptives, Q11 grid, Q18 ranking, cross-tabs, rollups |
| Report | Print-first summary for stakeholders (`Print / save as PDF`) |
| Data | Export CSV/JSON, import and merge, per-record list, storage status |

Section 6 stays locked until every required item in Sections 1–5 is answered, so the
proposed laboratory model is never described before the respondent has described
current practice. "Interviewer mode" reveals the purpose statement, interviewer
instructions and introduction script from the source guide; it changes no question.

## Combining responses from several people

1. Each person exports JSON from their own copy (Data → Export JSON).
2. One person imports every file into a single copy (Data → Choose file to merge).

Merging is keyed on `responseId`: unseen records are inserted, a newer `updatedAt`
replaces an older one, an older one is skipped, and equal timestamps with different
content are kept as a separate forked record rather than overwriting anything.
Re-importing the same file changes nothing.

## Export formats

- **JSON** — lossless interchange, the format to use for merging.
  `{schemaVersion, instrument, exportedAt, exportedFrom, responseCount, responses[]}`
- **CSV (wide)** — one row per respondent. Meta columns, then per question:
  `q13__payer_restrictions` 0/1 per option, `q13_n_selected`, `q13__other_text`,
  `q3_code`/`q3_label`, `q5_value` for Likert numerics, `q11__level_of_care` for grid
  cells, and `q18__row`, `q18__row_score`, `q18_top3__row` for the matrix.
  UTF-8 with BOM, CRLF, RFC 4180 quoting — opens cleanly in Excel.
- **CSV (long / tidy)** — one row per answered item, columns
  `response_id, submitted_at, status, complete, role_list, setting_list, tenure,
  section, question_id, question_number, question_text, item_id, item_text,
  answer_code, answer_label, answer_numeric, is_other, other_text`.
  This is the layout to point Power BI at.

## Statistics

Counts and percentages (multi-select percentages are respondent-denominated and the
denominator is printed), mean, median, sample standard deviation (n−1), min/max,
weighted mean for the Q18 ordinal scale (High 3, Medium 2, Low 1, No value 0),
cross-tab counts with row percentages, and rank ordering with ties broken by
weighted mean. Missing answers drop pairwise and every statistic prints its own N.

No inferential tests run in the browser: at needs-assessment sample sizes they would
over-claim. `analyze_survey.py` does chi-square and Kruskal–Wallis offline against
the long CSV for anyone who wants them.

```bash
pip install pandas scipy
python analyze_survey.py clinician-tox-survey-long-<timestamp>.csv
```

## Privacy

Anonymous by default. No patient information is collected and the contact fields are
optional. Nothing is transmitted anywhere; data stays in the browser until exported.
