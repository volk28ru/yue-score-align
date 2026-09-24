"""server.py - лёгкий веб-сервер редактора yue-score-align (порт 8090, v3)."""
from __future__ import annotations

import json
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from abc_parser import Block, Event, parse
from abc_writer import to_abc
from aligner import align
from lyrics import parse_lyrics

WEB = (Path(__file__).parent / "web").resolve()
PORT = 8090


def event_to_json(ev: Event, syllable: str | None = None) -> dict:
    return {
        "kind": ev.kind, "name": ev.name, "pitch": ev.pitch,
        "dur": str(ev.duration) if ev.duration else None,
        "tie": ev.tie, "rest_case": ev.rest_case, "section": ev.section,
        "letter": ev.letter, "oct_marks": ev.oct_marks, "acc": ev.acc,
        "syllable": syllable,
    }


def json_to_event(d: dict) -> Event:
    return Event(
        kind=d["kind"], pitch=d.get("pitch"), name=d.get("name"),
        duration=Fraction(d["dur"]) if d.get("dur") else None,
        tie=d.get("tie", False), rest_case=d.get("rest_case", "z"),
        section=d.get("section"), letter=d.get("letter"),
        oct_marks=d.get("oct_marks", ""), acc=d.get("acc"),
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
    return Block(
        voice=d["voice"], section=d.get("section"),
        section_label=d.get("section_label"),
        inline=list(d.get("inline", [])),
        events=[json_to_event(e) for e in d.get("events", [])],
    )


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj) -> None:
        self._send(200, json.dumps(obj, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/":
            path = "/index.html"
        file = (WEB / path.lstrip("/")).resolve()
        if not str(file).startswith(str(WEB)):
            self._send(404, b"not found", "text/plain")
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }.get(file.suffix, "application/octet-stream")
        try:
            self._send(200, file.read_bytes(), ctype)
        except OSError:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/align":
            score = parse(data.get("score", ""))
            sections = parse_lyrics(data.get("lyrics", ""))
            al = align(score, sections)
            vid = score.vocal_id()
            counter = [0]
            blocks_json = [block_to_json(b, vid, al.rows, counter)
                           for b in score.blocks]
            self._json({
                "unit": str(score.unit),
                "vocal_id": vid,
                "blocks": blocks_json,
                "leftover": al.leftover_syllables,
                "syllables": [r.syllable for r in al.rows],
                "notes_without_syllable": al.notes_without_syllable,
                "sections": score.section_order,
            })
        elif self.path == "/api/export":
            score = parse(data.get("score", ""))
            score.blocks = [json_to_block(d) for d in data.get("blocks", [])]
            self._json({"abc": to_abc(score)})
        else:
            self._send(404, b"{}", "application/json")

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    print(f"Редактор yue-score-align: http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
