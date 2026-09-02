#!/usr/bin/env python3
"""Normalize Obsidian wikilinks against the actual vault files.

Resolvable path/extension/URL-encoded variants are rewritten to the unique note
stem. Ambiguous targets prefer an exact stem match, then the longest stem;
remaining true unknowns are reported. By default unresolved links no longer
hard-fail the whole JARVIS pipeline (use --strict to restore old behavior).
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
        variants = {
            key(rel),
            key(rel[:-3] if rel.lower().endswith(".md") else rel),
            key(stem),
        }
        # also register basename-only path segments for deeper folders
        parts = Path(rel).parts
        if len(parts) >= 2:
            variants.add(key(parts[-1]))
            variants.add(key(Path(parts[-1]).stem))
        for variant in variants:
            if variant:
                aliases.setdefault(variant, set()).add(stem)
    return aliases, paths


def pick_candidate(target: str, candidates: set[str]) -> str | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return next(iter(candidates))
    t = key(target)
    # 1) exact stem
    exact = [c for c in candidates if key(c) == t]
    if len(exact) == 1:
        return exact[0]
    # 2) stem endswith / startswith target (Record-051... links)
    partial = [c for c in candidates if key(c) == t or key(c).endswith(t) or t.endswith(key(c))]
    if len(partial) == 1:
        return partial[0]
    if partial:
        # longest stem usually is the full Record-* filename
        return sorted(partial, key=lambda c: (-len(c), c))[0]
    # 3) stable fallback so pipeline can continue
    return sorted(candidates, key=lambda c: (-len(c), c))[0]


def normalize_vault(vault: Path) -> tuple[int, int, list[str]]:
    aliases, _ = note_maps(vault)
    changed = 0
    problems: list[str] = []
    for note in sorted(vault.rglob("*.md")):
        original = note.read_text(encoding="utf-8", errors="ignore")

        def replace(match: re.Match[str]) -> str:
            target, heading, alias = match.group(1), match.group(2) or "", match.group(3) or ""
            candidates = aliases.get(key(target), set())
            if not candidates:
                # try basename of target path
                base = key(Path(target.replace("\\", "/")).name)
                candidates = aliases.get(base, set())
            chosen = pick_candidate(target, candidates)
            if chosen is None:
                problems.append(f"unresolved: {note.relative_to(vault)} -> {target}")
                return match.group(0)
            if len(candidates) > 1 and key(chosen) != key(target):
                problems.append(
                    f"ambiguous-resolved: {note.relative_to(vault)} -> {target} => {chosen}"
                )
            return f"[[{chosen}{heading}{alias}]]"

        updated = WIKILINK.sub(replace, original)
        if updated != original:
            note.write_text(updated, encoding="utf-8")
            changed += 1
    unresolved_only = [p for p in problems if p.startswith("unresolved:")]
    return changed, len(unresolved_only), problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", default="obsidian/JARVIS_LUNA", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if any unresolved link remains (old behavior)",
    )
    parser.add_argument(
        "--allow-unresolved",
        action="store_true",
        help="deprecated alias: same as default non-strict mode",
    )
    args = parser.parse_args()
    if not args.vault.exists():
        print(f"vault not found: {args.vault}", file=sys.stderr)
        return 2
    files_changed, unresolved_count, problems = normalize_vault(args.vault)
    print(f"normalized files: {files_changed}")
    print(f"unresolved links: {unresolved_count}")
    print(f"notes (ambiguous-resolved + unresolved): {len(problems)}")
    for item in problems[:100]:
        print(item)
    if unresolved_count and args.strict:
        return 1
    # default: warn but do not block Deep Analysis / MoE / publish
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
