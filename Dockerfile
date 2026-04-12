FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY reviewer_app /app/reviewer_app
COPY lcms_parent_metabolite_analyzer.py /app/lcms_parent_metabolite_analyzer.py
WORKDIR /app/reviewer_app
ENV LCMS_DATA_DIR=/data \
    LCMS_HOST=0.0.0.0 \
    LCMS_PORT=8000
EXPOSE 8000
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
