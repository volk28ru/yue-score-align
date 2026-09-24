"""lyrics.py - разбор текста песни и силлабификация (русский и латиница).

Поддержка ручной разметки слогов дефисами ("по-е-хать"), корректная
обработка мягкого/твёрдого знака на конце слова (он не образует
отдельного слога), склейка слов с дефисом ("кто-то").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯaeiouyáéíóúäöüAEIOUYÁÉÍÓÚÄÖÜ")
SOFT = set("ьъЬЪ")
PUNCT = re.compile(r"[^\w\s\-']")


@dataclass
class LyricLine:
    text: str
    syllables: list[str] = field(default_factory=list)


@dataclass
class LyricSection:
    name: str
    lines: list[LyricLine] = field(default_factory=list)


def _syllabify_auto(word: str) -> list[str]:
    """Разбивает слово на слоги по кластерам гласных."""
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
            units: list[tuple[int, int]] = []
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
    # мягкий/твёрдый знак в конце слова присоединяется к предыдущему слогу,
    # отдельного слога не образует (кластер согласных без гласной уже
    # склеен выше; здесь убираем осиротевшие знаки)
    out = []
    for s in sylls:
        if s and all(ch in SOFT for ch in s) and out:
            out[-1] += s
        else:
            out.append(s)
    return [s for s in out if s]


def syllabify(word: str) -> list[str]:
    """Слоги слова. Дефисы внутри слова — ручная граница слога.

    "по-е-хать" -> ["по", "е", "хать"]; "кто-то" (без пробелов вокруг
    дефиса и без гласной в одной из частей?) обрабатывается как единое
    слово, если части не размечены как отдельные слоги намеренно:
    часть без собственной гласной склеивается с соседней.
    """
    word = word.strip()
    if not word:
        return []
    parts = word.split("-")
    if len(parts) > 1:
        # Ручная разметка: каждая непустая часть — слог; части без гласной
        # (например, префикс "сь" или дефисное слово "кто-то", где часть
        # "то" имеет гласную — остаётся отдельно) склеиваются с соседями.
        syls = [p for p in parts if p]
        merged: list[str] = []
        for p in syls:
            has_vowel = any(ch in VOWELS for ch in p)
            if merged and not has_vowel and not any(ch in VOWELS for ch in merged[-1]):
                merged[-1] += p
            elif merged and not has_vowel and all(ch in SOFT for ch in p):
                merged[-1] += p
            else:
                merged.append(p)
        return merged
    return _syllabify_auto(word)


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
        sylls: list[str] = []
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


def section_syllables(sec: LyricSection) -> list[str]:
    out = []
    for ln in sec.lines:
        out.extend(ln.syllables)
    return out
