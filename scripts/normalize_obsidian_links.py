#!/usr/bin/env python3
"""Normalize Obsidian wikilinks against the actual vault files.

The script uses real Markdown files only. It rewrites resolvable path/extension/
URL-encoded variants to the unique note stem and fails loudly for ambiguous or
unresolved links so the pipeline never reports a false healthy graph.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

WIKILINK = re.compile(r"\[\[([^\]|#]+)(#[^\]|]+)?(\|[^\]]+)?\]\]")


def key(value: str) -> str:
    value = unquote(value.strip()).replace("\\", "/")
    value = value.removeprefix("./").lstrip("/")
    if value.lower().endswith(".md"):
        value = value[:-3]
    return value.casefold().strip()


def note_maps(vault: Path) -> tuple[dict[str, set[str]], dict[str, Path]]:
    aliases: dict[str, set[str]] = {}
    paths: dict[str, Path] = {}
    for note in sorted(vault.rglob("*.md")):
        rel = note.relative_to(vault).as_posix()
        stem = note.stem
        paths[stem] = note
        variants = {key(rel), key(rel[:-3] if rel.lower().endswith(".md") else rel), key(stem)}
        for variant in variants:
            aliases.setdefault(variant, set()).add(stem)
    return aliases, paths


def normalize_vault(vault: Path) -> tuple[int, int, list[str]]:
    aliases, _ = note_maps(vault)
    changed = 0
    unresolved: list[str] = []
    for note in sorted(vault.rglob("*.md")):
        original = note.read_text(encoding="utf-8", errors="ignore")

        def replace(match: re.Match[str]) -> str:
            target, heading, alias = match.group(1), match.group(2) or "", match.group(3) or ""
            candidates = aliases.get(key(target), set())
            if len(candidates) == 1:
                canonical = next(iter(candidates))
                return f"[[{canonical}{heading}{alias}]]"
            if len(candidates) > 1:
                unresolved.append(f"ambiguous: {note.relative_to(vault)} -> {target}")
            else:
                unresolved.append(f"unresolved: {note.relative_to(vault)} -> {target}")
            return match.group(0)

        updated = WIKILINK.sub(replace, original)
        if updated != original:
            note.write_text(updated, encoding="utf-8")
            changed += 1
    return changed, len(unresolved), unresolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", default="obsidian/JARVIS_LUNA", type=Path)
    parser.add_argument("--allow-unresolved", action="store_true")
    args = parser.parse_args()
    if not args.vault.exists():
        print(f"vault not found: {args.vault}", file=sys.stderr)
        return 2
    files_changed, unresolved_count, unresolved = normalize_vault(args.vault)
    print(f"normalized files: {files_changed}")
    print(f"unresolved or ambiguous links: {unresolved_count}")
    for item in unresolved[:100]:
        print(item)
    if unresolved_count and not args.allow_unresolved:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

