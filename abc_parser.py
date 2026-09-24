"""abc_parser.py - блочный парсер ABC-нотации партитур YuE2 (v3).

Поддерживает: заголовки, голоса (V:), секции (% name), встроенные смены
размера (M:), ноты с альтерациями и октавными метками, паузы z/Z,
связи (лиги) "-" — в том числе множественные (мелизмы вида `c2-c2-c2`),
аккорды и интервалы `<[CEA]>`, украшения (`~`, `.`), тактовые черты.
Добавлена валидация согласованности метра и длительностей тактов
(score.warnings).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction

BASE_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
ACC_OFFSET = {"": 0, "=": 0, "^": 1, "^^": 2, "_": -1, "__": -2}


@dataclass
class Event:
    kind: str                          # "note" | "rest" | "bar" | "section"
    pitch: int | None = None
    name: str | None = None
    duration: Fraction | None = None
    tie: bool = False                  # связь с СЛЕДУЮЩИМ событием ("-" после ноты)
    tie_start: bool = False            # связь с ПРЕДЫДУЩИМ событием ("-" перед нотой)
    rest_case: str = "z"
    section: str | None = None
    letter: str | None = None
    oct_marks: str = ""
    acc: str | None = None
    ornaments: list[str] = field(default_factory=list)   # ["~", "."] и т.п.
    chord: list[int] = field(default_factory=list)       # доп. высоты аккорда (MIDI)


@dataclass
class Block:
    voice: str
    section: str | None = None
    section_label: str | None = None
    inline: list[str] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)


@dataclass
class Score:
    fields: dict[str, str] = field(default_factory=dict)
    unit: Fraction = Fraction(1, 8)
    meter: tuple[int, int] = (4, 4)
    voice_defs: list[tuple[str, str]] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    section_order: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def vocal_id(self) -> str | None:
        for vid, _ in self.voice_defs:
            if "vocal" in vid.lower():
                return vid
        return self.blocks[0].voice if self.blocks else None

    def voice_blocks(self, vid: str) -> list[Block]:
        return [b for b in self.blocks if b.voice == vid]

    def voice_stream(self, vid: str) -> list[Event]:
        out: list[Event] = []
        last = object()
        for b in self.voice_blocks(vid):
            if b.section != last:
                out.append(Event(kind="section", section=b.section))
                last = b.section
            out.extend(b.events)
        return out


_TOKEN_RE = re.compile(
    r"""
      (?P<bar>\|\]|\|\||\|)
    | (?P<deco>[\(\)<])
    | (?P<grace>(?:\^|_|=)?[A-Ga-g](?:['"]*)?\{)
    | (?P<rest>[zZ])(?P<rest_dur>\d+(?:/\d+)?)?(?P<rest_orn>\.)?
    | (?P<acc>\^\^|__|\^|_|=)?
      (?P<letter>[A-Ga-g])
      (?P<oct>['"]*)
      (?P<dur>\d+(?:/\d+)?(?P<dotted>\.)?)?
      (?P<orn>~)?
      (?P<tie>-)?
    """,
    re.VERBOSE,
)

_HEADER_RE = re.compile(r"^(?P<key>[A-Za-z]+):\s*(?P<val>.*)$")
_METER_RE = re.compile(r"^([1-9]\d*)/([1-9]\d*)$")
_SECTION_NAME_RE = re.compile(r"^[A-Za-z][\w .'-]*$")


def _parse_mult(text: str | None, unit: Fraction, dotted: bool = False) -> Fraction:
    if not text:
        base = unit
    elif "/" in text:
        num, den = text.split("/", 1)
        base = unit * Fraction(int(num), int(den or 1))
    else:
        base = unit * int(text)
    return base * Fraction(3, 2) if dotted else base


def _parse_unit(val: str) -> Fraction:
    val = val.strip()
    if "/" in val:
        num, den = val.split("/", 1)
        try:
            return Fraction(int(num), int(den))
        except (ValueError, ZeroDivisionError):
            return Fraction(1, 8)
    return Fraction(1, int(val)) if val.isdigit() and int(val) else Fraction(1, 8)


def _parse_meter(val: str) -> tuple[int, int] | None:
    m = _METER_RE.match(val.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _midi(letter: str, oct_marks: str, acc: str | None) -> int:
    octave = 4 if letter.islower() else 3
    octave += oct_marks.count("'") - oct_marks.count(",")
    semitone = BASE_SEMITONE[letter.upper()] + ACC_OFFSET.get(acc or "", 0)
    return 12 * (octave + 1) + semitone


def _is_section_name(name: str) -> bool:
    """Секцией считается короткий `% name` без служебных символов ABC."""
    return bool(_SECTION_NAME_RE.match(name)) and len(name) <= 40


def parse(text: str) -> Score:
    score = Score()
    body_started = False
    running_section: str | None = None
    pending_label: str | None = None
    current_vid: str | None = None
    block: Block | None = None
    prev_tie = False          # предыдущая нота закончилась на "-"
    in_chord = False          # открыт аккорд/интервал "<[" ... "]>"
    chord_pitches: list[int] = []
    chord_letters: list[tuple[str, str, str | None]] = []

    def new_block(vid: str) -> Block:
        nonlocal block, pending_label, body_started
        body_started = True
        block = Block(voice=vid, section=running_section,
                      section_label=pending_label)
        pending_label = None
        score.blocks.append(block)
        return block

    def close_ties() -> None:
        """Любое не-нотное событие обрывает цепочку лиг."""
        nonlocal prev_tie, in_chord, chord_pitches, chord_letters
        prev_tie = False
        in_chord = False
        chord_pitches, chord_letters = [], []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("%"):
            name = line[1:].strip()
            if name and _is_section_name(name):
                running_section = name
                pending_label = name
                if name not in score.section_order:
                    score.section_order.append(name)
                body_started = True
            close_ties()
            continue
        m = _HEADER_RE.match(line)
        if m:
            key, val = m.group("key"), m.group("val")
            if key == "V":
                parts = val.split()
                vid = parts[0] if parts else val
                if not body_started:
                    if not any(v == vid for v, _ in score.voice_defs):
                        score.voice_defs.append((vid, val))
                    current_vid = vid
                else:
                    current_vid = vid
                    new_block(vid)
                close_ties()
                continue
            if body_started and block is not None:
                block.inline.append(line)
                if key == "L":
                    score.unit = _parse_unit(val)
                elif key == "M":
                    mm = _parse_meter(val)
                    if mm:
                        score.meter = mm
                close_ties()
                continue
            score.fields[key] = val
            if key == "L":
                score.unit = _parse_unit(val)
            elif key == "M":
                mm = _parse_meter(val)
                if mm:
                    score.meter = mm
            continue
        if block is None:
            if current_vid is None:
                current_vid = (score.voice_defs[0][0] if score.voice_defs
                               else "default")
            new_block(current_vid)
        for tok in _TOKEN_RE.finditer(line):
            if tok.group("bar"):
                close_ties()
                block.events.append(Event(kind="bar"))
            elif tok.group("deco"):
                ch = tok.group("deco")
                if ch in "<[":
                    in_chord = True
                elif ch == ">":
                    in_chord = False
                # "(" — группировка, на события не влияет
            elif tok.group("grace"):
                # мелизм-украшение вида {c} — пропускаем с предупреждением
                score.warnings.append(
                    f"пропущено украшение: {{{tok.group('grace')[:-1]}}}")
                prev_tie = False
            elif tok.group("rest"):
                close_ties()
                block.events.append(Event(
                    kind="rest",
                    duration=_parse_mult(tok.group("rest_dur"), score.unit,
                                         bool(tok.group("rest_orn"))),
                    rest_case=tok.group("rest")[0],
                    ornaments=["."] if tok.group("rest_orn") else [],
                ))
            elif tok.group("letter"):
                acc = tok.group("acc")
                letter = tok.group("letter")
                octs = tok.group("oct")
                midi = _midi(letter, octs, acc)
                if in_chord:
                    chord_pitches.append(midi)
                    chord_letters.append((letter, octs, acc))
                    continue
                octave = midi // 12 - 1
                orn = tok.group("orn") or ""
                dotted = bool(tok.group("dotted"))
                dur_text = tok.group("dur")
                if dotted and dur_text:
                    dur_text = dur_text[:-1]   # множитель без точки
                base = _parse_mult(dur_text, score.unit)
                ev = Event(
                    kind="note",
                    pitch=midi,
                    name=f"{(acc or '')}{letter.upper()}{octave}",
                    duration=base * Fraction(3, 2) if dotted else base,
                    tie=bool(tok.group("tie")),
                    tie_start=prev_tie,
                    letter=letter,
                    oct_marks=octs,
                    acc=acc,
                    ornaments=([orn] if orn else []) + (["."] if dotted else []),
                )
                if chord_pitches:
                    ev.chord = list(chord_pitches)
                    chord_pitches.clear()
                    chord_letters.clear()
                block.events.append(ev)
                prev_tie = ev.tie
    _validate_meter(score)
    return score


def _validate_meter(score: Score) -> None:
    """Проверка длительностей тактов по голосам относительно заявленного метра.

    Такты, состоящие из одной многотактовой паузы `Z` (частый случай
    инструментальных партий), пропускаются; если блок целиком состоит из
    `Z`-пауз и черт, проверяется их суммарное число тактов.
    """
    spb = Fraction(score.meter[0], score.meter[1]) / score.unit
    for b in score.blocks:
        has_notes = any(e.kind == "note" for e in b.events)
        bar_no = 1
        acc = Fraction(0)
        only_z = True          # в текущем такте были только Z-паузы
        z_bars = Fraction(0)   # суммарно тактов в Z-паузах блока
        for ev in b.events:
            if ev.kind == "bar":
                if acc != spb and acc != 0 and not only_z:
                    score.warnings.append(
                        f"{b.voice}: такт {bar_no} содержит {acc * score.unit} "
                        f"(ожидается {spb * score.unit}) при L:{score.unit}")
                bar_no += 1
                acc = Fraction(0)
                only_z = True
            elif ev.kind in ("note", "rest"):
                d = ev.duration or Fraction(0)
                if ev.kind == "rest" and ev.rest_case == "Z":
                    z_bars += d / spb
                    acc += d * spb
                else:
                    if ev.kind == "note":
                        pass
                    only_z = only_z and ev.kind == "rest"
                    acc += d
        if acc not in (Fraction(0), spb) and not only_z:
            score.warnings.append(
                f"{b.voice}: последний такт ({bar_no}) неполный: "
                f"{acc * score.unit} из {spb * score.unit}")
        if not has_notes and z_bars and z_bars.denominator != 1:
            score.warnings.append(
                f"{b.voice}: суммарные многотактовые паузы не укладываются "
                f"в целый номер тактов: {z_bars}")
