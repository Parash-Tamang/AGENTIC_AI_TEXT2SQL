import logging
import os

import chromadb
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

from src.knowledgebase.config.vector_setting import VectorSettings, DEFAULT_SETTINGS

logger = logging.getLogger(__name__)


class Embedder:
    """
    Wraps ChromaDB's ONNX embedding function to produce embeddings.
    Uses ONNXMiniLM_L6_V2 for efficient, CPU-based embedding generation.
    """

    def __init__(self, settings: VectorSettings = DEFAULT_SETTINGS):
        self._embedding_fn = ONNXMiniLM_L6_V2()
        logger.info("✅ Embedder ready: ONNXMiniLM_L6_V2")

    def embed(self, text: str) -> list[float]:
        """Embed a single string."""
        result = self._embedding_fn([text])
        return result[0] if result else []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of strings efficiently in one pass."""
        return self._embedding_fn(texts)


__all__ = ["Embedder"]
