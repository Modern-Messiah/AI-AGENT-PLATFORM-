"""Post-answer faithfulness verification — the anti-hallucination gate.

After the strong model answers, a cheap verifier pass checks every sentence
of the answer against the cited sources: does the source actually state
this? The verdict travels with the done-event (verified / unsupported count
and which sentences failed), feeds into confidence calibration, and — when
NOTHING is supported — replaces the answer with an honest refusal instead
of letting an invented text through.

Best-effort by design: verifier outage degrades to "unverified", never
blocks the answer path.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from packages.core import settings
from packages.llm.client import complete_chat_json
from packages.rag.citations import CitationSource

log = logging.getLogger(__name__)

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MAX_ANSWER_CHARS = 6_000
_MAX_SOURCES = 6
_MAX_SOURCE_CHARS = 1_200

_VERIFIER_PROMPT = (
    "You are a strict fact-checker. For EACH numbered answer sentence decide "
    "whether the provided sources explicitly state it.\n"
    "Verdict 'supported' requires the claim (including numbers, codes, names, "
    "dates) to be directly present in the sources — not implied, not completed "
    "from world knowledge, not translated differently in meaning.\n"
    'Reply with JSON: {"supported": [1,3], "unsupported": [2]} using the '
    "sentence numbers; every number must appear in exactly one list."
)


@dataclass
class FaithfulnessVerdict:
    verified: bool = True
    total_sentences: int = 0
    supported_sentences: list[int] = field(default_factory=list)
    unsupported_sentences: list[int] = field(default_factory=list)
    error: str | None = None

    @property
    def unsupported_ratio(self) -> float:
        if not self.total_sentences:
            return 0.0
        return len(self.unsupported_sentences) / self.total_sentences


def split_answer_sentences(answer: str) -> list[str]:
    """Sentence split for verification; markers/lists kept out of the way."""
    sentences = [s.strip() for s in _SENTENCE_RE.split(answer.strip()) if s.strip()]
    return [s for s in sentences if len(s) > 3]


def _sources_block(sources: list[CitationSource]) -> str:
    parts = []
    for source in sources[:_MAX_SOURCES]:
        excerpt = source.excerpt[:_MAX_SOURCE_CHARS]
        parts.append(f"[{source.id}] {source.filename}:\n{excerpt}")
    return "\n\n".join(parts)


async def verify_answer_faithfulness(
    answer: str, sources: list[CitationSource]
) -> FaithfulnessVerdict:
    """Check every answer sentence against the cited sources (weak model)."""
    if not settings.answer_verification_enabled:
        return FaithfulnessVerdict(verified=True, error="disabled")
    sentences = split_answer_sentences(answer[:_MAX_ANSWER_CHARS])
    if not sentences or not sources:
        # Nothing to check — empty answers are handled by the refusal path.
        return FaithfulnessVerdict(verified=True, total_sentences=len(sentences))

    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, start=1))
    messages = [
        {"role": "system", "content": _VERIFIER_PROMPT},
        {
            "role": "user",
            "content": f"Answer sentences:\n{numbered}\n\nSources:\n{_sources_block(sources)}",
        },
    ]
    try:
        raw = await complete_chat_json(settings.weak_model, messages, max_tokens=300)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        supported = [int(n) for n in parsed.get("supported", [])]
        unsupported = [int(n) for n in parsed.get("unsupported", [])]
    except Exception as exc:
        log.warning("answer verification failed (degraded to unverified): %s", exc)
        return FaithfulnessVerdict(
            verified=False, total_sentences=len(sentences), error=str(exc)[:200]
        )

    valid = set(range(1, len(sentences) + 1))
    supported = [n for n in supported if n in valid]
    unsupported = [n for n in unsupported if n in valid]
    missing = sorted(valid - set(supported) - set(unsupported))
    if missing:  # verifier skipped some sentences — treat them as unsupported
        unsupported = sorted(set(unsupported) | set(missing))

    verdict = FaithfulnessVerdict(
        verified=not unsupported,
        total_sentences=len(sentences),
        supported_sentences=supported,
        unsupported_sentences=unsupported,
    )
    if unsupported:
        log.info(
            "answer verification: %d/%d sentences unsupported",
            len(unsupported),
            len(sentences),
        )
    return verdict
