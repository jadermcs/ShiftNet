"""Finding a lemma's occurrences in a document and cutting an encoder-sized context around each."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

# Sentence ends: . ! ? followed by space and a capital/quote/digit, or a blank line.
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]?\s+(?=[\"'(\[A-Z0-9])|\n\s*\n")
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Occurrence:
    context: str
    start: int  # character span of the target in context
    end: int


def forms_pattern(forms: list[str]) -> re.Pattern[str]:
    """Whole-word, case-insensitive match of any form; multi-word forms allow any whitespace."""
    alts = sorted({f.strip() for f in forms if f.strip()}, key=len, reverse=True)
    body = "|".join(r"\s+".join(map(re.escape, f.split())) for f in alts)
    return re.compile(rf"(?<![\w-])(?:{body})(?![\w-])", re.IGNORECASE)


def sentences(text: str) -> Iterator[tuple[int, int]]:
    """Character spans of sentences."""
    start = 0
    for m in _SENTENCE_END.finditer(text):
        yield start, m.start()
        start = m.end()
    yield start, len(text)


def default_forms(lemma: str) -> list[str]:
    """The lemma and a regular plural / third person: cloud, clouds; bus, buses; spy, spies."""
    lemma = lemma.strip()
    last = lemma.split()[-1].lower()
    if re.search(r"(s|x|z|ch|sh)$", last):
        plural = lemma + "es"
    elif re.search(r"[^aeiou]y$", last):
        plural = lemma[:-1] + "ies"
    else:
        plural = lemma + "s"
    return [lemma, plural]


def occurrences(
    text: str,
    pattern: re.Pattern[str],
    count_tokens: Callable[[str], int],
    max_tokens: int,
    max_per_doc: int = 2,
    min_words: int = 6,
) -> Iterator[Occurrence]:
    """Occurrences of the pattern, each with its sentence trimmed to fit the encoder.

    The context is the target's sentence, whitespace collapsed. If it is longer than max_tokens
    (counting the two markers), words are dropped from whichever side is longer until it fits, so
    the target stays roughly centred and is never truncated away. Very short sentences (headings,
    menu items) are skipped; so are repeated sentences within a document.
    """
    seen: set[str] = set()
    found = 0
    for s0, s1 in sentences(text):
        sentence = text[s0:s1]
        for m in pattern.finditer(sentence):
            before = _WS.sub(" ", sentence[: m.start()]).lstrip()
            after = _WS.sub(" ", sentence[m.end() :]).rstrip()
            left, right = before.split(), after.split()
            if len(left) + len(right) + 1 < min_words:
                continue
            # Keep "(cloud" and "clouds," glued as they were written.
            glue_left = "" if before and not before.endswith(" ") else " "
            glue_right = "" if after and not after.startswith(" ") else " "
            target = _WS.sub(" ", m.group(0))
            ctx = _join(left, glue_left, target, glue_right, right)
            while count_tokens(ctx.context) + 2 > max_tokens and (left or right):
                if len(left) > len(right):
                    left, glue_left = left[1:], glue_left if len(left) > 1 else " "
                else:
                    right, glue_right = right[:-1], glue_right if len(right) > 1 else " "
                ctx = _join(left, glue_left, target, glue_right, right)
            key = ctx.context.lower()
            if key in seen:
                continue
            seen.add(key)
            yield ctx
            found += 1
            if found >= max_per_doc:
                return


def _join(left: list[str], glue_left: str, target: str, glue_right: str, right: list[str]) -> Occurrence:
    pre = " ".join(left) + glue_left if left else ""
    post = glue_right + " ".join(right) if right else ""
    return Occurrence(pre + target + post, len(pre), len(pre) + len(target))
