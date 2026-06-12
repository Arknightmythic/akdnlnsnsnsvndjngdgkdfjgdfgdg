from langchain_qdrant import QdrantVectorStore, RetrievalMode, FastEmbedSparse
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document
from qdrant_client import QdrantClient
from dotenv import load_dotenv  
import os

load_dotenv()


QDRANT_URL = os.getenv("QDRANT_URL")
COLLECTION_NAME = os.getenv("COLLECTION_NAME")

class Retriever:
    def __init__(self):
        self._qdrant_client = QdrantClient(host="172.16.12.98")
        self._embedding = OllamaEmbeddings(
            base_url="http://172.16.12.98:11434",
            model="qwen3-embedding:8b",
        )
        self._sparse_embedding = FastEmbedSparse()
        self._vector_store = QdrantVectorStore.from_existing_collection(
            embedding=self._embedding,
            sparse_embedding=self._sparse_embedding,
            url=QDRANT_URL,
            collection_name=COLLECTION_NAME,
            retrieval_mode=RetrievalMode.HYBRID,
        )

    def hybrid_search(self, query: str, k: int = 5)-> list[Document]:
        results = self._vector_store.similarity_search(query=query, k=k, filter=None)
        return results