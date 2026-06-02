from __future__ import annotations

import math
import re
from collections import Counter

from docagent.schemas import EvidenceBlock

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text or "")]


class BM25Index:
    def __init__(self, blocks: list[EvidenceBlock], k1: float = 1.5, b: float = 0.75) -> None:
        self.blocks = blocks
        self.k1 = k1
        self.b = b
        self.doc_tokens = [tokenize(block.retrieval_text) for block in blocks]
        self.doc_len = [len(tokens) for tokens in self.doc_tokens]
        self.avg_doc_len = sum(self.doc_len) / max(len(self.doc_len), 1)
        self.term_freq = [Counter(tokens) for tokens in self.doc_tokens]
        doc_freq: Counter[str] = Counter()
        for tokens in self.doc_tokens:
            doc_freq.update(set(tokens))
        total_docs = max(len(blocks), 1)
        self.idf = {
            term: math.log(1 + (total_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in doc_freq.items()
        }

    def score(self, query: str, idx: int) -> float:
        query_terms = tokenize(query)
        if not query_terms or not self.doc_tokens[idx]:
            return 0.0
        score = 0.0
        length = self.doc_len[idx]
        tf = self.term_freq[idx]
        for term in query_terms:
            freq = tf.get(term, 0)
            if freq == 0:
                continue
            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * (1 - self.b + self.b * length / max(self.avg_doc_len, 1))
            score += self.idf.get(term, 0.0) * numerator / denominator
        return score

    def search(self, query: str, top_k: int = 5) -> list[tuple[EvidenceBlock, float]]:
        scored = [(block, self.score(query, idx)) for idx, block in enumerate(self.blocks)]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [(block, score) for block, score in scored[:top_k] if score > 0]

