from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ToolResult:
    output: Any
    confidence: float
    meta: Dict[str, Any] | None = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "output": self.output,
            "confidence": float(self.confidence),
            "meta": self.meta or {},
        }


def clamp01(x: float) -> float:
    if math.isnan(x) or math.isinf(x):
        return 0.0
    return max(0.0, min(1.0, x))


def retrieval_confidence_from_sources(
    sources: List[Dict[str, Any]],
    *,
    threshold: float,
) -> ToolResult:
    """Heuristic confidence for retrieval.

    We treat the best chunk relevance as the main signal, then lightly boost
    for additional supporting chunks above threshold.
    """

    rels: List[float] = []
    for s in sources or []:
        try:
            rels.append(float(s.get("relevance") or 0.0))
        except Exception:
            continue

    top = max(rels) if rels else 0.0
    supports = sum(1 for r in rels if r >= float(threshold))

    conf = clamp01(top / 100.0)
    conf = clamp01(conf + 0.05 * float(min(5, supports)))

    return ToolResult(
        output=None,
        confidence=conf,
        meta={"top_relevance": top, "supports": supports, "threshold": threshold},
    )


def transcription_confidence(transcript: str) -> ToolResult:
    text = str(transcript or "").strip()
    if not text:
        return ToolResult(output=None, confidence=0.0, meta={"chars": 0})
    # crude heuristic: longer transcript -> higher confidence
    conf = clamp01(min(1.0, len(text) / 120.0))
    return ToolResult(output=None, confidence=conf, meta={"chars": len(text)})


def llm_confidence(
    *,
    used_strict_grounding: bool,
    retrieval_confidence: float,
    answer: str,
) -> ToolResult:
    ans = str(answer or "").strip()
    if not ans:
        return ToolResult(output=None, confidence=0.0, meta={"empty": True})

    # In grounded RAG, the LLM confidence should generally be bounded by retrieval confidence.
    base = retrieval_confidence
    if not used_strict_grounding:
        base = clamp01(base * 0.8)

    # Penalize very short answers.
    if len(ans) < 30:
        base = clamp01(base * 0.7)

    return ToolResult(output=None, confidence=base, meta={"answer_chars": len(ans)})
