"""server.py - лёгкий веб-сервер редактора yue-score-align (v4).

Исправления: защита от path traversal через Path.is_relative_to,
валидация входных данных с кодом 400 вместо 500, ограничение размера
тела запроса, хост/порт настраиваются через аргументы командной строки
и переменные окружения, ответ /api/align дополнен готовым layout-JSON
(сетка тактов, секции, блоки дорожек) — клиенту не нужно дублировать
парсинг.
"""
from __future__ import annotations

import argparse
import json
import os
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from abc_parser import Block, Event, parse
from abc_writer import to_abc
from aligner import align
from lyrics import parse_lyrics

WEB = (Path(__file__).parent / "web").resolve()
MAX_BODY = 8 * 1024 * 1024          # 8 MiB
DEFAULT_HOST = os.environ.get("YUE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("YUE_PORT", "8090"))


class BadRequest(Exception):
    pass


def event_to_json(ev: Event, syllable: str | None = None) -> dict:
    return {
        "kind": ev.kind, "name": ev.name, "pitch": ev.pitch,
        "dur": str(ev.duration) if ev.duration else None,
        "tie": ev.tie, "tie_start": ev.tie_start,
        "rest_case": ev.rest_case, "section": ev.section,
        "letter": ev.letter, "oct_marks": ev.oct_marks, "acc": ev.acc,
        "ornaments": list(ev.ornaments), "chord": list(ev.chord),
        "syllable": syllable,
    }


def json_to_event(d: dict) -> Event:
    if not isinstance(d, dict) or d.get("kind") not in (
            "note", "rest", "bar", "section"):
        raise BadRequest(f"некорректное событие: {d!r}")
    dur = d.get("dur")
    try:
        duration = Fraction(str(dur)) if dur else None
    except (ValueError, ZeroDivisionError):
        raise BadRequest(f"некорректная длительность: {dur!r}")
    pitch = d.get("pitch")
    if pitch is not None and not isinstance(pitch, int):
        raise BadRequest("поле pitch должно быть целым числом")
    return Event(
        kind=d["kind"], pitch=pitch, name=d.get("name"),
        duration=duration,
        tie=bool(d.get("tie", False)), tie_start=bool(d.get("tie_start", False)),
        rest_case=d.get("rest_case", "z"),
        section=d.get("section"), letter=d.get("letter"),
        oct_marks=d.get("oct_marks", "") or "", acc=d.get("acc"),
        ornaments=list(d.get("ornaments", []) or []),
        chord=[int(p) for p in d.get("chord", []) or []],
    )


def block_to_json(b: Block, vid, rows, counter: list) -> dict:
    evs = []
    for ev in b.events:
        syl = None
        if b.voice == vid and ev.kind == "note":
            syl = rows[counter[0]].syllable if counter[0] < len(rows) else None
            counter[0] += 1
        evs.append(event_to_json(ev, syl))
    return {
        "voice": b.voice, "section": b.section,
        "section_label": b.section_label, "inline": list(b.inline),
        "events": evs,
    }


def json_to_block(d: dict) -> Block:
    if not isinstance(d, dict) or "voice" not in d:
        raise BadRequest("блок без имени голоса")
    events = d.get("events", [])
    if not isinstance(events, list):
        raise BadRequest("events должен быть списком")
    return Block(
        voice=str(d["voice"]), section=d.get("section"),
        section_label=d.get("section_label"),
        inline=[str(x) for x in (d.get("inline", []) or [])],
        events=[json_to_event(e) for e in events],
    )


# ---------------- layout (единый источник истины для клиента) ----------

def _meter_steps(meter: tuple[int, int], unit: Fraction) -> int:
    return max(1, round(Fraction(meter[0], meter[1]) / unit))


def build_layout(score, blocks_json, vid) -> dict:
    """Сетка тактов, секции и позиции блоков в шагах базового L:."""
    unit = score.unit
    header_meter = score.meter
    layout_voices = {}
    for voice in [vid] + [b.voice for b in score.blocks if b.voice != vid]:
        spb = _meter_steps(header_meter, unit)
        pending = None
        cursor = 0
        bar_positions: list[int] = []
        slot_start = 0
        sections = []
        cur_section = None
        ev_blocks = []
        for bi, bj in enumerate(blocks_json):
            if bj["voice"] != voice:
                continue
            for ln in bj.get("inline", []):
                if ln.startswith("M:"):
                    try:
                        num, den = ln[2:].strip().split("/")
                        pending = _meter_steps((int(num), int(den)), unit)
                    except (ValueError, ZeroDivisionError):
                        pass
            sec = bj.get("section")
            if sec and sec != cur_section:
                cur_section = sec
                sections.append({"name": sec, "start": cursor, "end": None})
            for ei, ev in enumerate(bj["events"]):
                kind = ev["kind"]
                if kind == "bar":
                    if pending:
                        spb = pending
                        pending = None
                    slot_start += spb
                    bar_positions.append(slot_start)
                    continue
                if kind not in ("note", "rest"):
                    continue
                try:
                    mult = Fraction(ev["dur"]) / unit
                except (KeyError, ValueError, ZeroDivisionError):
                    mult = Fraction(1)
                steps = max(1, round(mult))
                if kind == "rest" and ev.get("rest_case") == "Z":
                    steps *= spb
                ev_blocks.append({"bi": bi, "ei": ei, "start": cursor,
                                  "dur": steps, "kind": kind})
                cursor += steps
        for i in range(len(sections)):
            sections[i]["end"] = (sections[i + 1]["start"]
                                  if i + 1 < len(sections) else cursor)
        if not sections:
            sections = [{"name": "(без секции)", "start": 0, "end": cursor}]
        while slot_start < cursor:
            slot_start += spb
            bar_positions.append(slot_start)
        layout_voices[voice] = {
            "evBlocks": ev_blocks, "sections": sections,
            "total": max(cursor, slot_start), "barPositions": bar_positions,
        }
    total = max((v["total"] for v in layout_voices.values()), default=0)
    return {"unit": f"{unit.numerator}/{unit.denominator}",
            "stepsPerBar": _meter_steps(header_meter, unit),
            "voices": layout_voices, "total": total}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def _error(self, code: int, msg: str) -> None:
        self._json({"error": msg}, code)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/":
            path = "/index.html"
        try:
            file = (WEB / path.lstrip("/")).resolve()
        except OSError:
            self._send(400, b"bad path", "text/plain")
            return
        if not file.is_relative_to(WEB) or not file.is_file():
            self._send(404, b"not found", "text/plain")
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }.get(file.suffix, "application/octet-stream")
        try:
            self._send(200, file.read_bytes(), ctype)
        except OSError:
            self._send(404, b"not found", "text/plain")

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            raise BadRequest("некорректный Content-Length")
        if length <= 0:
            raise BadRequest("пустое тело запроса")
        if length > MAX_BODY:
            raise BadRequest(f"тело запроса превышает {MAX_BODY} байт")
        try:
            data = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise BadRequest("тело запроса не является корректным JSON")
        if not isinstance(data, dict):
            raise BadRequest("ожидается JSON-объект")
        return data

    def do_POST(self) -> None:
        try:
            data = self._read_body()
            if self.path == "/api/align":
                self._handle_align(data)
            elif self.path == "/api/export":
                self._handle_export(data)
            else:
                self._error(404, "неизвестный endpoint")
        except BadRequest as e:
            self._error(400, str(e))
        except Exception as e:                       # noqa: BLE001
            self._error(500, f"внутренняя ошибка: {e}")

    def _handle_align(self, data: dict) -> None:
        score_text = data.get("score")
        lyrics_text = data.get("lyrics", "")
        if not isinstance(score_text, str) or not score_text.strip():
            raise BadRequest("поле score (текст ABC) обязательно")
        if not isinstance(lyrics_text, str):
            raise BadRequest("поле lyrics должно быть строкой")
        score = parse(score_text)
        sections = parse_lyrics(lyrics_text)
        al = align(score, sections)
        vid = score.vocal_id()
        counter = [0]
        blocks_json = [block_to_json(b, vid, al.rows, counter)
                       for b in score.blocks]
        self._json({
            "unit": str(score.unit),
            "meter": f"{score.meter[0]}/{score.meter[1]}",
            "vocal_id": vid,
            "blocks": blocks_json,
            "layout": build_layout(score, blocks_json, vid),
            "leftover": al.leftover_syllables,
            "notes_without_syllable": al.notes_without_syllable,
            "sections": score.section_order,
            "align_mode": al.mode,
            "section_map": al.section_map,
            "warnings": score.warnings,
        })

    def _handle_export(self, data: dict) -> None:
        score_text = data.get("score")
        if not isinstance(score_text, str) or not score_text.strip():
            raise BadRequest("поле score (текст ABC) обязательно")
        raw_blocks = data.get("blocks", [])
        if not isinstance(raw_blocks, list):
            raise BadRequest("поле blocks должно быть списком")
        score = parse(score_text)
        score.blocks = [json_to_block(d) for d in raw_blocks]
        self._json({"abc": to_abc(score)})

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    p = argparse.ArgumentParser(description="Веб-сервер yue-score-align")
    p.add_argument("--host", default=DEFAULT_HOST,
                   help=f"адрес (по умолчанию {DEFAULT_HOST})")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"порт (по умолчанию {DEFAULT_PORT})")
    args = p.parse_args()
    print(f"Редактор yue-score-align: http://{args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
