"""Advanced document chunking with paragraph, section, and token awareness.

Supports:
- Paragraph-aware chunking (preserving semantic paragraphs)
- Section-aware chunking (detecting headings and subsection structure)
- Token-based chunk sizes with configurable overlap
- Adjacent-chunk expansion linking (prev/next chunk navigation)
- Preservation of arXiv version, paper title, page ranges, section headings
"""
import re
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

from PyPDF2 import PdfReader
from config import PAPERS, PAPERS_DIR


@dataclass
class EnhancedChunk:
    chunk_id: str
    paper_key: str              # e.g. "attention", "moshi", "dynamic_chunking"
    paper_title: str
    arxiv_version: str          # e.g. "1706.03762v7"
    page_start: int             # 1-indexed PDF page
    page_end: int
    section_heading: str        # e.g. "Section 3.2.2 Multi-Head Attention"
    text: str
    token_count: int
    char_start: int
    char_end: int
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None

    def citation_label(self) -> str:
        if self.page_start == self.page_end:
            return f"[{self.paper_title}, p.{self.page_start}]"
        return f"[{self.paper_title}, pp.{self.page_start}-{self.page_end}]"

    def citation_label_with_section(self) -> str:
        label = self.citation_label()
        if self.section_heading and self.section_heading != "General":
            return f"{label} ({self.section_heading})"
        return label


# Approximate token counter: ~4 characters per token in English scientific text
def estimate_tokens(text: str) -> int:
    words = re.findall(r'\b\w+\b|[^\w\s]', text)
    return max(1, len(words))


# Section heading detection patterns across the three papers
SECTION_PATTERNS = [
    r'^(?:(?:\d+\.){1,3}\d*|\b[IVXLCDM]+\.?)\s+([A-Z][A-Za-z0-9\s,\-:–—]+)',
    r'^(Abstract|Introduction|Background|Model Architecture|Attention|Training|Results|Evaluation|Experiments|Conclusion|References|Appendix(?:\s+[A-Z])?)\b',
    r'^(Table\s+\d+:?[^\n]+)',
    r'^(Figure\s+\d+:?[^\n]+)',
]

def detect_section_heading(line: str) -> Optional[str]:
    """Detect if a text line is a section heading or table/figure title."""
    s = line.strip()
    if len(s) < 3 or len(s) > 100:
        return None
    for pattern in SECTION_PATTERNS:
        m = re.match(pattern, s, re.IGNORECASE)
        if m:
            return s
    return None


def extract_paper_pages(paper_key: str) -> List[Dict[str, Any]]:
    """Extract text page-by-page preserving character positions, paragraphs, and headings."""
    info = PAPERS[paper_key]
    path = os.path.join(PAPERS_DIR, info["file"])
    reader = PdfReader(path)
    pages_data = []

    for i, page in enumerate(reader.pages):
        raw = page.extract_text() or ""
        # Clean line breaks while preserving paragraph boundaries
        # Normalize double newlines for paragraphs
        lines = [line.strip() for line in raw.split("\n")]
        paragraphs = []
        curr_p = []
        current_section = None

        for line in lines:
            if not line:
                if curr_p:
                    p_text = " ".join(curr_p).strip()
                    if p_text:
                        paragraphs.append({"text": p_text, "heading": current_section})
                    curr_p = []
                continue

            sec = detect_section_heading(line)
            if sec:
                if curr_p:
                    p_text = " ".join(curr_p).strip()
                    if p_text:
                        paragraphs.append({"text": p_text, "heading": current_section})
                    curr_p = []
                current_section = sec
                curr_p.append(line)
            else:
                curr_p.append(line)

        if curr_p:
            p_text = " ".join(curr_p).strip()
            if p_text:
                paragraphs.append({"text": p_text, "heading": current_section})

        pages_data.append({
            "page_num": i + 1,
            "raw_text": " ".join(lines),
            "paragraphs": paragraphs,
        })

    return pages_data


