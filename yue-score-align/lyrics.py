"""lyrics.py - разбор текста песни и силлабификация (русский и латиница)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯaeiouAEIOU")
SOFT = set("ьъ")
PUNCT = re.compile(r"[^\w\s-]")


@dataclass
class LyricLine:
    text: str
    syllables: list[str] = field(default_factory=list)


@dataclass
class LyricSection:
    name: str
    lines: list[LyricLine] = field(default_factory=list)


def syllabify(word: str) -> list[str]:
    """Разбивает слово на слоги по кластерам гласных.

    Правила:
    - мягкий/твёрдый знак склеивается с предшествующим согласным;
    - одиночный согласный между гласными открывает следующий слог;
    - кластер из двух и более согласных: первый закрывает текущий слог.
    """
    word = word.strip()
    if not word:
        return []
    chars = list(word)
    vowel_idx = [i for i, ch in enumerate(chars) if ch in VOWELS]
    if not vowel_idx:
        return [word]
    nuclei = []
    start = prev = vowel_idx[0]
    for i in vowel_idx[1:]:
        if i == prev + 1:
            prev = i
            continue
        nuclei.append((start, prev))
        start = prev = i
    nuclei.append((start, prev))
    sylls = []
    cut = 0
    for n, (ns, ne) in enumerate(nuclei):
        if n + 1 < len(nuclei):
            next_start = nuclei[n + 1][0]
            units = []
            i = ne + 1
            while i < next_start:
                if chars[i] in SOFT and units:
                    units[-1] = (units[-1][0], i)
                else:
                    units.append((i, i))
                i += 1
            if not units:
                end = next_start
            elif len(units) == 1:
                end = units[0][0]
            else:
                end = units[0][1] + 1
            sylls.append("".join(chars[cut:end]))
            cut = end
        else:
            sylls.append("".join(chars[cut:]))
    return [s for s in sylls if s]


def parse_lyrics(text: str) -> list[LyricSection]:
    sections: list[LyricSection] = []
    current = LyricSection(name="(начало)")
    sections.append(current)
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = LyricSection(name=line[1:-1].strip())
            sections.append(current)
            continue
        clean = PUNCT.sub(" ", line)
        sylls = []
        for w in clean.split():
            sylls.extend(syllabify(w))
        current.lines.append(LyricLine(text=line, syllables=sylls))
    return [s for s in sections if s.lines]


def flatten_syllables(sections: list[LyricSection]) -> list[str]:
    out = []
    for s in sections:
        for ln in s.lines:
            out.extend(ln.syllables)
    return out
