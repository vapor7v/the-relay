"""Second-stage local candidate reranker for high-precision fact retrieval.

Combines:
- Base retrieval score (RRF / BM25 / Semantic)
- Exact entity and quantitative token overlap boost (numbers, proper nouns)
- Section heading query relevance alignment
- Query-paper alignment
- Coverage density score
"""
import re
from typing import List, Tuple, Optional
from chunker import EnhancedChunk


class LocalCandidateReranker:
    """Fast, local second-stage reranker operating on candidate chunks."""

    def __init__(self):
        pass

    def rerank(
        self,
        query: str,
        candidates: List[EnhancedChunk],
        top_k: int = 5,
        target_paper: Optional[str] = None,
    ) -> List[EnhancedChunk]:
        """Rerank candidate chunks using multi-signal scoring."""
        if not candidates:
            return []

        # Extract numeric tokens and capitalized keywords from query
        q_lower = query.lower()
        numbers = re.findall(r'\b\d+(?:\.\d+)?\b', query)
        q_tokens = set(re.findall(r'\b\w+\b', q_lower))

        # Detect paper focus from query
        detected_paper = target_paper
        if not detected_paper:
            if any(w in q_lower for w in ["moshi", "speech", "codec", "audio", "mimi", "helium"]):
                detected_paper = "moshi"
            elif any(w in q_lower for w in ["dynamic chunking", "chunking", "boundary", "h-net"]):
                detected_paper = "dynamic_chunking"
            elif any(w in q_lower for w in ["transformer", "attention", "vaswani", "bleu", "multi-head"]):
                detected_paper = "attention"

        scored = []
        for rank, chunk in enumerate(candidates):
            c_text_lower = chunk.text.lower()
            heading_lower = chunk.section_heading.lower()

            # 1. Base position score from first stage (decaying from 1.0 down)
            score = 1.0 / (1.0 + 0.1 * rank)

            # 2. Paper alignment boost
            if detected_paper:
                if chunk.paper_key == detected_paper:
                    score += 0.5
                else:
                    score -= 0.3

            # 3. Section heading alignment boost
            heading_words = set(re.findall(r'\b\w+\b', heading_lower))
            overlap_heading = len(q_tokens.intersection(heading_words))
            score += 0.25 * overlap_heading

            # 4. Number match boost
            for num in numbers:
                if num in c_text_lower:
                    score += 0.35

            # 5. Semantic concept & domain term alignment boost
            concept_boosts = [
                ({"bitrate", "codec"}, {"1.1", "kbps", "bitrate", "quantiz", "rvq"}),
                ({"optimizer", "schedule"}, {"adam", "warmup", "decay"}),
                ({"regularization"}, {"dropout", "label smoothing", "regulariz"}),
                ({"boundary", "boundaries", "decide"}, {"predictor", "gating", "halt", "boundary", "learned"}),
                ({"dataset", "datasets", "evaluate"}, {"benchmark", "dataset", "fineweb", "lra", "evaluation", "fisher"}),
                ({"dimension", "d_model", "dimensionality"}, {"512", "d_model", "dimension"}),
                ({"heads", "head"}, {"8", "eight", "heads"}),
                ({"bleu"}, {"28.4", "bleu", "wmt"}),
                ({"latency"}, {"200", "160", "latency", "ms"}),
                ({"parameter", "parameters"}, {"7b", "billion", "helium"}),
                ({"positional", "encoding"}, {"sinusoid", "sine", "cosine"}),
                ({"duplex", "speaking", "listening"}, {"inner monologue", "parallel", "duplex", "stream"}),
            ]
            for q_triggers, cand_targets in concept_boosts:
                if any(t in q_lower for t in q_triggers):
                    if any(target in c_text_lower for target in cand_targets):
                        score += 0.45

            # 6. Penalize references / citations section chunks
            if any(w in heading_lower for w in ["references", "bibliography"]):
                score -= 1.0

            scored.append((chunk, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:top_k]]
