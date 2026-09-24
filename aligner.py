"""aligner.py - сопоставление слогов текста нотам вокальной линии YuE2 (v3).

Выравнивание выполняется ПОСЕКЦИОННО: музыкальные секции (`% verse`,
`% chorus`) сопоставляются текстовым (`[Verse]`) по нормализованным
именам; при успешном сопоставлении слоги каждой секции распределяются
только по нотам своей секции. Если сопоставить секции не удаётся
(разное число/имена), включается глобальное выравнивание как fallback.
Мелизмы (цепочки лиг, в т.ч. множественные `c-c-c`) наследуют слог
первой ноты цепочки.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction

from abc_parser import Score
from lyrics import LyricSection, flatten_syllables, section_syllables


@dataclass
class Row:
    section: str
    name: str
    midi: int
    duration: Fraction
    syllable: str | None
    tie: bool
    tie_start: bool = False


@dataclass
class Alignment:
    rows: list[Row] = field(default_factory=list)
    leftover_syllables: list[str] = field(default_factory=list)
    notes_without_syllable: int = 0
    mode: str = "global"                       # "per-section" | "global"
    section_map: dict[str, str] = field(default_factory=dict)

    def table(self) -> str:
        lines = [f"Режим выравнивания: {self.mode}"]
        if self.section_map:
            for ms, ls in self.section_map.items():
                lines.append(f"  секция '{ms}' <- текст '[{ls}]'")
        lines.append("Нота     Длит.    Слог")
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


def _norm_name(name: str) -> str:
    """Нормализация имени секции для сопоставления: 'Chorus 2' -> 'chorus'."""
    n = re.sub(r"[^a-zа-яё]+", " ", name.lower()).strip()
    first = n.split(" ")[0] if n else ""
    aliases = {
        "куплет": "verse", "припев": "chorus", "вступление": "intro",
        "проигрыш": "solo", "бридж": "bridge", "кода": "outro",
        "концовка": "outro", "предприпев": "prechorus",
    }
    first = aliases.get(first, first)
    # убираем нумерацию: "verse 2" -> "verse"
    return first


def _music_sections(score: Score, vid: str) -> dict[str, list[int]]:
    """Порядок музыкальных секций -> индексы событий-нот в rows-потоке."""
    order: dict[str, list[int]] = {}
    current = "(без секции)"
    idx = 0
    for ev in score.voice_stream(vid):
        if ev.kind == "section":
            current = ev.section or current
        elif ev.kind == "note":
            order.setdefault(current, [])
            order[current].append(idx)
            idx += 1
    return order


def align(score: Score, sections: list[LyricSection]) -> Alignment:
    al = Alignment()
    vid = score.vocal_id()
    stream = [e for e in score.voice_stream(vid) if e.kind == "note"]
    if not stream:
        return al
    sec_notes = _music_sections(score, vid)
    total_notes = sum(len(v) for v in sec_notes.values())
    # строки заранее, чтобы назначать слоги по индексам
    cur_sec = "(без секции)"
    si = 0
    for ev in score.voice_stream(vid):
        if ev.kind == "section":
            cur_sec = ev.section or cur_sec
        elif ev.kind == "note":
            al.rows.append(Row(cur_sec, ev.name or "?", ev.pitch or 0,
                               ev.duration or Fraction(0), None,
                               ev.tie, ev.tie_start))
            si += 1

    def assign(note_indices: list[int], sylls: list[str]) -> list[str]:
        """Распределяет слоги по нотам одной группы; возвращает остаток."""
        pos = 0
        prev_tie = False
        prev_syl: str | None = None
        leftover_start = len(sylls)
        for ni in note_indices:
            r = al.rows[ni]
            if prev_tie and r.tie_start:
                r.syllable = prev_syl          # продолжение мелизмы
            else:
                if pos < len(sylls):
                    r.syllable = sylls[pos]
                    pos += 1
                else:
                    r.syllable = None
                    al.notes_without_syllable += 1
            prev_syl = r.syllable
            prev_tie = r.tie
        leftover_start = pos
        return sylls[leftover_start:]

    # --- попытка посекционного сопоставления ---
    ly_by_norm: dict[str, list[LyricSection]] = {}
    for ls in sections:
        ly_by_norm.setdefault(_norm_name(ls.name), []).append(ls)
    mus_names = [m for m in sec_notes if m != "(без секции)"]
    matched: dict[str, LyricSection] = {}
    used_ids: set[int] = set()
    # Жадное сопоставление по нормализованным именам; секции музыки без
    # текстового аналога (например, инструментальное intro) допустимы —
    # их ноты остаются вокализами. Режим посекционным считается, если
    # сопоставлена хотя бы одна секция и покрыты все текстовые секции
    # (иначе слоги «поплывут» между строфами — лучше глобальный режим).
    for mn in mus_names:
        cands = ly_by_norm.get(_norm_name(mn), [])
        chosen = next((c for c in cands if id(c) not in used_ids), None)
        if chosen is not None:
            used_ids.add(id(chosen))
            matched[mn] = chosen
    uncovered_text = any(id(ls) not in used_ids for ls in sections)
    if matched and not uncovered_text:
        al.mode = "per-section"
        al.section_map = {m: s.name for m, s in matched.items()}
        leftovers: list[str] = []
        for mn, note_idx in sec_notes.items():
            if mn in matched:
                leftovers.extend(assign(note_idx,
                                        section_syllables(matched[mn])))
            else:
                # секция без текста — все её ноты остаются без слога
                assign(note_idx, [])
        unmatched_lyr = [ls for ls in sections if id(ls) not in used_ids]
        for ls in unmatched_lyr:
            leftovers.extend(section_syllables(ls))
        al.leftover_syllables = leftovers
        return al

    # --- глобальный fallback ---
    al.mode = "global"
    al.rows = [Row(*[getattr(r, f) for f in ("section", "name", "midi",
                                             "duration")],
                   None, r.tie, r.tie_start) for r in al.rows]
    al.notes_without_syllable = 0
    all_idx = list(range(total_notes))
    al.leftover_syllables = assign(all_idx, flatten_syllables(sections))
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
