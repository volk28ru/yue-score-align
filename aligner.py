"""aligner.py - сопоставление слогов текста нотам вокальной линии YuE2 (v2)."""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from abc_parser import Score
from lyrics import LyricSection, flatten_syllables


@dataclass
class Row:
    section: str
    name: str
    midi: int
    duration: Fraction
    syllable: str | None
    tie: bool


@dataclass
class Alignment:
    rows: list[Row] = field(default_factory=list)
    leftover_syllables: list[str] = field(default_factory=list)
    notes_without_syllable: int = 0

    def table(self) -> str:
        lines = ["Нота     Длит.    Слог"]
        cur = None
        for r in self.rows:
            if r.section != cur:
                cur = r.section
                lines.append(f"-- {cur} --")
            syl = r.syllable if r.syllable is not None else "(вокализ)"
            mark = " ~" if r.tie else ""
            lines.append(f"{r.name:8s} {str(r.duration):8s} {syl}{mark}")
        if self.leftover_syllables:
            lines.append("Лишние слоги: " + " ".join(self.leftover_syllables))
        if self.notes_without_syllable:
            lines.append(f"Нот без слога: {self.notes_without_syllable}")
        return "\n".join(lines)


def align(score: Score, sections: list[LyricSection]) -> Alignment:
    stream = score.voice_stream(score.vocal_id())
    al = Alignment()
    if not stream:
        return al
    sylls = flatten_syllables(sections)
    idx = 0
    current_section = "(без секции)"
    last_tie = False
    for ev in stream:
        if ev.kind == "section":
            current_section = ev.section or current_section
            last_tie = False
            continue
        if ev.kind != "note":
            last_tie = False
            continue
        if last_tie:
            syl = al.rows[-1].syllable if al.rows else None
        else:
            syl = sylls[idx] if idx < len(sylls) else None
            if syl is None:
                al.notes_without_syllable += 1
            else:
                idx += 1
        al.rows.append(Row(current_section, ev.name or "?", ev.pitch or 0,
                           ev.duration or Fraction(0), syl, ev.tie))
        last_tie = ev.tie
    al.leftover_syllables = sylls[idx:]
    return al


if __name__ == "__main__":
    from abc_parser import parse
    from lyrics import parse_lyrics

    score_text = """X:1
M:4/4
L:1/32
Q:1/4=76
K:Gm
V: Vocal
% chorus
z24z4G4|B4G4B4d4g4-g4z12|
"""
    lyrics_text = """[Chorus]
Не выпьем больше чай.
"""
    al = align(parse(score_text), parse_lyrics(lyrics_text))
    print(al.table())
