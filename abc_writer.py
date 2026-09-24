"""abc_writer.py - сериализация блочной партитуры обратно в текст ABC (v3).

Исправления: корректная сериализация многотактовых пауз `Z<n>`
(длительность хранится в базовых шагах `L:`, поэтому для `Z` пишется
множитель в тактах), перенос длинных строк для читаемости, канонический
порядок заголовков (X, T, C, M, L, Q, K…), сохранение украшений и
лиг начала (`-c`).
"""
from __future__ import annotations

from fractions import Fraction

from abc_parser import Event, Score

_HEADER_ORDER = ["X", "T", "C", "O", "S", "D", "R", "M", "L", "Q", "K"]
_LINE_WIDTH = 100


def dur_token(ev: Event, unit: Fraction) -> str:
    """Множитель длительности в базовых шагах (без точки).

    Для точкованной ноты (`c4.` = 6 шагов при L:1/16) пишется НЕточная
    основа (4), а точку добавляет event_tokens — иначе "c6." означало бы
    9 шагов вместо 6.
    """
    mult = ev.duration / unit
    if "." in ev.ornaments and mult.denominator == 2 and mult.numerator % 3 == 0:
        mult = mult * Fraction(2, 3)      # обратно к неосновной длительности
    if mult.denominator == 1:
        return "" if mult.numerator == 1 else str(mult.numerator)
    return f"{mult.numerator}/{mult.denominator}"


def event_tokens(ev: Event, unit: Fraction,
                 steps_per_bar: Fraction | None = None) -> list[str]:
    if ev.kind == "bar":
        return ["|"]
    if ev.kind == "rest":
        if ev.rest_case == "Z" and steps_per_bar and steps_per_bar > 0:
            bars = ev.duration / steps_per_bar
            if bars.denominator == 1 and bars.numerator >= 1:
                # Z всегда с множителем: явное "Z1" однозначнее голого "Z"
                return [f"Z{bars.numerator}"]
        tok = dur_token(ev, unit)
        if "." in ev.ornaments:
            tok += "."
        return [ev.rest_case + tok]
    if ev.kind == "note":
        head = "-" if ev.tie_start else ""
        core = ((ev.acc or "") + (ev.letter or "C") + ev.oct_marks
                + "".join(o for o in ev.ornaments if o != ".")
                + dur_token(ev, unit)
                + ("." if "." in ev.ornaments else ""))
        chord = ""
        if ev.chord:
            inner = "".join(_pitch_letter(p) for p in ev.chord)
            chord = f"[{inner}]"
        return [head + chord + core + ("-" if ev.tie else "")]
    return []


_PITCH_NAMES = ["C", "C", "D", "D", "E", "F", "F", "G", "G", "A", "A", "B"]
_PITCH_ACC = ["", "^", "", "^", "", "", "^", "", "^", "", "^", ""]


def _pitch_letter(midi: int) -> str:
    pc = midi % 12
    octave = midi // 12 - 1
    letter = _PITCH_NAMES[pc]
    acc = _PITCH_ACC[pc]
    if octave >= 4:
        return acc + letter.lower() + "'" * (octave - 4)
    return acc + letter + "," * (3 - octave)


def to_abc(score: Score) -> str:
    steps_per_bar = (Fraction(score.meter[0], score.meter[1]) / score.unit
                     if score.meter[1] else None)
    out: list[str] = []
    keys = [k for k in _HEADER_ORDER if k in score.fields]
    keys += [k for k in score.fields if k not in _HEADER_ORDER and k != "K"]
    for key in keys:
        out.append(f"{key}:{score.fields[key]}")
    for vid, defn in score.voice_defs:
        out.append(f"V:{defn}")
    if "K" in score.fields:
        out.append(f"K:{score.fields['K']}")
    for b in score.blocks:
        if b.section_label:
            out.append(f"% {b.section_label}")
        out.append(f"V:{b.voice}")
        out.extend(b.inline)
        buf: list[str] = []
        line_len = 0
        for ev in b.events:
            for tok in event_tokens(ev, score.unit, steps_per_bar):
                if line_len + len(tok) > _LINE_WIDTH and buf:
                    out.append("".join(buf))
                    buf, line_len = [], 0
                buf.append(tok)
                line_len += len(tok)
        if buf:
            out.append("".join(buf))
    return "\n".join(out) + "\n"
