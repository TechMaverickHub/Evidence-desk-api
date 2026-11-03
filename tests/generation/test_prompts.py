import pytest

from app.generation.prompts import PromptError, load_prompts, parse_prompts

VALID = """# notes {ignored}

## system
Be careful.

## user
Q: {question}
P: {passages}

## retry
Problem: {problem}
"""


def test_the_shipped_prompt_file_loads_with_every_section() -> None:
    prompts = load_prompts()

    message = prompts.user_message("What is k?", '<passage id="1">k is 60</passage>')
    assert "What is k?" in message
    assert "k is 60" in message
    assert "untrusted" in prompts.system


def test_sections_are_split_and_the_preamble_dropped() -> None:
    prompts = parse_prompts(VALID)

    assert prompts.system == "Be careful."
    assert prompts.retry_message("bad citation") == "Problem: bad citation"


@pytest.mark.parametrize(
    ("markdown", "message"),
    [
        (VALID.replace("## user", "## users"), "no '## user' section"),
        (VALID.replace("{passages}", ""), "missing placeholders: ['passages']"),
        (VALID.replace("{problem}", "x"), "missing placeholders: ['problem']"),
    ],
)
def test_a_broken_prompt_file_fails_with_a_clear_message(markdown: str, message: str) -> None:
    with pytest.raises(PromptError, match=message.replace("[", r"\[").replace("]", r"\]")):
        parse_prompts(markdown)


def test_curly_braces_in_passage_text_are_not_reformatted() -> None:
    # Passages often contain code like {**mapping}; format() only touches the template.
    message = parse_prompts(VALID).user_message("q", "use {**mapping} and {x}")

    assert "use {**mapping} and {x}" in message
