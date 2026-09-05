"""Structure-aware, deterministic document chunking."""

from real_estate_agent.rag.chunking.models import ChunkingConfig, DocumentChunk
from real_estate_agent.rag.chunking.splitter import chunk_document

__all__ = ["ChunkingConfig", "DocumentChunk", "chunk_document"]
