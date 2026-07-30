# syntax=docker/dockerfile:1

# Image tunggal untuk API + semua Celery worker + beat. Proses mana yang
# jalan ditentukan oleh `command:` di docker-compose.yml, bukan oleh Dockerfile
# ini — jadi image yang sama dipakai ulang untuk 7 service (api, 5 worker,
# beat) dan cukup di-build sekali.
FROM python:3.12-slim

# build-essential: jaga-jaga kalau ada dependency Python yang tidak punya
# prebuilt wheel manylinux yang cocok dan perlu dikompilasi dari source.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

# uv dipakai untuk install dependency dari pyproject.toml (bukan
# requirements.txt — file itu di repo ini tersimpan sebagai UTF-16 dan akan
# gagal/salah kalau diparse pip apa adanya; pyproject.toml adalah sumber yang
# valid dan memang sudah dipakai project ini, lihat .venv & uv.lock).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Catatan: uv.lock di-gitignore di repo ini, jadi belum tentu ikut terbawa
# kalau deploy lewat `git clone` di server. Karena itu COPY seluruh source
# dulu (bukan copy pyproject.toml/uv.lock terpisah demi cache layer), lalu
# `uv sync` TANPA --frozen — kalau uv.lock ada & cocok dipakai apa adanya,
# kalau tidak ada/tidak sinkron, uv akan resolve ulang dari pyproject.toml
# alih-alih gagal total. Trade-off: build sedikit lebih lambat (dependency
# ikut re-resolve tiap ada perubahan source), tapi jauh lebih tahan terhadap
# variasi kondisi deploy.
COPY . .
RUN uv sync

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 9191

# Default: jalankan API server. Untuk worker/beat, override lewat `command:`
# di docker-compose.yml (image yang sama, proses yang berbeda).
CMD ["python", "main.py"]