def chunk_paper(
    paper_key: str,
    strategy: str = "section_aware",  # "token_300_50", "token_500_75", "token_700_100", "section_aware"
    target_tokens: int = 500,
    overlap_tokens: int = 75,
) -> List[EnhancedChunk]:
    """Chunk paper into EnhancedChunk instances using specified chunking strategy."""
    info = PAPERS[paper_key]
    title = info["title"]
    arxiv_ver = info.get("version", "arXiv")
    pages_data = extract_paper_pages(paper_key)

    if strategy == "token_300_50":
        target_tokens, overlap_tokens = 300, 50
    elif strategy == "token_500_75":
        target_tokens, overlap_tokens = 500, 75
    elif strategy == "token_700_100":
        target_tokens, overlap_tokens = 700, 100

    chunks: List[EnhancedChunk] = []
    
    # Flatten paragraphs across pages with page tracking
    flat_paragraphs = []
    for p_data in pages_data:
        p_num = p_data["page_num"]
        for para in p_data["paragraphs"]:
            p_text = para["text"]
            # Fix PDF extraction glitches like 'warmup _steps' -> 'warmup_steps', '1.1kbps' -> '1.1 kbps'
            p_text = re.sub(r'warmup\s+_steps', 'warmup_steps', p_text)
            p_text = re.sub(r'd_model\s+', 'd_model ', p_text)
            p_text = re.sub(r'1\.1\s*kbps', '1.1 kbps', p_text)
            p_tokens = estimate_tokens(p_text)
            flat_paragraphs.append({
                "page": p_num,
                "text": p_text,
                "tokens": p_tokens,
                "heading": para["heading"] or "General",
            })

    if strategy == "section_aware":
        # Group paragraphs by coherent section boundaries without splitting small subsections
        curr_section = None
        curr_text_parts = []
        curr_pages = []
        curr_tokens = 0
        chunk_idx = 0

        for p in flat_paragraphs:
            heading = p["heading"]
            p_tok = p["tokens"]

            # If section changed and we have accumulated enough text, emit chunk
            section_changed = (heading != curr_section and heading != "General" and curr_tokens >= 150)
            token_overflow = (curr_tokens + p_tok > 600)

            if (section_changed or token_overflow) and curr_text_parts:
                c_text = "\n\n".join(curr_text_parts).strip()
                if len(c_text) > 40:
                    cid = f"{paper_key}-sec-{chunk_idx:04d}"
                    chunks.append(EnhancedChunk(
                        chunk_id=cid,
                        paper_key=paper_key,
                        paper_title=title,
                        arxiv_version=arxiv_ver,
                        page_start=min(curr_pages),
                        page_end=max(curr_pages),
                        section_heading=curr_section or "General",
                        text=c_text,
                        token_count=curr_tokens,
                        char_start=0,
                        char_end=len(c_text),
                    ))
                    chunk_idx += 1

                # If section changed, start fresh; if token overflow, carry overlap
                if section_changed:
                    curr_text_parts = []
                    curr_pages = []
                    curr_tokens = 0
                else:
                    # Keep last paragraph for overlap
                    overlap_para = curr_text_parts[-1] if curr_text_parts else ""
                    curr_text_parts = [overlap_para] if overlap_para else []
                    curr_pages = [curr_pages[-1]] if curr_pages else []
                    curr_tokens = estimate_tokens(overlap_para)

            if heading != "General" and heading is not None:
                curr_section = heading

            curr_text_parts.append(p["text"])
            curr_pages.append(p["page"])
            curr_tokens += p_tok

        # Final chunk
        if curr_text_parts:
            c_text = "\n\n".join(curr_text_parts).strip()
            if len(c_text) > 40:
                cid = f"{paper_key}-sec-{chunk_idx:04d}"
                chunks.append(EnhancedChunk(
                    chunk_id=cid,
                    paper_key=paper_key,
                    paper_title=title,
                    arxiv_version=arxiv_ver,
                    page_start=min(curr_pages),
                    page_end=max(curr_pages),
                    section_heading=curr_section or "General",
                    text=c_text,
                    token_count=curr_tokens,
                    char_start=0,
                    char_end=len(c_text),
                ))

    else:
        # Token-based sliding window over paragraphs
        curr_text_parts = []
        curr_pages = []
        curr_tokens = 0
        chunk_idx = 0
        curr_heading = "General"

        for p in flat_paragraphs:
            p_tok = p["tokens"]
            if p["heading"] != "General":
                curr_heading = p["heading"]

            curr_text_parts.append(p["text"])
            curr_pages.append(p["page"])
            curr_tokens += p_tok

            if curr_tokens >= target_tokens:
                c_text = "\n\n".join(curr_text_parts).strip()
                if len(c_text) > 40:
                    cid = f"{paper_key}-{strategy}-{chunk_idx:04d}"
                    chunks.append(EnhancedChunk(
                        chunk_id=cid,
                        paper_key=paper_key,
                        paper_title=title,
                        arxiv_version=arxiv_ver,
                        page_start=min(curr_pages),
                        page_end=max(curr_pages),
                        section_heading=curr_heading,
                        text=c_text,
                        token_count=curr_tokens,
                        char_start=0,
                        char_end=len(c_text),
                    ))
                    chunk_idx += 1

                # Discard paragraphs until remaining tokens <= overlap_tokens
                while curr_text_parts and curr_tokens > overlap_tokens:
                    removed_text = curr_text_parts.pop(0)
                    curr_pages.pop(0)
                    curr_tokens -= estimate_tokens(removed_text)

        if curr_text_parts:
            c_text = "\n\n".join(curr_text_parts).strip()
            if len(c_text) > 40:
                cid = f"{paper_key}-{strategy}-{chunk_idx:04d}"
                chunks.append(EnhancedChunk(
                    chunk_id=cid,
                    paper_key=paper_key,
                    paper_title=title,
                    arxiv_version=arxiv_ver,
                    page_start=min(curr_pages),
                    page_end=max(curr_pages),
                    section_heading=curr_heading,
                    text=c_text,
                    token_count=curr_tokens,
                    char_start=0,
                    char_end=len(c_text),
                ))

    # Link adjacent chunks (prev/next) for context expansion
    for i in range(len(chunks)):
        if i > 0:
            chunks[i].prev_chunk_id = chunks[i - 1].chunk_id
        if i < len(chunks) - 1:
            chunks[i].next_chunk_id = chunks[i + 1].chunk_id

    return chunks


def build_corpus(strategy: str = "section_aware") -> List[EnhancedChunk]:
    """Build corpus across all three arXiv papers with specified chunking strategy."""
    all_chunks = []
    for key in PAPERS.keys():
        paper_chunks = chunk_paper(key, strategy=strategy)
        all_chunks.extend(paper_chunks)
    return all_chunks
