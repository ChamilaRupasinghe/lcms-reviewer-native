LCMS Reviewer v4 production package for 10.117.1.148:4444

Contents
- .env.example
- docker-compose.prod.yml
- nginx.conf
- systemd service and backup timer units
- deployment, preflight, backup, restore, and smoke-test scripts
- deployment runbook
- security hardening notes
- backup and restore strategy
- rollback plan
- go-live checklist

Start with these documents
1. DEPLOYMENT_RUNBOOK.txt
2. SECURITY_HARDENING.txt
3. BACKUP_AND_RESTORE.txt
4. GO_LIVE_CHECKLIST.txt
5. ROLLBACK_PLAN.txt


What is new in v4
- user-friendly, color-coded dashboard cards
- clickable recent-run, flagged-specimen, and accession drill-down workflow
- LCMS1 vs LCMS2 instrument activity panels
- searchable flagged-accession and specimen tables
- specimen-level suspect/wrong-peak review notes based on analyte level intensity and parent/metabolite pattern review
- collapsible rule cards and easier reviewer navigation
