# Integrasi Reasoning Service (Celery Event-Driven)

> **Untuk Tim Data Engineer / Matching Service**

Menginfokan bahwa modul **Reasoning AI** sekarang sudah dikonversi ke arsitektur **Celery Worker (Event-Driven)**. Tujuannya agar sistem lebih tangguh, proses AI tidak memblokir server FastAPI utama, dan dapat diproses secara asinkron/paralel (*scale up*).

## 1. Perubahan pada `processing/handler.py`

Untuk mengintegrasikan *Matching Service* dengan Celery *Reasoning*, kami telah menyisipkan sepotong kode (*trigger*) di bagian akhir proses Matching (tepatnya di dalam metode `process_file`).

Setelah semua logika `process_grade_X` selesai berjalan dan *database* ter-*update*, kode berikut digunakan untuk mengirim *task* ke antrean Redis:

```python
# Trigger Reasoning Celery Task as a background event
try:
    from reasoning.tasks import process_file_reasoning
    process_file_reasoning.delay(file_id)
    print(f"Enqueued reasoning task for {file_id}")
except Exception as e:
    print(f"Failed to enqueue reasoning task for {file_id}: {e}")
```

*Note: Pemanggilan `.delay(file_id)` ini murni **asynchronous/non-blocking**. Waktu respons dari API `/match/` tidak akan bertambah lama sama sekali.*

---

## 2. Dokumentasi Perubahan Skema Database

Sistem *Reasoning* kami juga membutuhkan beberapa perubahan dan penambahan pada skema *database* StarRocks. Berikut adalah struktur dan hubungannya:

### A. Tabel Eksisting: `uploaded_files`
Digunakan sebagai tabel utama *lifecycle* dari satu *file* yang diunggah. Kami menambahkan satu kolom untuk melacak proses AI.

- **[BARU] Kolom:** `reasoning_status VARCHAR(30) DEFAULT 'PENDING'`
- **Siklus Hidup (Life Cycle):**
  1. `PENDING`: Nilai otomatis *(default)* saat file baru masuk.
  2. `PROCESSING`: Di-set oleh Celery Worker tepat saat mulai menarik data yang berstatus `MANUAL_REVIEW`.
  3. `COMPLETED`: Di-set ketika sistem AI sudah sukses membedah dan memproses semua baris dalam *file* tersebut.
  4. `SKIPPED`: Jika ternyata di dalam *file* tersebut tidak ada satupun baris berstatus `MANUAL_REVIEW` (semuanya *Auto Match* atau *Auto Unmatch*), sehingga proses AI dilewati.
  5. `FAILED`: Jika Celery gagal, koneksi Redis mati, atau API LLM sedang *down*. (Worker dirancang untuk mencoba ulang otomatis maksimal 3x).

### B. Tabel Eksisting: `institution`
Tabel tujuan akhir yang menampung detail baris data yang telah di-*match*.

- **[BARU] Kolom:** `reason VARCHAR(65533)`
  - Menampung teks penjelasan dalam Bahasa Indonesia mengapa data tidak cocok (contoh: *"Nama berbeda (Joko vs Jaka), Tanggal Lahir kosong"*).
- **[BARU] Kolom:** `pattern_name VARCHAR(255)`
  - Menyimpan kode unik dari pola ketidakcocokan (contoh: `P001_NAMA_BEDA__TGLLAHIR_KOSONG`). Sangat berguna bagi tim analitik untuk menghitung jenis *error* / ketidaksesuaian terbanyak di suatu institusi.
- **[BARU] Kolom:** `reasoning_source VARCHAR(20)`
  - Akan diisi teks **`LLM`** atau **`CACHE`**. Berfungsi sebagai jejak audit untuk membedakan mana baris yang dianalisis langsung oleh *Language Model* (murni AI), dan mana baris yang menggunakan hasil penghematan komputasi (*Cache*).

### C. Tabel Baru: `reasoning_patterns`
Tabel ini khusus milik layanan *Reasoning* sebagai fondasi fitur **Super Caching** kami. Tabel ini menyimpan *hash* dari setiap variasi *error*.

- **Kolom Kunci:** 
  - `pattern_hash` (Primary Key).
  - `reason_template` (Template bahasa baku dari AI, dilengkapi *placeholder* seperti `{incoming.nama_lengkap}`).
  - `hit_count` (Menghitung efektivitas *cache*: sudah berapa ratus/ribu kali pola ini berhasil digunakan ulang).
- **Relasi dengan Tim Lain:** Tabel ini sifatnya terisolasi (independen) untuk kebutuhan internal AI. Tim Data Engineer tidak perlu merelasikan, membaca, ataupun memanipulasi tabel ini. Ia berfungsi penuh sebagai "otak memori" dari sistem *Reasoning AI*.
