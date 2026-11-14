"""Hybrid multi-retriever system combining BM25, TF-IDF, and Dense Semantic Embeddings.

Features:
- BM25Okapi retrieval using rank_bm25
- TF-IDF retrieval using scikit-learn
- Dense semantic vector retrieval using SentenceTransformers (all-MiniLM-L6-v2)
- Reciprocal Rank Fusion (RRF) with configurable weights and rank constant k=60
- Paper-aware soft-filtering / routing
- Adjacent-chunk context expansion
"""
import os
import re
import pickle
from typing import List, Dict, Any, Optional, Tuple

# Ensure huggingface does not attempt remote network calls in sandboxed environments
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from chunker import EnhancedChunk, build_corpus


def tokenize_for_bm25(text: str) -> List[str]:
    """Tokenize and normalize text for BM25 matching."""
    # Retain alphanumeric tokens, lowercased, including hyphens and numbers
    text_clean = re.sub(r'[^\w\s\.\-]', ' ', text.lower())
    tokens = [t.strip('.-') for t in text_clean.split() if len(t.strip('.-')) > 1]
    return tokens


class BM25Retriever:
    """BM25 Okapi retriever."""

    def __init__(self, chunks: List[EnhancedChunk]):
        self.chunks = chunks
        self.tokenized_corpus = [tokenize_for_bm25(c.text) for c in chunks]
        self.bm25 = BM25Okapi(self.tokenized_corpus)

    def retrieve(self, query: str, top_k: int = 10, paper_filter: Optional[str] = None) -> List[Tuple[EnhancedChunk, float]]:
        tokens = tokenize_for_bm25(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        scored_chunks = []
        for idx, score in enumerate(scores):
            chunk = self.chunks[idx]
            if paper_filter and chunk.paper_key != paper_filter:
                score *= 0.5  # Soft penalty rather than hard exclusion
            scored_chunks.append((chunk, float(score)))

        scored_chunks.sort(key=lambda x: x[1], reverse=True)
        return scored_chunks[:top_k]


class TFIDFRetriever:
    """TF-IDF retriever using n-grams and sublinear term frequency."""

    def __init__(self, chunks: List[EnhancedChunk]):
        self.chunks = chunks
        self.vectorizer = TfidfVectorizer(
            stop_words="english",
            max_features=12000,
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        texts = [c.text for c in chunks]
        self.matrix = self.vectorizer.fit_transform(texts)

    def retrieve(self, query: str, top_k: int = 10, paper_filter: Optional[str] = None) -> List[Tuple[EnhancedChunk, float]]:
        q_vec = self.vectorizer.transform([query])
        sims = cosine_similarity(q_vec, self.matrix).flatten()
        scored = []
        for idx, score in enumerate(sims):
            chunk = self.chunks[idx]
            if paper_filter and chunk.paper_key != paper_filter:
                score *= 0.5
            scored.append((chunk, float(score)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


class DenseSemanticRetriever:
    """Dense embedding retriever using SentenceTransformers on CPU."""

    def __init__(self, chunks: List[EnhancedChunk], model_name: str = "all-MiniLM-L6-v2", cache_path: Optional[str] = None):
        self.chunks = chunks
        self.model = SentenceTransformer(model_name, device="cpu")
        
        if cache_path and os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                self.embeddings = pickle.load(f)
        else:
            texts = [f"{c.section_heading}\n{c.text}" for c in chunks]
            self.embeddings = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
            if cache_path:
                with open(cache_path, "wb") as f:
                    pickle.dump(self.embeddings, f)

    def retrieve(self, query: str, top_k: int = 10, paper_filter: Optional[str] = None) -> List[Tuple[EnhancedChunk, float]]:
        q_emb = self.model.encode([query], convert_to_numpy=True, normalize_embeddings=True)
        sims = np.dot(self.embeddings, q_emb.T).flatten()
        scored = []
        for idx, score in enumerate(sims):
            chunk = self.chunks[idx]
            if paper_filter and chunk.paper_key != paper_filter:
                score *= 0.5
            scored.append((chunk, float(score)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def reciprocal_rank_fusion(
    ranked_lists: List[List[Tuple[EnhancedChunk, float]]],
    weights: Optional[List[float]] = None,
    k: int = 60,
    top_k: int = 10,
) -> List[Tuple[EnhancedChunk, float]]:
    """Combine multiple ranked lists using Reciprocal Rank Fusion."""
    if not ranked_lists:
        return []
    if weights is None:
        weights = [1.0] * len(ranked_lists)

    scores: Dict[str, float] = {}
    chunk_map: Dict[str, EnhancedChunk] = {}

    for r_list, weight in zip(ranked_lists, weights):
        for rank, (chunk, _) in enumerate(r_list):
            cid = chunk.chunk_id
            chunk_map[cid] = chunk
            # Standard RRF formula: weight / (k + rank)
            scores[cid] = scores.get(cid, 0.0) + (weight / (k + rank + 1))

    sorted_cids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)
    return [(chunk_map[cid], scores[cid]) for cid in sorted_cids[:top_k]]


class HybridRetriever:
    """Unified hybrid retriever orchestrating BM25, TF-IDF, and Dense embeddings."""

    def __init__(self, chunks: List[EnhancedChunk], enable_dense: bool = True, embedding_cache_path: Optional[str] = None):
        self.chunks = chunks
        self.chunk_by_id = {c.chunk_id: c for c in chunks}
        self.bm25_retriever = BM25Retriever(chunks)
        self.tfidf_retriever = TFIDFRetriever(chunks)
        self.dense_retriever = (
            DenseSemanticRetriever(chunks, cache_path=embedding_cache_path)
            if enable_dense else None
        )

    def search(
        self,
        query: str,
        mode: str = "hybrid_rrf",  # "tfidf_only", "bm25_only", "hybrid_sparse", "hybrid_rrf"
        top_k: int = 10,
        paper_filter: Optional[str] = None,
        expand_adjacent: bool = False,
    ) -> List[EnhancedChunk]:
        """Search across corpus using selected retrieval mode."""
        if mode == "tfidf_only":
            scored = self.tfidf_retriever.retrieve(query, top_k=top_k, paper_filter=paper_filter)
            selected = [c for c, _ in scored]
        elif mode == "bm25_only":
            scored = self.bm25_retriever.retrieve(query, top_k=top_k, paper_filter=paper_filter)
            selected = [c for c, _ in scored]
        elif mode == "hybrid_sparse":
            # Combine BM25 + TF-IDF with RRF
            bm25_res = self.bm25_retriever.retrieve(query, top_k=top_k * 2, paper_filter=paper_filter)
            tfidf_res = self.tfidf_retriever.retrieve(query, top_k=top_k * 2, paper_filter=paper_filter)
            fused = reciprocal_rank_fusion([bm25_res, tfidf_res], weights=[1.2, 0.8], top_k=top_k)
            selected = [c for c, _ in fused]
        elif mode == "hybrid_rrf":
            # Combine BM25 + TF-IDF + Dense Embeddings
            bm25_res = self.bm25_retriever.retrieve(query, top_k=top_k * 2, paper_filter=paper_filter)
            tfidf_res = self.tfidf_retriever.retrieve(query, top_k=top_k * 2, paper_filter=paper_filter)
            if self.dense_retriever:
                dense_res = self.dense_retriever.retrieve(query, top_k=top_k * 2, paper_filter=paper_filter)
                fused = reciprocal_rank_fusion(
                    [bm25_res, tfidf_res, dense_res],
                    weights=[1.2, 0.8, 1.5],
                    top_k=top_k,
                )
            else:
                fused = reciprocal_rank_fusion([bm25_res, tfidf_res], weights=[1.2, 0.8], top_k=top_k)
            selected = [c for c, _ in fused]
        else:
            raise ValueError(f"Unknown retrieval mode: {mode}")

        if expand_adjacent and selected:
            # Expand top-ranked chunk with its adjacent neighbors if available
            expanded_results = []
            seen_ids = set()
            for c in selected:
                if c.chunk_id not in seen_ids:
                    seen_ids.add(c.chunk_id)
                    expanded_results.append(c)
                # If top chunk has adjacent neighbor in same section, include it
                if len(expanded_results) <= top_k and c.next_chunk_id and c.next_chunk_id in self.chunk_by_id:
                    next_c = self.chunk_by_id[c.next_chunk_id]
                    if next_c.section_heading == c.section_heading and next_c.chunk_id not in seen_ids:
                        seen_ids.add(next_c.chunk_id)
                        expanded_results.append(next_c)
            selected = expanded_results[:top_k]

        return selected
