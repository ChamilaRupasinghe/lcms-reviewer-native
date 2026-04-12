import sqlite3
conn = sqlite3.connect(r".\reviewer_data\lcms_reviewer.db")
try:
    run_id = conn.execute("SELECT MAX(id) FROM review_runs").fetchone()[0]
    print("LATEST_RUN_ID:", run_id)
    rows = conn.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN LENGTH(TRIM(COALESCE(well_position, ''))) > 0 THEN 1 ELSE 0 END)
        FROM specimens
        WHERE run_id = ?
    """, (run_id,)).fetchone()
    print("SPECIMEN_COUNTS:", rows)
    preview = conn.execute("""
        SELECT accession, source_file, well_position
        FROM specimens
        WHERE run_id = ?
        ORDER BY id
        LIMIT 15
    """, (run_id,)).fetchall()
    for row in preview:
        print(row)
finally:
    conn.close()
