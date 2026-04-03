import os
from typing import List

from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def _client_openai() -> AsyncOpenAI:
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _client = AsyncOpenAI(api_key=key)
    return _client


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    words = text.split()
    if not words:
        return []
    chunks: List[str] = []
    step = max(1, chunk_size - overlap)
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks


async def embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    client = _client_openai()
    response = await client.embeddings.create(model="text-embedding-3-small", input=texts)
    return [item.embedding for item in response.data]


async def embed_query(text: str) -> List[float]:
    vecs = await embed_texts([text])
    return vecs[0]
