"""Local embeddings via fastembed (ONNX, no server, no API key)."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Iterable

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# bge-style models expect a query instruction prefix for retrieval queries.
QUERY_PREFIXES = {
    "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-base-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-large-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "intfloat/multilingual-e5-large": "query: ",
}
# e5-style models also expect a passage prefix on documents.
DOC_PREFIXES = {"intfloat/multilingual-e5-large": "passage: "}


@lru_cache(maxsize=2)
def _model(name: str):
    from fastembed import TextEmbedding

    cache = os.environ.get("EZTUDY_MODEL_CACHE") or os.path.expanduser("~/.cache/eztudy/models")
    return TextEmbedding(model_name=name, cache_dir=cache)


class Embedder:
    def __init__(self, model_name: str):
        self.model_name = model_name

    @property
    def dim(self) -> int:
        return len(self.embed_query("dimension probe"))

    def embed_documents(self, texts: Iterable[str]) -> list[list[float]]:
        prefix = DOC_PREFIXES.get(self.model_name, "")
        return [v.tolist() for v in _model(self.model_name).embed([prefix + t for t in texts], batch_size=32)]

    def embed_query(self, text: str) -> list[float]:
        prefix = QUERY_PREFIXES.get(self.model_name, "")
        return next(iter(_model(self.model_name).embed([prefix + text]))).tolist()
