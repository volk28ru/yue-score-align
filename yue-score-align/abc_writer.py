"""abc_writer.py - сериализация блочной партитуры обратно в текст ABC (v2)."""
from __future__ import annotations

from fractions import Fraction

from abc_parser import Event, Score


def dur_token(ev: Event, unit: Fraction) -> str:
    mult = ev.duration / unit
    if mult.denominator == 1:
        return "" if mult.numerator == 1 else str(mult.numerator)
    return f"{mult.numerator}/{mult.denominator}"


def event_token(ev: Event, unit: Fraction) -> str | None:
    if ev.kind == "bar":
        return "|"
    if ev.kind == "rest":
        return ev.rest_case + dur_token(ev, unit)
    if ev.kind == "note":
        return ((ev.acc or "") + (ev.letter or "C") + ev.oct_marks
                + dur_token(ev, unit) + ("-" if ev.tie else ""))
    return None


def to_abc(score: Score) -> str:
    out = []
    for key, val in score.fields.items():
        if key in ("X", "T", "M", "L", "Q"):
            out.append(f"{key}:{val}")
    for vid, defn in score.voice_defs:
        out.append(f"V: {defn}")
    if "K" in score.fields:
        out.append(f"K:{score.fields['K']}")
    for b in score.blocks:
        if b.section_label:
            out.append(f"% {b.section_label}")
        out.append(f"V: {b.voice}")
        out.extend(b.inline)
        buf = []
        for ev in b.events:
            tok = event_token(ev, score.unit)
            if tok:
                buf.append(tok)
        out.append("".join(buf))
    return "\n".join(out) + "\n"
