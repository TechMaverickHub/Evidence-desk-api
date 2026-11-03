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


def parse_prompts(markdown: str) -> AnswerPrompts:
    sections = _sections(markdown)
    for name, placeholders in REQUIRED_PLACEHOLDERS.items():
        if name not in sections:
            raise PromptError(f"prompts.md has no '## {name}' section")
        missing = placeholders - set(_PLACEHOLDER.findall(sections[name]))
        if missing:
            raise PromptError(f"'## {name}' is missing placeholders: {sorted(missing)}")
    return AnswerPrompts(**{name: sections[name] for name in REQUIRED_PLACEHOLDERS})


@lru_cache
def load_prompts() -> AnswerPrompts:
    return parse_prompts(PROMPTS_PATH.read_text(encoding="utf-8"))


def _sections(markdown: str) -> dict[str, str]:
    """Text of each `## name` section, up to the next one (the preamble is dropped)."""
    headings = list(_SECTION.finditer(markdown))
    ends = [heading.start() for heading in headings[1:]] + [len(markdown)]
    return {
        heading.group(1): markdown[heading.end() : end].strip()
        for heading, end in zip(headings, ends, strict=True)
    }
