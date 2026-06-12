import os
import sys
import json
import hashlib
from pathlib import Path

# Setup path agar bisa import dari chatbot.knowledge
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(project_root))

from chatbot.knowledge.parser import clean_markdown

def test_parse_to_json(md_file_path: str, output_json_path: str):
    """
    Membaca file markdown FAQ, melakukan parsing/cleansing,
    lalu menyimpannya sebagai JSON agar bisa di-review sebelum masuk ke Qdrant.
    """
    if not os.path.exists(md_file_path):
        print(f"Error: File tidak ditemukan di {md_file_path}")
        return

    # Baca file markdown
    with open(md_file_path, "r", encoding="utf-8") as file:
        md_text = file.read()

    # Parsing menggunakan fungsi yang sama dengan ingestor.py
    chunks = clean_markdown(md_text)
    
    documents_to_ingest = []
    
    # Buat simulasi Document object
    for i, text_chunk in enumerate(chunks):
        if not text_chunk.strip():
            continue
            
        chunk_hash = hashlib.sha256(text_chunk.encode()).hexdigest()
        
        # Simulasi struktur Document dari Langchain
        doc = {
            "page_content": text_chunk,
            "metadata": {
                "source": os.path.basename(md_file_path),
                "file_hash": chunk_hash,
                "faq": i + 1
            }
        }
        documents_to_ingest.append(doc)

    # Simpan hasil ke dalam JSON untuk direview
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(documents_to_ingest, f, indent=4, ensure_ascii=False)
        
    print(f"Berhasil mem-parsing {len(documents_to_ingest)} dokumen.")
    print(f"Hasil JSON dapat dilihat di: {output_json_path}")

if __name__ == "__main__":
    # Tentukan path file markdown yang akan dites (faq.md)
    current_dir = Path(__file__).resolve().parent
    knowledge_dir = current_dir.parent
    md_path = knowledge_dir / "data" / "md" / "faq_v1_50.md"
    
    # Path output JSON
    output_path = current_dir / "parsed_result.json"
    
    test_parse_to_json(str(md_path), str(output_path))
