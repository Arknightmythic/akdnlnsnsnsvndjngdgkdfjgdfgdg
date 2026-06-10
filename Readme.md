# SynchronoAPI

> Backend berbasis **FastAPI** untuk memproses, mencocokkan (**Data Matching**), dan memberikan penilaian (**Grading**) pada data CSV secara _real-time_ maupun _background processing_.

Sistem ini menggunakan **StarRocks** sebagai database analitik utama, **MinIO** sebagai _object storage_, dan **Celery + Redis** untuk eksekusi tugas terjadwal (_background tasks_ & _retention_).

---

## Daftar Isi

- [Prasyarat Sistem](#-prasyarat-sistem)
- [Persiapan Lingkungan](#-1-persiapan-lingkungan)
- [Menjalankan Layanan](#-2-menjalankan-layanan)
- [Endpoint Penting](#-3-endpoint-penting)
- [Troubleshooting](#-4-troubleshooting)

---

## 📋 Prasyarat Sistem

Pastikan layanan berikut sudah berjalan dan dapat diakses sebelum memulai:

| Layanan        | Keterangan                                       |
| -------------- | ------------------------------------------------ |
| **StarRocks**  | Database analitik utama (MySQL Dialect)          |
| **MinIO**      | Object storage kompatibel S3                     |
| **Redis**      | Broker & backend untuk Celery                    |
| **Python 3.x** | Direkomendasikan menggunakan Virtual Environment |

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

Dependensi utama meliputi: FastAPI, Uvicorn, Polars, DuckDB, SQLAlchemy, Celery, dan Redis.

### Langkah 3 — Konfigurasi Environment Variables

Buat file `.env` di root directory dan isi variabel berikut:

```env
# ── Database (StarRocks) ───────────────────────────────
STARROCKS_HOST=127.0.0.1
STARROCKS_PORT=9030
STARROCKS_USER=root
STARROCKS_PASSWORD=
STARROCKS_DATABASE=synchrono

# ── Object Storage (MinIO) ────────────────────────────
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=your_access_key
MINIO_SECRET_KEY=your_secret_key
RAW_BUCKET_NAME=raw-zone
CURATED_BUCKET_NAME=curated-zone

# ── Task Queue (Celery & Redis) ───────────────────────
REDIS_URL=redis://172.16.12.98:6378/0
```

---

## 🏃 2. Menjalankan Layanan

Sistem terdiri dari **3 komponen** yang harus dijalankan secara terpisah. Buka **3 terminal berbeda** dan pastikan Virtual Environment aktif di masing-masing terminal.

### Terminal 1 — FastAPI Server

Menerima request dari frontend dan menangani proses upload hingga grading.

```bash
python main.py
```

Server berjalan di: `http://localhost:9191`

---

### Terminal 2 — Celery Worker audit retention

Mengeksekusi tugas berat di background seperti sinkronisasi data dan retention log.

```bash
python -m celery -A worker.celery_app worker --pool=solo --loglevel=info
```

> **⚠️ Penting untuk Windows:** Wajib menggunakan `python -m celery` dan flag `--pool=solo`. Tanpa flag ini, proses Celery akan _hang_ atau memunculkan `ModuleNotFoundError`.

---

### Terminal 3 — Celery Beat (Scheduler)

Memicu tugas terjadwal (seperti `execute_audit_retention`) sesuai konfigurasi cron di `worker.py`.

```bash
python -m celery -A worker.celery_app beat --loglevel=info
```

---

## 🧪 3. Endpoint Penting

### `POST /files/` — Upload & Ingestion (SSE)

Mengonversi CSV ke Parquet, mengupload ke MinIO, dan mencetak progress secara _real-time_ via Server-Sent Events.

- **Format request:** `multipart/form-data`
- **Field:** `institution_name`, `files`

---

### `POST /match/?file_id={id}` — Data Matching

Menjalankan komputasi **Jaro-Winkler** via DuckDB secara batch antara data _incoming_ (di MinIO) dan tabel `master` di StarRocks.

---

### `POST /retention/trigger` — Trigger Retention Manual

Memerintahkan Celery Worker untuk langsung menghapus log audit & akses yang kedaluwarsa dari StarRocks — tanpa menunggu jadwal tengah malam.

---

### Peringatan `Substantial drift` dari Celery

Peringatan `Substantial drift from celery@...` adalah **normal** jika Worker dijalankan di mesin lokal (WIB / UTC+7) namun terhubung ke Redis di server berzona waktu UTC. Proses tetap berjalan dengan benar.


---
### 👷‍♂️ Menjalankan Background Workers (Celery)

Aplikasi ini menggunakan Celery dan Redis untuk memproses tugas-tugas berat (*asynchronous tasks*) di latar belakang secara paralel. 

> **⚠️ Prasyarat:** Pastikan server **Redis** sudah menyala dan dapat diakses sebelum menjalankan *worker*.

Buka terminal/Command Prompt baru untuk masing-masing *worker* (berada di *root directory* proyek), lalu jalankan perintah berikut:

**1. Matching Worker**
Bertugas mengeksekusi komputasi pencocokan data jutaan baris menggunakan DuckDB dan Polars.
```bash
python -m celery -A processing.celery_app worker -Q matching_queue --pool=solo --loglevel=info

```

**2. Reasoning Worker**
Bertugas memproses antrean AI (LLM) untuk memberikan alasan otomatis pada data yang tidak cocok (*Micro-batching*).

```bash
python -m celery -A reasoning.celery_app worker -Q reasoning_queue --pool=solo --loglevel=info

```

**3. Audit Worker**
Bertugas mencatat seluruh riwayat aktivitas dan *event* sistem ke dalam database secara *non-blocking*.

```bash
python -m celery -A audit.celery_app worker -Q audit_queue --pool=solo --loglevel=info

```

**4. General Processing Queue**
Bertugas menangani tugas-tugas *default* atau proses umum lainnya yang tidak masuk ke dalam antrean spesifik di atas.

```bash
python -m celery -A processing.celery_app worker -Q celery --pool=solo --loglevel=info

```

*Catatan: Argumen `--pool=solo` digunakan untuk kompatibilitas OS Windows. Jika aplikasi di-deploy ke server Linux/Production (seperti Ubuntu atau container Docker), Anda bisa menghapus `--pool=solo` dan menggantinya dengan argumen concurrency (contoh: `--concurrency=4`) agar worker dapat memanfaatkan multi-core CPU secara maksimal.*

```