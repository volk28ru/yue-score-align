"""cli.py - консольная карта выравнивания партитуры и текста YuE2."""
from __future__ import annotations

import argparse

from abc_parser import parse
from aligner import align
from lyrics import parse_lyrics, flatten_syllables


def main() -> None:
    p = argparse.ArgumentParser(
        description="Построение карты выравнивания Score (ABC) и Lyrics для YuE2")
    p.add_argument("--score", required=True, help="путь к файлу с ABC-партитурой")
    p.add_argument("--lyrics", required=True, help="путь к файлу с текстом песни")
    args = p.parse_args()

    with open(args.score, encoding="utf-8") as f:
        score = parse(f.read())
    with open(args.lyrics, encoding="utf-8") as f:
        sections = parse_lyrics(f.read())

    al = align(score, sections)
    print(al.table())

    total_syll = len(flatten_syllables(sections))
    used = total_syll - len(al.leftover_syllables)
    melisma = sum(1 for i, r in enumerate(al.rows) if i and al.rows[i - 1].tie)
    print()
    print(f"Нот в вокальной линии : {len(al.rows)}")
    print(f"Мелизмов (тянучек)    : {melisma}")
    print(f"Слогов в тексте       : {total_syll}")
    print(f"Слогов распределено   : {used}")
    print(f"Слогов без нот        : {len(al.leftover_syllables)}")
    print(f"Нот без слога         : {al.notes_without_syllable}")


if __name__ == "__main__":
    main()
