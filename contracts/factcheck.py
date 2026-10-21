"""Fact checks for LLM text, shared by every agent that lets an LLM write.

The LLM is allowed to rephrase, never to invent a figure: every number in its text
must already exist in the facts it was given. Known limit: a wrong claim made in
WORDS (no number) is not caught here.
"""
import re

# A figure, not part of an identifier: "run_001", "Revenue@2.0", "#12", "R4" are skipped
# (entry ids are checked separately as citations).
NUMBER = re.compile(r"(?<![\w@#.,])\d+(?:,\d{3})*(?:\.\d+)?(?!\w)")


def numbers_in(text: str) -> list[str]:
    return NUMBER.findall(text)


def allowed_numbers(*texts: str) -> set[float]:
    """Every number of the facts, plus its usual roundings."""
    out: set[float] = set()
    for t in texts:
        for n in numbers_in(t):
            v = float(n.replace(",", ""))
            out |= {v, round(v), round(v, 1), round(v, 2)}
    return out


def unsupported_numbers(text: str, allowed: set[float]) -> list[str]:
    """Numbers of `text` absent from the facts (dates split into parts are fine)."""
    return [n for n in numbers_in(text)
            if not any(abs(float(n.replace(",", "")) - a) < 1e-9 for a in allowed)]
