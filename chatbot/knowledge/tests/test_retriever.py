import json
import sys
from pathlib import Path

# Tambahkan root directory ke sys.path agar bisa import chatbot
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from chatbot.knowledge.retriever import Retriever

def main():
    print("🔄 Menginisialisasi Retriever (koneksi ke Qdrant & Ollama)...")
    try:
        retriever = Retriever()
    except Exception as e:
        print(f"❌ Gagal inisialisasi Retriever: {e}")
        return

    # Pertanyaan simulasi (mirip dengan yang ada di FAQ)
    query = "Bagaimana cara melihat jumlah data padan batch terakhir?"
    print(f"\n🔍 Mencari jawaban untuk: '{query}'")
    
    try:
        # Panggil hybrid search (minta 3 hasil teratas)
        results = retriever.hybrid_search(query=query, k=3)
        
        output_data = []
        for i, doc in enumerate(results, start=1):
            print(f"\n--- Hasil #{i} ---")
            print(f"Metadata: {doc.metadata}")
            # Potong content agar tidak kepanjangan saat di-print
            preview = doc.page_content[:200].replace('\n', ' ') + "..."
            print(f"Content: {preview}")
            
            output_data.append({
                "rank": i,
                "metadata": doc.metadata,
                "page_content": doc.page_content
            })
            
        # Simpan hasilnya ke JSON agar user bisa melihat detail lengkapnya
        output_path = Path(__file__).parent / "retriever_results.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=4)
            
        print(f"\n✅ Pencarian sukses! Detail lengkap disimpan ke: {output_path.name}")
        
    except Exception as e:
        print(f"❌ Terjadi kesalahan saat mencari: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
