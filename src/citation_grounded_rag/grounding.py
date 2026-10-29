"""Validate model citations against the retrieved source text."""

from __future__ import annotations

import json

from .engine import Answer, Passage


def validated_answer(
    raw: str, passages: list[Passage], min_confidence: float = 0.55
) -> Answer | None:
    """Accept only well-formed answers with exact source substrings."""
    try:
        data = json.loads(raw)
        answer = data["answer"]
        evidence = data["evidence"]
        confidence = float(data["confidence"])
        if not isinstance(answer, str) or not isinstance(evidence, list):
            return None
        by_id = {p.id: p for p in passages}
        ids = [item["id"] for item in evidence]
        if (
            not ids
            or len(ids) != len(set(ids))
            or not min_confidence <= confidence <= 1
            or any(
                not isinstance(item["quote"], str)
                or not item["quote"].strip()
                or item["quote"] not in by_id[item["id"]].text
                for item in evidence
            )
        ):
            return None
        return Answer(answer, tuple(by_id[i] for i in ids), confidence, True)
    except (ValueError, TypeError, KeyError):
        return None
