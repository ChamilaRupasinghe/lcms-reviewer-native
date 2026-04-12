LCMS Parent-Metabolite Reviewer Web App

What this version adds
- multi-user web interface for upload, review, and specimen drill-down
- persistent database storage so runs reload after restart
- downloadable HTML/CSV outputs for each run
- SQLite by default, with optional PostgreSQL via DATABASE_URL
- Docker Compose file with restart=unless-stopped for automatic relaunch after reboot
- gunicorn workers for concurrent browser use

How to run locally
1. cd reviewer_app
2. pip install -r requirements.txt
3. python web_reviewer.py
4. open http://127.0.0.1:8000

How to seed sample files on first launch
python web_reviewer.py --seed-dir /path/to/folder/with/sample_xlsx

How to run with Docker
1. cd reviewer_app
2. docker compose up -d --build
3. open http://127.0.0.1:8000

Persistence
- default local database and files are stored under reviewer_app/reviewer_data
- in Docker, persistent data is stored in reviewer_app/persistent_data
- restarting the process reloads all prior runs from the database automatically

Operational notes
- intended as a reviewer, not an auto-finalizer
- accession filter keeps only specimen rows starting with T, including rerun suffixes such as -rr
- HTML/CSV output is regenerated for each run and linked from the run detail page
- for heavier concurrent use, point DATABASE_URL to PostgreSQL instead of SQLite
