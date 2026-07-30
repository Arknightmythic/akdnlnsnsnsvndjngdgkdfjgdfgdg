# SynchronoAPI

> Backend berbasis **FastAPI** untuk memproses, mencocokkan (**Data Matching**), dan memberikan penilaian (**Grading**) pada data CSV secara _real-time_ maupun _background processing_.

Sistem ini menggunakan **StarRocks** sebagai database analitik utama, **MinIO** sebagai _object storage_, dan **Celery + Redis** untuk eksekusi tugas asinkron (_matching_, _reasoning AI_, _export_, _custom mapping_) serta tugas terjadwal (_retention_).

Frontend-nya ada di repo terpisah: [`synchrono-web-client`](../synchrono-web-client/README.md).

---

## Daftar Isi

- [Prasyarat Sistem](#-prasyarat-sistem)
- [Persiapan Lingkungan](#️-1-persiapan-lingkungan)
- [Menjalankan Layanan](#-2-menjalankan-layanan)
- [Endpoint Penting](#-3-endpoint-penting)
- [Troubleshooting](#-4-troubleshooting)

---

## 📋 Prasyarat Sistem

Pastikan layanan berikut sudah berjalan dan dapat diakses sebelum memulai:

| Layanan          | Keterangan                                                                 |
| ---------------- | --------------------------------------------------------------------------- |
| **StarRocks**    | Database analitik utama (MySQL Dialect), schema `synchrono`                 |
| **MinIO**        | Object storage kompatibel S3                                                |
| **Redis**        | Broker & backend untuk **semua** Celery app (matching, reasoning, dst)      |
| **Ollama / vLLM** | LLM provider untuk fitur Reasoning AI (`reasoning/`) & Custom Mapping GenAI (`custom_mapping/`) — tanpa ini, dua fitur itu akan gagal, sisanya tetap jalan normal |
| **Python 3.x**   | Direkomendasikan menggunakan Virtual Environment                            |

---

## ⚙️ 1. Persiapan Lingkungan

### Langkah 1 — Aktifkan Virtual Environment

Jika menggunakan Git Bash di Windows:

```bash
source .venv/Scripts/activate
```

### Langkah 2 — Instalasi Dependensi

```bash
pip install -r requirements.txt
```

Dependensi utama meliputi: FastAPI, Uvicorn, Polars, DuckDB, SQLAlchemy, Celery, Redis, rapidfuzz, langchain-openai (client untuk Ollama/vLLM).

### Langkah 3 — Konfigurasi Environment Variables

Salin `.env_example` menjadi `.env` di root directory, lalu isi:

```env
# ── Database (StarRocks) ───────────────────────────────
STARROCKS_HOST=127.0.0.1
STARROCKS_PORT=9030
STARROCKS_USER=root
STARROCKS_PASSWORD=
STARROCKS_DATABASE=synchrono

# ── Object Storage (MinIO) ─────────────────────────────
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=your_access_key
MINIO_SECRET_KEY=your_secret_key
RAW_BUCKET_NAME=raw-zone
# CURATED_BUCKET_NAME dipakai sebagai PREFIX FOLDER di dalam RAW_BUCKET_NAME
# untuk file parquet hasil upload — BUKAN nama bucket S3 terpisah.
CURATED_BUCKET_NAME=curated-zone

# ── Task Queue (Celery & Redis) ────────────────────────
# Dipakai oleh KEDUA Celery app (worker.celery_app dan reasoning.celery_app)
REDIS_URL=redis://127.0.0.1:6379/0

# ── LLM Provider (Reasoning AI + Custom Mapping GenAI) ─
# LLM_PROVIDER = "ollama" (default) atau "vllm"
LLM_PROVIDER=ollama
OLLAMA_LOCAL_BASE_URL=http://localhost:11434
OLLAMA_MODEL_NAME=llama3.1:8b-instruct-q4_K_M
# Kalau LLM_PROVIDER=vllm, dipakai sebagai gantinya:
# VLLM_MODEL_NAME=meta-llama/Meta-Llama-3-8B-Instruct
# OPENAI_API_KEY=EMPTY

# ── Chatbot (fitur /agent) ─────────────────────────────
OLLAMA_CLOUD_BASE_URL=
```

> Variabel lain di `.env_example` (`QDRANT_URL`, `COLLECTION_NAME`, `OPIK_URL_OVERRIDE`, dst) dipakai oleh fitur chatbot/knowledge base — isi hanya jika fitur tersebut dipakai.

---

## 🏃 2. Menjalankan Layanan

Sistem terdiri dari **1 API server + 5 Celery worker (masing-masing 1 queue) + 1 Celery beat** — total **7 terminal terpisah**, di luar dependency eksternal (StarRocks/MinIO/Redis/Ollama) yang harus sudah menyala. Pastikan Virtual Environment aktif di tiap terminal.

> **⚠️ Ada 2 Celery app berbeda di project ini** — jangan tertukar flag `-A`-nya:
> - `worker.celery_app` ([worker.py](worker.py)) → dipakai untuk queue `audit_queue`, `matching_queue`, `export_queue`, `custom_mapping_queue`
> - `reasoning.celery_app` ([reasoning/celery_app.py](reasoning/celery_app.py)) → khusus `reasoning_queue`
>
> Tidak ada `audit.celery_app` atau `processing.celery_app` terpisah — modul-modul itu memakai `worker.celery_app` yang sama lewat `autodiscover_tasks`.

> **⚠️ Penting untuk Windows:** Wajib menggunakan `python -m celery` dan flag `--pool=solo`. Tanpa flag ini, proses Celery akan _hang_ atau memunculkan `ModuleNotFoundError`. Di Linux/production, ganti `--pool=solo` dengan `--concurrency=4` (atau sesuai jumlah core) supaya worker bisa multi-proses.

### Terminal 1 — FastAPI Server

Menerima request dari frontend: upload, grading, matching, retrieval, audit, chatbot, custom mapping.

```bash
python main.py
```

Server berjalan di: `http://localhost:9191`

---

### Terminal 2 — Matching Worker

Komputasi pencocokan data (Jaro-Winkler via DuckDB + Polars) untuk file yang jutaan baris.

```bash
python -m celery -A worker.celery_app worker -Q matching_queue --pool=solo --loglevel=info
```

### Terminal 3 — Reasoning Worker

Memproses antrean AI (LLM) untuk memberi alasan otomatis pada baris `MANUAL_REVIEW` (micro-batching). **Perhatikan `-A`-nya beda dari worker lain.**

```bash
python -m celery -A reasoning.celery_app worker -Q reasoning_queue --pool=solo --loglevel=info
```

### Terminal 4 — Export Worker

Menghasilkan file `match.csv` / `unmatch.csv` ke MinIO setelah matching selesai (auto-trigger) atau setelah user klik "Mark as Completed".

```bash
python -m celery -A worker.celery_app worker -Q export_queue --pool=solo --loglevel=info
```

### Terminal 5 — Custom Mapping Worker

Menjalankan GenAI untuk memetakan kolom file custom (grade 6/F) ke kolom master.

```bash
python -m celery -A worker.celery_app worker -Q custom_mapping_queue --pool=solo --loglevel=info
```

### Terminal 6 — Audit Worker

Mencatat audit trail, access log, dan menjalankan retention (hapus log kedaluwarsa) secara non-blocking.

```bash
python -m celery -A worker.celery_app worker -Q audit_queue --pool=solo --loglevel=info
```

### Terminal 7 — Celery Beat (Scheduler)

Memicu tugas terjadwal: `execute_audit_retention` (harian, 00:00 Asia/Jakarta) dan `flush_access_logs` (tiap 10 detik). Tanpa beat, kedua tugas ini **tidak pernah jalan otomatis** — hanya bisa dipicu manual lewat `POST /retention/trigger`.

```bash
python -m celery -A worker.celery_app beat --loglevel=info
```

> Untuk development cepat kalau tidak butuh fitur AI/export, minimal jalankan Terminal 1, 2, 6, 7 (API + matching + audit + beat) — cukup untuk alur upload → grading → matching auto-match. Fitur reasoning, export, dan custom mapping (grade 6) butuh worker masing-masing di atas.

---

## 🧪 3. Endpoint Penting

### `POST /files/` — Upload & Ingestion (SSE)

Mengonversi CSV ke Parquet, mengupload ke MinIO, dan mencetak progress secara _real-time_ via Server-Sent Events.

- **Format request:** `multipart/form-data`
- **Field:** `institution_name`, `files`

---

### `POST /match/?file_id={id}` — Data Matching

Melempar job matching ke `matching_queue` (async, 202 Accepted). Progress-nya bisa diikuti lewat `GET /match/stream/{file_id}` (SSE) atau `GET /match/logs/{file_id}` (snapshot untuk reconnect).

---

### `POST /custom-mapping/{file_id}/activate` — Custom Grading (grade 6)

Melempar job ekstraksi kolom + GenAI pairing ke `custom_mapping_queue`.

---

### `POST /retention/trigger` — Trigger Retention Manual

Memerintahkan Celery Worker (`audit_queue`) untuk langsung menghapus log audit & akses yang kedaluwarsa dari StarRocks — tanpa menunggu jadwal tengah malam.

---

## 🛠 4. Troubleshooting

### Peringatan `Substantial drift` dari Celery

Peringatan `Substantial drift from celery@...` adalah **normal** jika Worker dijalankan di mesin lokal (WIB / UTC+7) namun terhubung ke Redis di server berzona waktu UTC. Proses tetap berjalan dengan benar.

### Status file mentok di `PROCESSING`

Cek dulu apakah worker untuk queue yang bersangkutan benar-benar dijalankan (lihat tabel di atas) — ini penyebab paling sering, terutama untuk `export_queue` dan `custom_mapping_queue` yang gampang lupa karena tidak selalu dibutuhkan saat dev.

```sql
SELECT file_id, grade, matching_task_status, reasoning_task_status,
       custom_mapping_task_status, export_status, sync_status
FROM uploaded_files WHERE file_id = '...';
```

### `ModuleNotFoundError` atau worker hang di Windows

Pastikan pakai `python -m celery` (bukan `celery` langsung) dan flag `--pool=solo` selalu ada di setiap perintah worker di atas.
