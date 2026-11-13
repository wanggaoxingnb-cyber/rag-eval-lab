"""Small deterministic RAG evaluator: no external calls and no third-party packages."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re

INJECTION_PATTERNS = [
    "忽略之前", "忽略全部", "泄露系统", "系统提示词一字不差", "绕过账号",
    "绕过权限", "导出所有客户", "导出全部客户", "伪造", "篡改", "无限退款",
]
SYNONYMS = {
    "订单号": "订单编号",
    "退钱": "退款",
    "超额": "超过原支付金额",
    "别人": "其他客户",
    "发票抬头": "企业名称 纳税人识别号",
}


@dataclass(frozen=True)
class Config:
    name: str
    chunk_chars: int
    top_k: int
    score_threshold: float
    title_boost: float
    diversify: bool
    injection_guard: bool
    synonym_expansion: bool
    scope_exclusion_guard: bool
    description: str


BASELINE = Config(
    name="baseline", chunk_chars=240, top_k=3, score_threshold=0.15,
    title_boost=0.0, diversify=False, injection_guard=False,
    synonym_expansion=False, scope_exclusion_guard=False,
    description="较长切块、低阈值、无文档多样性、无查询扩展、无注入防护",
)
IMPROVED = Config(
    name="improved", chunk_chars=130, top_k=5, score_threshold=3.0,
    title_boost=1.4, diversify=True, injection_guard=True,
    synonym_expansion=True, scope_exclusion_guard=True,
    description="章节内小块、阈值提升、标题加权、文档多样性、查询扩展与注入防护",
)


def chinese_bigrams(text: str) -> list[str]:
    tokens = []
    for segment in re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+", text.lower()):
        if re.fullmatch(r"[a-z0-9]+", segment):
            tokens.append(segment)
        else:
            tokens.extend(segment[i:i + 2] for i in range(max(1, len(segment) - 1)))
    return tokens


def normalize_query(query: str, enabled: bool) -> str:
    if not enabled:
        return query
    result = query
    for source, target in SYNONYMS.items():
        result = result.replace(source, target)
    return result


def split_text(text: str, size: int) -> list[str]:
    """Split at Chinese punctuation near the configured boundary, never mid-word on purpose."""
    text = text.strip()
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            candidates = [text.rfind(mark, start, end) for mark in "。；！？"]
            boundary = max(candidates)
            if boundary > start + size // 2:
                end = boundary + 1
        chunks.append(text[start:end].strip())
        start = end
    return [chunk for chunk in chunks if chunk]


def make_chunks(documents: list[dict], size: int) -> list[dict]:
    chunks = []
    for doc in documents:
        for section in doc["sections"]:
            for index, text in enumerate(split_text(section["text"], size), 1):
                chunks.append({
                    "chunk_id": f"{doc['id']}:{section['id']}:{index}",
                    "doc_id": doc["id"], "doc_title": doc["title"],
                    "section_id": section["id"], "section_title": section["title"],
                    "text": text,
                })
    return chunks


class BM25:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.tokens = [chinese_bigrams(c["text"]) for c in chunks]
        self.frequencies = [Counter(tokens) for tokens in self.tokens]
        self.lengths = [len(tokens) for tokens in self.tokens]
        self.avg_length = sum(self.lengths) / max(1, len(self.lengths))
        self.doc_frequency = Counter()
        for tokens in self.tokens:
            self.doc_frequency.update(set(tokens))
        self.total = len(chunks)

    def idf(self, token: str) -> float:
        df = self.doc_frequency[token]
        return math.log(1 + (self.total - df + 0.5) / (df + 0.5))

    def rank(self, query: str, config: Config) -> list[dict]:
        query = normalize_query(query, config.synonym_expansion)
        query_tokens = set(chinese_bigrams(query))
        scored = []
        for index, chunk in enumerate(self.chunks):
            score = 0.0
            freq = self.frequencies[index]
            length = self.lengths[index]
            for token in query_tokens:
                tf = freq[token]
                if not tf:
                    continue
                k1, b = 1.5, 0.75
                denominator = tf + k1 * (1 - b + b * length / self.avg_length)
                score += self.idf(token) * tf * (k1 + 1) / denominator
            if config.title_boost:
                title_tokens = set(chinese_bigrams(chunk["doc_title"] + chunk["section_title"]))
                score += config.title_boost * len(query_tokens & title_tokens)
            if score > 0:
                scored.append({"score": round(score, 6), **chunk})
        scored.sort(key=lambda row: (-row["score"], row["chunk_id"]))
        if config.diversify:
            scored = diversify(scored)
        return scored[:config.top_k]


def diversify(rows: list[dict]) -> list[dict]:
    """Take the best chunk from each document first, then fill by score."""
    first, later, seen = [], [], set()
    for row in rows:
        if row["doc_id"] not in seen:
            first.append(row)
            seen.add(row["doc_id"])
        else:
            later.append(row)
    return first + later


def injection_reason(query: str) -> str | None:
    for pattern in INJECTION_PATTERNS:
        if pattern in query:
            return pattern
    return None


def answer_query(query: str, documents: list[dict], config: Config) -> dict:
    if config.injection_guard:
        reason = injection_reason(query)
        if reason:
            return {
                "type": "refuse_injection", "answer": f"我不能执行涉及“{reason}”的请求。",
                "citations": [], "evidence_doc_ids": [], "evidence": [], "top_score": 0,
            }

    chunks = make_chunks(documents, config.chunk_chars)
    evidence = BM25(chunks).rank(query, config)
    top_score = evidence[0]["score"] if evidence else 0
    negative_scope_only = (
        config.scope_exclusion_guard
        and re.search(r"多少|多少钱|发放标准", query)
        and evidence
        and all("不包含" in row["text"] for row in evidence)
    )
    if not evidence or top_score < config.score_threshold or negative_scope_only:
        return {
            "type": "refuse_no_evidence", "answer": "当前知识库没有足够依据，我不作猜测。",
            "citations": [], "evidence_doc_ids": [], "evidence": evidence, "top_score": top_score,
        }

    citations = list(dict.fromkeys(row["doc_id"] for row in evidence))
    snippets = []
    used_docs = set()
    for row in evidence:
        if row["doc_id"] in used_docs:
            continue
        used_docs.add(row["doc_id"])
        snippets.append(f"《{row['doc_title']}·{row['section_title']}》指出：{row['text']}")
        if len(snippets) >= (3 if config.diversify else 2):
            break
    answer = "\n".join(snippets) + "\n以上只按当前证据回答；涉及资金、权限或隐私时仍需人工复核。"
    return {
        "type": "answer", "answer": answer, "citations": citations,
        "evidence_doc_ids": list(dict.fromkeys(row["doc_id"] for row in evidence)),
        "evidence": evidence, "top_score": top_score,
    }
