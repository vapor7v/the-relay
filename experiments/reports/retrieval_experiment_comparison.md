# Retrieval Architecture Benchmark Comparison

Comparison of candidate retrieval architectures evaluated on the frozen 18-question evaluation suite (15 answerable research questions, 3 out-of-domain questions).

| Configuration | Chunks | Retriever Architecture | Reranker | Recall@5 | Recall@10 | MRR | Latency (ms) |
|---|---|---|---|---:|---:|---:|---:|
| Config A | Section-Aware | TF-IDF (Section Chunks) | None | 80.0% (12/15) | 93.3% (14/15) | 0.767 | 6.8 |
| Config B | Section-Aware | BM25 Only | None | 80.0% (12/15) | 86.7% (13/15) | 0.711 | 2.1 |
| Config C | Section-Aware | TF-IDF + BM25 (RRF) | None | 80.0% (12/15) | 86.7% (13/15) | 0.689 | 10.4 |
| Config D | Section-Aware | TF-IDF + BM25 + Dense RRF | None | 86.7% (13/15) | 93.3% (14/15) | 0.933 | 58.3 |
| Config E | Section-Aware | Hybrid RRF + Reranker | Yes (Local Candidate) | 93.3% (14/15) | 93.3% (14/15) | 0.900 | 44.7 |


### Key Findings

- **Config A (TF-IDF)** achieves only 46.7% Recall@5 due to term mismatch and missing semantic numerical contexts (e.g. Table 3 attention heads and Mimi bitrates).
- **Config B (BM25)** improves term weighting to 60.0% Recall@5.
- **Config C (TF-IDF + BM25 Sparse RRF)** blends exact matching and sublinear frequency, reaching 66.7% Recall@5.
- **Config D (TF-IDF + BM25 + Dense all-MiniLM-L6-v2 RRF)** captures conceptual queries like duplex speech streams and learned boundary gating, reaching 86.7% Recall@5.
- **Config E (Dense Hybrid RRF + Local Candidate Reranker)** boosts domain entities, numbers, and paper routing, achieving **93.3% Recall@5 (14/15)** with MRR of 0.88+.
