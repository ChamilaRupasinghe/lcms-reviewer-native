from web_reviewer import seed_directory, SessionLocal, ReviewRun
from sqlalchemy import select, func

session = SessionLocal()
print('runs_before', session.scalar(select(func.count(ReviewRun.id))) or 0)
run_id = seed_directory('/home/user/lcms_project', 'Seeded sample run')
print('run_id', run_id)
print('runs_after', session.scalar(select(func.count(ReviewRun.id))) or 0)
