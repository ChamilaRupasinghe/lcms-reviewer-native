import sqlite3
from pathlib import Path

db_path = Path(r".\reviewer_data\lcms_reviewer.db")
conn = sqlite3.connect(db_path)
try:
    cols = [row[1] for row in conn.execute("PRAGMA table_info(specimens)").fetchall()]
    if "well_position" not in cols:
        conn.execute("ALTER TABLE specimens ADD COLUMN well_position TEXT NOT NULL DEFAULT ''")
        conn.commit()
        print("Added specimens.well_position")
    else:
        print("specimens.well_position already exists")

    cols = [row[1] for row in conn.execute("PRAGMA table_info(specimens)").fetchall()]
    print("Specimen columns:", cols)
finally:
    conn.close()
