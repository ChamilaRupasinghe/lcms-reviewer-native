from web_reviewer import SessionLocal, ReviewRun, Specimen, Flag, AnalyteResult
from sqlalchemy import select, func

session = SessionLocal()
print('runs', session.scalar(select(func.count(ReviewRun.id))) or 0)
print('specimens', session.scalar(select(func.count(Specimen.id))) or 0)
print('flags', session.scalar(select(func.count(Flag.id))) or 0)
print('analytes', session.scalar(select(func.count(AnalyteResult.id))) or 0)
for run in session.scalars(select(ReviewRun).order_by(ReviewRun.id)).all():
    print('run', run.id, run.label, run.file_count, run.accession_count, run.flagged_accession_count, run.red_count, run.amber_count)
