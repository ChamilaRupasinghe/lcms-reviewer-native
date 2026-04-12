import sqlite3
from pathlib import Path
import pandas as pd

DB = Path(r".\reviewer_data\lcms_reviewer.db")
conn = sqlite3.connect(DB)

try:
    run_id = conn.execute("SELECT MAX(id) FROM review_runs").fetchone()[0]
    print("LATEST_RUN_ID:", run_id)

    files = conn.execute("""
        SELECT id, original_name, stored_path
        FROM uploaded_files
        WHERE run_id = ?
        ORDER BY id
    """, (run_id,)).fetchall()

    print("\n=== UPLOADED FILES FOR LATEST RUN ===")
    for row in files:
        print(row)

    if not files:
        raise SystemExit("No uploaded files found for latest run.")

    file_id, original_name, stored_path = files[0]
    p = Path(stored_path)

    print("\n=== FIRST FILE CHECK ===")
    print("ORIGINAL_NAME:", original_name)
    print("STORED_PATH:", stored_path)
    print("EXISTS:", p.exists())

    if not p.exists():
        raise SystemExit("Stored file does not exist on this machine.")

    df = pd.read_excel(p)
    print("\n=== ALL COLUMNS ===")
    for c in df.columns:
        print(repr(c))

    candidate_cols = [
        c for c in df.columns
        if any(k in str(c).lower() for k in [
            "vial", "position", "order", "drawer", "slot", "sample", "accession"
        ])
    ]

    print("\n=== CANDIDATE POSITION-RELATED COLUMNS ===")
    for c in candidate_cols:
        print(repr(c))

    if candidate_cols:
        print("\n=== FIRST 15 ROWS OF CANDIDATE COLUMNS ===")
        print(df[candidate_cols].head(15).to_string(index=False))
    else:
        print("\nNo obvious position-related columns found.")

finally:
    conn.close()
