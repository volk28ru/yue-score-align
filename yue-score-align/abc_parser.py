"""abc_parser.py - блочный парсер ABC-нотации партитур YuE2 (v2)."""
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
    tie: bool = False
    rest_case: str = "z"
    section: str | None = None
    letter: str | None = None
    oct_marks: str = ""
    acc: str | None = None


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
    voice_defs: list[tuple[str, str]] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    section_order: list[str] = field(default_factory=list)

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
    | (?P<rest>[zZ])(?P<rest_dur>\d+(?:/\d+)?)?
    | (?P<acc>\^\^|__|\^|_|=)?
      (?P<letter>[A-Ga-g])
      (?P<oct>[,'"]*)
      (?P<dur>\d+(?:/\d+)?)?
      (?P<tie>-)?
    """,
    re.VERBOSE,
)

_HEADER_RE = re.compile(r"^(?P<key>[A-Za-z]+):\s*(?P<val>.*)$")


def _parse_mult(text: str | None, unit: Fraction) -> Fraction:
    if not text:
        return unit
    if "/" in text:
        num, den = text.split("/", 1)
        return unit * Fraction(int(num), int(den or 1))
    return unit * int(text)


def _parse_unit(val: str) -> Fraction:
    val = val.strip()
    if "/" in val:
        num, den = val.split("/", 1)
        return Fraction(int(num), int(den))
    return Fraction(1, int(val)) if val.isdigit() else Fraction(1, 8)


def _midi(letter: str, oct_marks: str, acc: str | None) -> int:
    octave = 4 if letter.islower() else 3
    octave += oct_marks.count("'") - oct_marks.count(",")
    semitone = BASE_SEMITONE[letter.upper()] + ACC_OFFSET.get(acc or "", 0)
    return 12 * (octave + 1) + semitone


def parse(text: str) -> Score:
    score = Score()
    body_started = False
    running_section: str | None = None
    pending_label: str | None = None
    current_vid: str | None = None
    block: Block | None = None

    def new_block(vid: str) -> Block:
        nonlocal block, pending_label, body_started
        body_started = True
        block = Block(voice=vid, section=running_section,
                      section_label=pending_label)
        pending_label = None
        score.blocks.append(block)
        return block

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("%"):
            name = line[1:].strip()
            if name:
                running_section = name
                pending_label = name
                if name not in score.section_order:
                    score.section_order.append(name)
                body_started = True
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
                continue
            if body_started and block is not None:
                block.inline.append(line)
                if key == "L":
                    score.unit = _parse_unit(val)
                continue
            score.fields[key] = val
            if key == "L":
                score.unit = _parse_unit(val)
            continue
        if block is None:
            if current_vid is None:
                current_vid = (score.voice_defs[0][0] if score.voice_defs
                               else "default")
            new_block(current_vid)
        for tok in _TOKEN_RE.finditer(line):
            if tok.group("bar"):
                block.events.append(Event(kind="bar"))
            elif tok.group("rest"):
                block.events.append(Event(
                    kind="rest",
                    duration=_parse_mult(tok.group("rest_dur"), score.unit),
                    rest_case=tok.group("rest")[0],
                ))
            elif tok.group("letter"):
                acc = tok.group("acc")
                letter = tok.group("letter")
                octs = tok.group("oct")
                midi = _midi(letter, octs, acc)
                octave = midi // 12 - 1
                block.events.append(Event(
                    kind="note",
                    pitch=midi,
                    name=f"{(acc or '')}{letter.upper()}{octave}",
                    duration=_parse_mult(tok.group("dur"), score.unit),
                    tie=bool(tok.group("tie")),
                    letter=letter,
                    oct_marks=octs,
                    acc=acc,
                ))
    return score
