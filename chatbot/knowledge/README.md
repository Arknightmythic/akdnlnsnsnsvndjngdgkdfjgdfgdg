# Modul Basis Pengetahuan (Knowledge Base) Synchrono

Modul ini bertanggung jawab atas alur _End-to-End_ (E2E) _Retrieval-Augmented Generation_ (RAG) untuk AI Agent Synchrono. Modul ini menangani mulai dari _parsing_ dokumen mentah, proses _embedding_ menggunakan metode _dense_ & _sparse vector_, penyimpanan ke dalam _Vector Database_ (Qdrant), hingga pencarian kembali secara efisien saat AI sedang beroperasi.

## 🏗️ Arsitektur & Komponen Utama

- **`ingestor.py`**: _Pipeline_ untuk memasukkan data. Melakukan pembacaan file mentah, membuat kalkulasi _hash_ agar tidak ada data ganda (idempotent), melakukan _embed_ teks, dan menyimpannya di Qdrant via `QdrantVectorStore` dari Langchain.
- **`retriever.py`**: _Pipeline_ pencarian data. Terhubung ke _collection_ Qdrant dan melakukan pencarian **Hybrid Search** (menggabungkan pencarian makna/Dense dan kata kunci/Sparse) untuk memberikan hasil yang paling relevan.
- **`parser.py`**: Pembersih (parser) teks *custom* yang dirancang untuk membersihkan file Markdown dan secara otomatis menyisipkan _tag_ XML semantic (`<question>` dan `<answer>`) agar AI RAG kita memahami konteks tanpa tertukar.
- **`data/md/`**: Repositori data lokal tempat seluruh sumber file Markdown (misalnya FAQ) disimpan.
- **`tests/`**: Berisi _script_ pengujian (contoh: `test_parse_faq.py`) untuk memvalidasi dan melakukan pratinjau struktur data (JSON) sebelum benar-benar di-_ingest_ ke Qdrant.

---

## 🚀 Alur Kerja Pipeline End-to-End (E2E)

### 1. Menambahkan Data Baru (Knowledge Generation)
Untuk menambahkan FAQ atau pengetahuan baru, buat atau perbarui file `.md` di dalam folder `data/md/`.
- Gunakan `faq_template.md` yang telah disediakan sebagai acuan/panduan.
- Pisahkan setiap _entry_ FAQ baru menggunakan `<!-- page break -->`.
- Format setiap pertanyaannya dengan awalan `Q: `. Secara otomatis, `parser.py` akan mengonversinya menjadi _tag_ XML terstruktur tanpa perlu penulisan manual.

### 2. Pratinjau Data (Opsional tapi Direkomendasikan)
Sebelum melakukan _ingestion_ (memasukkan data) ke _database_ production, Anda bisa melakukan pratinjau bagaimana struktur data akan dibaca oleh sistem.
```bash
# Pastikan Anda menggunakan virtual environment yang benar
python chatbot/knowledge/tests/test_parse_faq.py
```
Silakan cek hasil pada file `chatbot/knowledge/tests/parsed_result.json` untuk memastikan struktur dan _metadata_ ("faq", "source", "file_hash") sudah benar.

### 3. Ingestion (Memasukkan data ke Qdrant)
Karena `ingestor.py` sudah dilengkapi kapabilitas Command Line Interface (CLI), Anda bisa langsung mengeksekusinya langsung melalui Terminal / Bash. Cukup berikan path file sebagai argumennya. Sistem ini juga bersifat idempotent (aman dari duplikasi data).

```bash
# Pastikan Anda berada di root folder project
uv run python -m chatbot.knowledge.ingestor chatbot/knowledge/data/md/faq_v1_50.md
```

Atau jika Anda ingin memanggilnya di dalam kode Python:
```python
from pathlib import Path
from chatbot.knowledge.ingestor import Ingestor

ingestor = Ingestor()
ingestor.ingest_file(Path("chatbot/knowledge/data/md/faq_v1_50.md"))
```

### 4. Retrieval (Pencarian oleh AI)
Saat sesi _chat_ berlangsung, _handler_ atau AI Agent akan memanggil _class_ `Retriever` untuk mencari konteks bisnis yang tepat.
```python
from chatbot.knowledge.retriever import Retriever

retriever = Retriever()

# Mencari 3 FAQ paling relevan (menggunakan metode Hybrid Search)
results = retriever.search("Berapa jumlah data yang padan?", top_k=3)

for doc in results:
    print(f"Content: {doc.page_content}")
    print(f"Metadata: {doc.metadata}")
```

---

## 🛠️ Konfigurasi Environment

Pastikan variabel-variabel lingkungan berikut sudah terpasang di dalam file `.env` root aplikasi Anda:

```env
MODEL_BASE_URL="http://localhost:11434"
QDRANT_URL="http://localhost:6333"
COLLECTION_NAME="synchrono_faq_collection" # (Atau sesuaikan dengan nama collection yang disepakati)
```

## 🔍 Fitur & Praktik Terbaik (Best Practices)
- **Aman dari Duplikat (Idempotency)**: Ingestor akan melacak metadata `file_hash` di Qdrant. Melakukan eksekusi (hit) ingestor berkali-kali pada file yang sama tidak akan melahirkan tumpukan data ganda.
- **Hybrid Search**: Pencarian kita memanfaatkan `Qwen3-embedding:8b` untuk mendeteksi makna kata (_dense semantic_) ditambah `FastEmbedSparse` untuk mencocokkan kata kunci unik secara eksak (_sparse keyword_). Hasilnya dijamin sangat akurat.
- **Auto-Tagging AI Friendly**: Tim penulis FAQ tidak perlu pusing belajar struktur *prompting* XML. Cukup ketik biasa menggunakan bahasa natural yang diawali dengan `Q: `, biarkan kode parser yang bekerja menerjemahkannya ke format rigid yang disukai LLM.
