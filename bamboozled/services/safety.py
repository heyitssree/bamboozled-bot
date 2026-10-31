"""Screens EXTERNAL trivia text (question, every answer, category). Whole words, never substrings, so "class" is not "ass".

Tiers: `always` and `contextual` come from the v1 word list (data/safety/*.txt, nothing added); `blocklist` is the
owner's (Manglish spellings, Malayalam script). `contextual` only applies when trivia.safety_strictness is "strict".
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

DATA = Path(__file__).resolve().parents[2] / "data" / "safety"
ZERO_WIDTH = re.compile(r"[​-‏⁠﻿]")
LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
SHORT = 2                     # tokens this short are joined back up to catch "f u c k" and "fu-ck"


def normalise(text: str, keep: int = 2) -> str:
    t = unicodedata.normalize("NFKC", text).lower()          # folds full-width letters, keeps Malayalam script intact
    t = ZERO_WIDTH.sub("", t).translate(LEET)
    return re.sub(r"(.)\1{2,}", r"\1" * keep, t)             # "sooooo" -> "soo" (or "so": a stretched "wwwhore" too)


def tokens(text: str, keep: int = 2) -> list[str]:
    """Words: letters, digits and combining marks (Malayalam vowel signs are marks; \\w alone would split on them)."""
    out, cur = [], []
    for ch in normalise(text, keep):
        if ch.isalnum() or unicodedata.category(ch).startswith("M"):
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def _hit(entry: list[str], toks: list[str]) -> bool:
    n = len(entry)
    if any(toks[i:i + n] == entry for i in range(len(toks) - n + 1)):          # contiguous whole words
        return True
    flat = "".join(entry)
    if len(flat) >= 6 and flat in "".join(toks):                                # spaced-out evasion, long entries only
        return True
    # "f u c k" / "fu-ck": a run of 2+ short tokens that joins up to the entry exactly
    run: list[str] = []
    for tok in toks + [""]:
        if tok and len(tok) <= SHORT:
            run.append(tok)
            continue
        for i in range(len(run)):
            for j in range(i + 2, len(run) + 1):
                if "".join(run[i:j]) == flat:
                    return True
        run = []
    return False


def _load(path: Path) -> list[list[str]]:
    if not path.is_file():
        return []
    lines = (ln.strip() for ln in path.read_text(encoding="utf-8").splitlines())
    return [t for ln in lines if ln and not ln.startswith("#") and (t := tokens(ln))]


class Screen:
    def __init__(self, strictness: str = "standard", directory: Path = DATA):
        self.strictness = strictness
        self.always = _load(directory / "always.txt") + _load(directory / "blocklist.txt")
        self.contextual = _load(directory / "contextual.txt")
        self.allow = {t[0] for t in _load(directory / "allowlist.txt") if len(t) == 1}

    def is_clean(self, *texts: str, strictness: Optional[str] = None) -> bool:
        entries = self.always + (self.contextual if (strictness or self.strictness) == "strict" else [])
        for text in texts:
            for keep in (2, 1):
                toks = [t for t in tokens(text, keep) if t not in self.allow]
                if any(_hit(e, toks) for e in entries):
                    return False
        return True


class Rejections:
    """Counts screened-out questions per (source, category) for /bamboozled-admin status."""

    def __init__(self) -> None:
        self.counts: Counter = Counter()

    def add(self, source: str, category: str) -> None:
        self.counts[(source, category or "?")] += 1

    def total(self) -> int:
        return sum(self.counts.values())

    def by_source(self) -> dict[str, int]:
        out: Counter = Counter()
        for (src, _), n in self.counts.items():
            out[src] += n
        return dict(out)


def question_texts(q) -> Iterable[str]:
    return (q.text, q.category, *q.answers)
