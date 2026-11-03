"""Number the context passages, and check a model reply against exactly what was sent.

This is the trust boundary: an answer leaves the server only if every citation maps to a
passage that was actually in the prompt.
"""

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from app.generation.schemas import AnswerStatus, ModelAnswer
from app.retrieval.repository import SearchHit


@dataclass(frozen=True)
class LabelledPassage:
    label: int
    hit: SearchHit


@dataclass(frozen=True)
class CheckedAnswer:
    status: AnswerStatus
    answer: str
    # In citation order, without duplicates; empty unless answered.
    cited: list[LabelledPassage]


class InvalidReplyError(Exception):
    """A reply that can't be accepted. `kind` decides what happens after the one retry:
    "format" ends in 502, "unsupported" is downgraded to insufficient_evidence."""

    def __init__(self, kind: Literal["format", "unsupported"], problem: str) -> None:
        super().__init__(problem)
        self.kind = kind
        self.problem = problem


def label_passages(hits: list[SearchHit]) -> list[LabelledPassage]:
    return [LabelledPassage(label, hit) for label, hit in enumerate(hits, start=1)]


def format_passages(passages: list[LabelledPassage]) -> str:
    """Delimited blocks; the source attribute lets the model see document versions."""
    return "\n\n".join(
        f'<passage id="{p.label}" source="{p.hit.slug}@{p.hit.version}">\n'
        f"{_neutralise_delimiters(p.hit.text)}\n</passage>"
        for p in passages
    )


def check_reply(content: str, passages: list[LabelledPassage]) -> CheckedAnswer:
    try:
        reply = ModelAnswer.model_validate(json.loads(content))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise InvalidReplyError("format", "the reply was not JSON matching the schema") from exc
    if reply.status == "insufficient_evidence":
        # Text or citations alongside a refusal are ignored, never shown.
        return CheckedAnswer("insufficient_evidence", "", [])
    if not reply.answer.strip():
        raise InvalidReplyError("unsupported", "status was answered but the answer was empty")
    if not reply.citations:
        raise InvalidReplyError("unsupported", "the answer cited no passages")
    by_label = {passage.label: passage for passage in passages}
    unknown = sorted(set(reply.citations) - by_label.keys())
    if unknown:
        raise InvalidReplyError(
            "unsupported", f"it cited passage numbers that were not given: {unknown}"
        )
    ordered = list(dict.fromkeys(reply.citations))
    return CheckedAnswer("answered", reply.answer.strip(), [by_label[n] for n in ordered])


def _neutralise_delimiters(text: str) -> str:
    # A passage must not be able to close its own block and pose as instructions.
    return text.replace("</passage", "</ passage").replace("<passage", "< passage")
