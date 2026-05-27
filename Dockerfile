FROM python:3.13-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tools ./tools
COPY export.py ./

# data/civic.json is bind-mounted from the host git clone at /app/data; the DB is rebuilt from it.
ENV DB_PATH=/data/civic.db
ENV CIVIC_JSON=/app/data/civic.json
ENV PORT=8902
EXPOSE 8902

# Build the SQLite from the pushed JSON, then serve. Host cron re-runs load_json after `git pull`.
CMD ["sh", "-c", "python tools/load_json.py && uvicorn app.main:app --host 0.0.0.0 --port 8902"]
