"""Load the answer prompts from `prompts.md`, so prompt text never lives in Python code."""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_PATH = Path(__file__).with_name("prompts.md")

# Each section and the placeholders it must contain; checked when the file is loaded.
REQUIRED_PLACEHOLDERS = {
    "system": set(),
    "user": {"question", "passages"},
    "retry": {"problem"},
}
JUDGE_PLACEHOLDERS = {
    "judge_system": set(),
    "judge_correctness": {"question", "reference", "answer"},
    "judge_faithfulness": {"answer", "passages"},
}
_SECTION = re.compile(r"^## (\w+)\s*$", re.MULTILINE)
_PLACEHOLDER = re.compile(r"{(\w+)}")


class PromptError(Exception):
    """The prompt file is missing a section or placeholder; raised at startup, not mid-request."""


@dataclass(frozen=True)
class AnswerPrompts:
    system: str
    user: str
    retry: str

    def user_message(self, question: str, passages: str) -> str:
        return self.user.format(question=question, passages=passages)

    def retry_message(self, problem: str) -> str:
        return self.retry.format(problem=problem)


@dataclass(frozen=True)
class JudgePrompts:
    """Grading prompts for answer evaluation (task 009b)."""

    judge_system: str
    judge_correctness: str
    judge_faithfulness: str

    def correctness_message(self, question: str, reference: str, answer: str) -> str:
        return self.judge_correctness.format(question=question, reference=reference, answer=answer)

    def faithfulness_message(self, answer: str, passages: str) -> str:
        return self.judge_faithfulness.format(answer=answer, passages=passages)


def parse_prompts(markdown: str) -> AnswerPrompts:
    return AnswerPrompts(**_checked_sections(markdown, REQUIRED_PLACEHOLDERS))


def parse_judge_prompts(markdown: str) -> JudgePrompts:
    return JudgePrompts(**_checked_sections(markdown, JUDGE_PLACEHOLDERS))


@lru_cache
def load_prompts() -> AnswerPrompts:
    return parse_prompts(PROMPTS_PATH.read_text(encoding="utf-8"))


@lru_cache
def load_judge_prompts() -> JudgePrompts:
    return parse_judge_prompts(PROMPTS_PATH.read_text(encoding="utf-8"))


def _checked_sections(markdown: str, required: dict[str, set[str]]) -> dict[str, str]:
    sections = _sections(markdown)
    for name, placeholders in required.items():
        if name not in sections:
            raise PromptError(f"prompts.md has no '## {name}' section")
        missing = placeholders - set(_PLACEHOLDER.findall(sections[name]))
        if missing:
            raise PromptError(f"'## {name}' is missing placeholders: {sorted(missing)}")
    return {name: sections[name] for name in required}


def _sections(markdown: str) -> dict[str, str]:
    """Text of each `## name` section, up to the next one (the preamble is dropped)."""
    headings = list(_SECTION.finditer(markdown))
    ends = [heading.start() for heading in headings[1:]] + [len(markdown)]
    return {
        heading.group(1): markdown[heading.end() : end].strip()
        for heading, end in zip(headings, ends, strict=True)
    }
