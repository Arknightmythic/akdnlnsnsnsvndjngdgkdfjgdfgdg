from langchain_qdrant import QdrantVectorStore, RetrievalMode, FastEmbedSparse
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance

from dotenv import load_dotenv
from pathlib import Path
import hashlib
import os
import re

from chatbot.knowledge.parser import clean_markdown

load_dotenv()

MODEL_BASE_URL = os.getenv("MODEL_BASE_URL")
QDRANT_URL = os.getenv("QDRANT_URL")
COLLECTION_NAME = os.getenv("COLLECTION_NAME")

class Ingestor:
    def __init__(self):
        self._qdrant_client = QdrantClient(host="172.16.12.98")
        self._embedding = OllamaEmbeddings(
            base_url=MODEL_BASE_URL,
            model="qwen3-embedding:8b"
        )
        self._sparse_embedding = FastEmbedSparse()
        
        self._vector_store = QdrantVectorStore.from_documents(
            documents=[],
            embedding=self._embedding,
            sparse_embedding=self._sparse_embedding,
            url=QDRANT_URL,
            collection_name=COLLECTION_NAME,
            retrieval_mode=RetrievalMode.HYBRID,
            force_recreate=False
        )

        self._processed_file_hashes, self._processed_chunk_hashes = self._get_exists_hashed()

    def _get_exists_hashed(self) -> tuple[set, set]:
        offset = None
        processed_file_hashes = set()
        processed_chunk_hashes = set()
        
        try:
            while True:
                points, offset = self._vector_store.client.scroll(
                    collection_name=COLLECTION_NAME,
                    limit=10_000,
                    with_payload=True,
                    offset=offset
                )
                if not points:
                    break

                for point in points:
                    meta = point.payload.get("metadata", {})
                    f_hash = meta.get("file_hash")
                    c_hash = meta.get("chunk_hash")
                    if f_hash:
                        processed_file_hashes.add(f_hash)
                    if c_hash:
                        processed_chunk_hashes.add(c_hash)

                if offset is None:
                    break
        except Exception:
            pass
            
        return processed_file_hashes, processed_chunk_hashes
    
    def _compute_file_hash(self, file_path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def ingest_file(self, file_path: Path):
        file_hash = self._compute_file_hash(file_path)
        
        # Level 1: File-Level Check
        if file_hash in self._processed_file_hashes:
            print(f"File {file_path.name} tidak ada perubahan (hash cocok). Melewati proses...")
            return
            
        path_str = str(file_path)

        if "markdown" in path_str or ".md" in path_str:
            content_type = "text"
            doc_name = file_path.name
        elif "tables" in path_str:
            content_type = "tables"
            doc_name = file_path.parent.name
        elif "images_desc" in path_str:
            content_type = "image"
            doc_name = file_path.parent.name
        else:
            content_type = "unknown"
            doc_name = file_path.name

        content = file_path.read_text(encoding="utf-8")

        base_metadata = {
            "doc_name": doc_name,
            "content_type": content_type,
            "file_hash": file_hash,
            "source_file": doc_name
        }

        if content_type == "text":
            pages = clean_markdown(content)
            documents = []
            
            for idx, page in enumerate(pages, start=1):
                chunk_hash = hashlib.sha256(page.encode("utf-8")).hexdigest()
                
                # Level 2: Chunk-Level Check
                if chunk_hash in self._processed_chunk_hashes:
                    print(f"    FAQ #{idx} sudah ada di Qdrant. Skip duplikat.")
                    continue
                    
                metadata = base_metadata.copy()
                metadata.update({
                    "faq": idx,
                    "chunk_hash": chunk_hash
                })
                documents.append(Document(page_content=page, metadata=metadata))

            if not documents:
                print(f"Tidak ada FAQ baru yang perlu ditambahkan dari {file_path.name}.")
            else:
                print(f"    Menambahkan {len(documents)} FAQ baru ke collection...")
                self._vector_store.add_documents(documents)

        # Update cache di memory
        self._processed_file_hashes.add(file_hash)
        if content_type == "text":
            for doc in documents:
                self._processed_chunk_hashes.add(doc.metadata["chunk_hash"])

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Ingest Markdown files to Qdrant Vector Database")
    parser.add_argument("file_path", type=str, help="Path ke file markdown yang akan di-ingest (contoh: chatbot/knowledge/data/md/faq_v1_50.md)")
    
    args = parser.parse_args()
    
    md_path = Path(args.file_path)
    if not md_path.exists():
        print(f" Error: File tidak ditemukan di {md_path}")
        sys.exit(1)
        
    print(f" Memulai proses ingestion untuk file: {md_path}")
    try:
        ingestor = Ingestor()
        ingestor.ingest_file(md_path)
        print(" Ingestion berhasil diselesaikan!")
    except Exception as e:
        import traceback
        print(f"❌ Terjadi kesalahan saat ingestion: {e}")
        traceback.print_exc()
        sys.exit(1)