import sqlite3
from pathlib import Path

db_path = Path(r".\reviewer_data\lcms_reviewer.db")
conn = sqlite3.connect(db_path)

try:
    print("=== REVIEW RUNS ===")
    rows = conn.execute("""
        SELECT id, label, file_count, accession_count, created_at
        FROM review_runs
        ORDER BY id DESC
    """).fetchall()
    for row in rows:
        print(row)

    print("\n=== UPLOADED FILES FOR RUN 1 ===")
    rows = conn.execute("""
        SELECT id, original_name, stored_path
        FROM uploaded_files
        WHERE run_id = 1
        ORDER BY id
    """).fetchall()
    for row in rows:
        print(row)

    print("\n=== SPECIMEN WELL POSITION COUNTS BY RUN ===")
    rows = conn.execute("""
        SELECT
            run_id,
            COUNT(*) AS total_specimens,
            SUM(CASE WHEN LENGTH(TRIM(COALESCE(well_position, ''))) > 0 THEN 1 ELSE 0 END) AS specimens_with_well
        FROM specimens
        GROUP BY run_id
        ORDER BY run_id DESC
    """).fetchall()
    for row in rows:
        print(row)

    print("\n=== FIRST 20 SPECIMENS FROM RUN 1 ===")
    rows = conn.execute("""
        SELECT id, accession, source_file, well_position, batch_name
        FROM specimens
        WHERE run_id = 1
        ORDER BY id
        LIMIT 20
    """).fetchall()
    for row in rows:
        print(row)

finally:
    conn.close()
