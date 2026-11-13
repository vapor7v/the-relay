"""PDF text extraction → chunking → TF-IDF index.

Builds a searchable index over the three arXiv papers.
Each chunk carries metadata: paper key, page number(s), and character offsets.
"""
import os
import re
import json
import pickle
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from PyPDF2 import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from config import PAPERS, PAPERS_DIR


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Chunk:
    paper_key: str        # e.g. "attention"
    paper_title: str
    page_start: int       # 1-indexed
    page_end: int
    text: str
    char_start: int       # offset within full paper text
    char_end: int

    def citation_label(self) -> str:
        if self.page_start == self.page_end:
            return f"[{self.paper_title}, p.{self.page_start}]"
        return f"[{self.paper_title}, pp.{self.page_start}-{self.page_end}]"


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------
def extract_paper_text(paper_key: str) -> tuple[str, list[tuple[int, int]]]:
    """Return (full_text, [(page_num, char_offset), ...])."""
    info = PAPERS[paper_key]
    path = os.path.join(PAPERS_DIR, info["file"])
    reader = PdfReader(path)
    full_text = ""
    page_offsets: list[tuple[int, int]] = []
    for i, page in enumerate(reader.pages):
        offset = len(full_text)
        text = page.extract_text() or ""
        # Clean up common PDF extraction artifacts
        text = re.sub(r'\s+', ' ', text).strip()
        page_offsets.append((i + 1, offset))
        full_text += text + "\n"
    return full_text, page_offsets


def _page_for_offset(page_offsets: list[tuple[int, int]], offset: int) -> int:
    """Given character offset, return 1-indexed page number."""
    page = 1
    for pnum, poff in page_offsets:
        if poff <= offset:
            page = pnum
        else:
            break
    return page


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def chunk_text(
    paper_key: str,
    paper_title: str,
    full_text: str,
    page_offsets: list[tuple[int, int]],
    chunk_size: int = 1000,
    overlap: int = 100,
) -> List[Chunk]:
    """Split paper text into overlapping chunks with metadata."""
    chunks = []
    start = 0
    while start < len(full_text):
        end = min(start + chunk_size, len(full_text))
        # Try to break at a sentence boundary
        if end < len(full_text):
            last_period = full_text.rfind('.', start, end)
            if last_period > start + chunk_size // 2:
                end = last_period + 1
        text = full_text[start:end].strip()
        if len(text) > 20:  # skip tiny fragments
            page_start = _page_for_offset(page_offsets, start)
            page_end = _page_for_offset(page_offsets, end - 1)
            chunks.append(Chunk(
                paper_key=paper_key,
                paper_title=paper_title,
                page_start=page_start,
                page_end=page_end,
                text=text,
                char_start=start,
                char_end=end,
            ))
        start = end - overlap if end < len(full_text) else end
    return chunks


# ---------------------------------------------------------------------------
# TF-IDF index
# ---------------------------------------------------------------------------
class PaperIndex:
    """TF-IDF search index over paper chunks."""

    def __init__(self):
        self.chunks: List[Chunk] = []
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.tfidf_matrix = None

    def build(self, chunk_size: int = 1000, overlap: int = 100):
        """Extract, chunk, and index all papers."""
        self.chunks = []
        for key, info in PAPERS.items():
            full_text, page_offsets = extract_paper_text(key)
            paper_chunks = chunk_text(
                paper_key=key,
                paper_title=info["title"],
                full_text=full_text,
                page_offsets=page_offsets,
                chunk_size=chunk_size,
                overlap=overlap,
            )
            self.chunks.extend(paper_chunks)
            print(f"  {key}: {len(paper_chunks)} chunks from {len(page_offsets)} pages")

        self.vectorizer = TfidfVectorizer(
            stop_words="english",
            max_features=10000,
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        texts = [c.text for c in self.chunks]
        self.tfidf_matrix = self.vectorizer.fit_transform(texts)
        print(f"Index built: {len(self.chunks)} chunks, {self.tfidf_matrix.shape[1]} features")

    def search(self, query: str, top_k: int = 3) -> List[Chunk]:
        """Return top-k most relevant chunks for a query."""
        if self.vectorizer is None:
            raise RuntimeError("Index not built yet. Call build() first.")
        query_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self.tfidf_matrix).flatten()
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            if scores[idx] > 0.01:  # minimum relevance threshold
                results.append(self.chunks[idx])
        return results

    def save(self, path: str):
        with open(path, 'wb') as f:
            pickle.dump({'chunks': self.chunks, 'vectorizer': self.vectorizer,
                         'matrix': self.tfidf_matrix}, f)

    def load(self, path: str):
        with open(path, 'rb') as f:
            data = pickle.load(f)
        self.chunks = data['chunks']
        self.vectorizer = data['vectorizer']
        self.tfidf_matrix = data['matrix']


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    idx = PaperIndex()
    idx.build(chunk_size=1000, overlap=100)
    print("\n--- Test search: 'multi-head attention' ---")
    results = idx.search("multi-head attention", top_k=3)
    for r in results:
        print(f"  {r.citation_label()}: {r.text[:100]}...")
    print("\n--- Test search: 'speech text dialogue' ---")
    results = idx.search("speech text dialogue", top_k=3)
    for r in results:
        print(f"  {r.citation_label()}: {r.text[:100]}...")
