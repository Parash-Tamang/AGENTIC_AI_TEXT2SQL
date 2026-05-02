# app/src/knowledgebase/setup/client.py
import os
import chromadb
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

VECTOR_STORE_PATH = os.getenv("VECTOR_STORE_PATH", "./vector_store/chroma")

COLLECTION_NAME = os.getenv("VECTOR_COLLECTION_NAME", "AdventureWorksSchema")

_embedding_fn = None
_client = None


def get_embedding_function():
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = ONNXMiniLM_L6_V2()
    return _embedding_fn


def get_chroma_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=VECTOR_STORE_PATH)
    return _client


def get_collection(collection_name: str = None):
    client = get_chroma_client()
    name = collection_name or COLLECTION_NAME
    return client.get_or_create_collection(
        name=name,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def get_existing_collection(collection_name: str):
    client = get_chroma_client()
    existing_collections = client.list_collections()
    for col in existing_collections:
        if col.name == collection_name:
            return client.get_collection(
                name=collection_name,
                embedding_function=get_embedding_function(),  # ✅ this was missing
            )
    return None


def collection_exists(collection_name: str) -> bool:
    try:
        client = get_chroma_client()
        existing_collections = client.list_collections()
        collection_names = [col.name for col in existing_collections]
        return collection_name in collection_names
    except Exception as e:
        print(f"Error checking collection existence: {str(e)}")
        return False
