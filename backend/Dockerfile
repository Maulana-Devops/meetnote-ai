FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --disable-pip-version-check --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/main.py ./main.py
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY backend/scripts ./scripts
# Kamus organisasi Fase 1 (path default /config/indonesian-vocab.txt di container).
COPY config /config

# Volume compose dilewat di /data; model lokal opsional disimpan di /models.
RUN mkdir -p /data/storage/meetings /models/faster-whisper

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
