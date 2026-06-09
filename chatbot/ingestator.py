from langchain_qdrant import QdrantVectorStore, RetrievalMode, FastEmbedSparse
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document
from qdrant_client import QdrantClient
from dotenv import load_dotenv
from pathlib import Path
import hashlib
import os
import re

load_dotenv()

MODEL_BASE_URL = os.getenv("MODEL_BASE_URL")
QDRANT_URL = os.getenv("QDRANT_URL")
COLLECTION_NAME = os.getenv("COLLECTION_NAME")

class Ingestator:
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
            retrieval_mode=RetrievalMode.HYBRID,
            force_recreate=False

        )
        self._processed_hashes = self._get_exists_hashed()

    def _get_exists_hashed(self)-> set:
        offset = None
        processed_hashes = set()
        while True:
            points, offset = self._vector_store.client.scroll(
                collection_name=COLLECTION_NAME,
                limit=10_000,
                with_payload=True,
                offset=offset
            )
            if not points:
                break

            processed_hashes.update(point.payload.get("metadata", {}).get("file_hash") for point in points if point.payload.get("metadata", {}).get("file_hash") is not None)

            if offset in None:
                break
        return processed_hashes
    
    def _compute_file_hash(self, file_path: Path)-> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "r", encoding="utf-8") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def ingest_file(self, file_path: Path, processed_hashes: set):
        file_hash = self._compute_file_hash(file_path)
        path_str = str(file_path)

        if "markdown" in path_str:
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
            pages = content.split("<!-- page break -->")
            documents = []
            for idx, page in enumerate(pages, start=1):
                metadata = base_metadata.copy()
                metadata.update({"page": idx})
                documents.append(Document(page_content=page, metadata=metadata))

            self._vector_store.add_documents(documents)

        self._processed_hashes.add(file_hash)