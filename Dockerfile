FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

RUN useradd -u 1000 -m appuser && chown -R appuser:appuser /srv
USER appuser

ENV PORT=8080
CMD ["sh", "-c", "exec uvicorn app.api:app --host 0.0.0.0 --port ${PORT}"]
