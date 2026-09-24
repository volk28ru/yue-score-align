"""cli.py - консольная карта выравнивания партитуры и текста YuE2."""
from __future__ import annotations

import argparse
import sys

from abc_parser import parse
from aligner import align
from lyrics import parse_lyrics, flatten_syllables


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Построение карты выравнивания Score (ABC) и Lyrics для YuE2")
    p.add_argument("--score", required=True, help="путь к файлу с ABC-партитурой")
    p.add_argument("--lyrics", required=True, help="путь к файлу с текстом песни")
    p.add_argument("--export-abc", metavar="FILE",
                   help="сохранить выровненный текст со слогами в файл")
    args = p.parse_args(argv)

    try:
        with open(args.score, encoding="utf-8") as f:
            score_text = f.read()
        with open(args.lyrics, encoding="utf-8") as f:
            lyrics_text = f.read()
    except OSError as e:
        print(f"Ошибка чтения файла: {e}", file=sys.stderr)
        return 1

    score = parse(score_text)
    sections = parse_lyrics(lyrics_text)
    al = align(score, sections)
    print(al.table())

    for w in score.warnings:
        print(f"ПРЕДУПРЕЖДЕНИЕ: {w}", file=sys.stderr)

    total_syll = len(flatten_syllables(sections))
    used = total_syll - len(al.leftover_syllables)
    melisma = sum(1 for r in al.rows if r.tie_start)
    print()
    print(f"Нот в вокальной линии : {len(al.rows)}")
    print(f"Мелизмов (тянучек)    : {melisma}")
    print(f"Слогов в тексте       : {total_syll}")
    print(f"Слогов распределено   : {used}")
    print(f"Слогов без нот        : {len(al.leftover_syllables)}")
    print(f"Нот без слога         : {al.notes_without_syllable}")

    if args.export_abc:
        from abc_writer import to_abc
        with open(args.export_abc, "w", encoding="utf-8") as f:
            f.write(to_abc(score))
        print(f"ABC сохранён в {args.export_abc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
