#!/usr/bin/env python3
"""Normalize Obsidian wikilinks against the actual vault files.

기능
----
1. 실제 Obsidian vault 파일을 기준으로 일반 wikilink를 정규화한다.
2. 경로/확장자/URL-encoded 변형을 실제 note stem으로 변환한다.
3. 구형 Record-번호--제목 형식 링크를 stable Record 로 마이그레이션한다.
4. training_corpus.jsonl 을 기준으로 stable 이름을 계산한다.
   (expand_obsidian_graph.record_key 와 동일 규칙: SHA-256(url|title)[:10])
5. 실제 파일 stem 은 slug(record_key) 형태다.
   예: Record a1b2c3d4e5 · Some-Title  →  Record-a1b2c3d4e5-Some-Title
6. 애매한 링크는 exact → partial → longest 순서로 처리한다.
7. 해결 불가 링크는 경고만 출력한다. --strict 시 unresolved 있으면 exit 1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "knowledge" / "training_corpus.jsonl"
RAW = ROOT / "data" / "knowledge" / "real_sources.json"

WIKILINK = re.compile(
    r"\[\[([^\]|#]+)(#[^\]|]+)?(\|[^\]]+)?\]\]"
)

LEGACY_RECORD = re.compile(
    r"^record[-_](\d+)[-_]{1,2}(.+)$",
    re.IGNORECASE,
)

STABLE_DISPLAY = re.compile(
    r"^record\s+([0-9a-f]{10})\s+[·•]\s*(.+)$",
    re.IGNORECASE,
)

STABLE_SLUG = re.compile(
    r"^record[-_]([0-9a-f]{10})[-_](.+)$",
    re.IGNORECASE,
)

SLUG_RE = re.compile(r"[^\w가-힣 -]+", re.UNICODE)
NAME_MAX_BYTES = 180


def normalize_unicode(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def slug(text: str, fallback: str = "Node") -> str:
    text = normalize_unicode(text)
    clean = SLUG_RE.sub("", text).strip().replace(" ", "-")[:70]
    while len(clean.encode("utf-8")) > NAME_MAX_BYTES and clean:
        clean = clean[:-1]
    return clean or fallback


def record_key(row: dict) -> str:
    url = str(row.get("url") or "").strip()
    title = normalize_unicode(str(row.get("title") or "Untitled").strip())
    h = hashlib.sha256((url or title).encode("utf-8")).hexdigest()[:10]
    return f"Record {h} · {slug(title, 'Record')}"


def record_stem(row: dict) -> str:
    return slug(record_key(row))


def key(value: str) -> str:
    value = normalize_unicode(unquote(value.strip()))
    value = value.replace("\\", "/")
    value = value.removeprefix("./").lstrip("/")
    if value.lower().endswith(".md"):
        value = value[:-3]
    return value.casefold().strip()


def title_key(value: str) -> str:
    value = normalize_unicode(unquote(value.strip()))
    value = value.replace("\\", "/")
    value = value.split("/")[-1]
    if value.lower().endswith(".md"):
        value = value[:-3]
    m = STABLE_DISPLAY.match(value) or STABLE_SLUG.match(value)
    if m:
        value = m.group(2)
    m2 = LEGACY_RECORD.match(value)
    if m2:
        value = m2.group(2)
    value = value.replace("-", " ").replace("_", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value.casefold()


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
        parts = Path(rel).parts
        if len(parts) >= 2:
            variants.add(key(parts[-1]))
            variants.add(key(Path(parts[-1]).stem))
        for variant in variants:
            if variant:
                aliases.setdefault(variant, set()).add(stem)
    return aliases, paths


def load_corpus_rows() -> list[dict]:
    rows: list[dict] = []
    if CORPUS.exists():
        for line in CORPUS.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if rows:
        return rows
    if RAW.exists():
        try:
            raw = json.loads(RAW.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return []
        for source_name, source in (raw.get("sources") or {}).items():
            for item in source.get("items") or []:
                rows.append({
                    "title": item.get("title") or item.get("product") or "Untitled",
                    "text": item.get("text") or item.get("summary") or "",
                    "url": item.get("url") or "",
                    "source": item.get("source") or source_name,
                })
    return rows


def build_record_migration_map(
    vault: Path,
    paths: dict[str, Path],
) -> dict[str, str]:
    migration: dict[str, str] = {}
    stems_on_disk = set(paths.keys())
    stems_cf = {s.casefold(): s for s in stems_on_disk}

    by_title: dict[str, set[str]] = {}
    for stem in stems_on_disk:
        tk = title_key(stem)
        if tk:
            by_title.setdefault(tk, set()).add(stem)

    rows = load_corpus_rows()
    corpus_stems = 0
    for row in rows:
        stem = record_stem(row)
        display = record_key(row)
        real = stems_cf.get(stem.casefold())
        if not real:
            continue
        corpus_stems += 1
        for variant in (stem, display):
            migration[key(variant)] = real
        tk = title_key(row.get("title") or "")
        if tk and len(by_title.get(tk, set())) == 1:
            migration[key(str(row.get("title") or ""))] = real

    for stem in stems_on_disk:
        m = LEGACY_RECORD.match(stem)
        if not m:
            continue
        legacy_title = m.group(2).strip()
        tk = title_key(legacy_title)
        candidates = {c for c in by_title.get(tk, set()) if not LEGACY_RECORD.match(c)}
        if len(candidates) == 1:
            migration[key(stem)] = next(iter(candidates))

    for stem in stems_on_disk:
        m = STABLE_SLUG.match(stem)
        if not m:
            continue
        hx, title = m.group(1), m.group(2)
        display = f"Record {hx} · {title.replace('-', ' ')}"
        migration[key(display)] = stem
        migration.setdefault(key(f"Record {hx}"), stem)
        migration.setdefault(key(f"Record-{hx}"), stem)

    print(
        f"corpus rows: {len(rows)} · "
        f"stable stems on disk matched: {corpus_stems} · "
        f"migration keys: {len(migration)}"
    )
    return migration


def legacy_record_target(
    target: str,
    record_migration: dict[str, str],
) -> str | None:
    normalized = key(target)
    direct = record_migration.get(normalized)
    if direct:
        return direct
    base = key(Path(target.replace("\\", "/")).name)
    direct = record_migration.get(base)
    if direct:
        return direct
    raw = unquote(target.strip())
    if raw.lower().endswith(".md"):
        raw = raw[:-3]
    m = LEGACY_RECORD.match(Path(raw.replace("\\", "/")).name)
    if m:
        tk = title_key(m.group(2))
        for k, v in record_migration.items():
            if title_key(k) == tk:
                return v
    return None


def pick_candidate(target: str, candidates: set[str]) -> str | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return next(iter(candidates))
    t = key(target)
    exact = [c for c in candidates if key(c) == t]
    if len(exact) == 1:
        return exact[0]
    partial = [
        c for c in candidates
        if key(c) == t or key(c).endswith(t) or t.endswith(key(c))
    ]
    if len(partial) == 1:
        return partial[0]
    if partial:
        return sorted(partial, key=lambda v: (-len(v), v))[0]
    return sorted(candidates, key=lambda v: (-len(v), v))[0]


def normalize_vault(vault: Path) -> tuple[int, int, list[str]]:
    aliases, paths = note_maps(vault)
    record_migration = build_record_migration_map(vault, paths)
    changed = 0
    problems: list[str] = []
    print(
        f"legacy Record migration candidates: {len(record_migration)}"
        if record_migration else "legacy Record migration candidates: 0"
    )

    for note in sorted(vault.rglob("*.md")):
        original = note.read_text(encoding="utf-8", errors="ignore")

        def replace(match: re.Match[str]) -> str:
            target = match.group(1)
            heading = match.group(2) or ""
            alias = match.group(3) or ""
            migrated = legacy_record_target(target, record_migration)
            if migrated is not None and key(migrated) != key(target):
                problems.append(
                    f"legacy-record-migrated: {note.relative_to(vault)} -> "
                    f"{target} => {migrated}"
                )
                return f"[[{migrated}{heading}{alias}]]"
            if migrated is not None:
                return f"[[{migrated}{heading}{alias}]]"
            candidates = aliases.get(key(target), set())
            if not candidates:
                base = key(Path(target.replace("\\", "/")).name)
                candidates = aliases.get(base, set())
            chosen = pick_candidate(target, candidates)
            if chosen is None:
                problems.append(
                    f"unresolved: {note.relative_to(vault)} -> {target}"
                )
                return match.group(0)
            if key(chosen) != key(target):
                problems.append(
                    f"ambiguous-resolved: {note.relative_to(vault)} -> "
                    f"{target} => {chosen}"
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
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--allow-unresolved", action="store_true")
    args = parser.parse_args()
    if not args.vault.exists():
        print(f"vault not found: {args.vault}", file=sys.stderr)
        return 2
    files_changed, unresolved_count, problems = normalize_vault(args.vault)
    legacy_migrated = sum(1 for p in problems if p.startswith("legacy-record-migrated:"))
    ambiguous_count = sum(1 for p in problems if p.startswith("ambiguous-resolved:"))
    print(f"normalized files: {files_changed}")
    print(f"legacy Record links migrated: {legacy_migrated}")
    print(f"ambiguous links resolved: {ambiguous_count}")
    print(f"unresolved links: {unresolved_count}")
    print(f"notes (legacy-migrated + ambiguous-resolved + unresolved): {len(problems)}")
    for item in problems[:200]:
        print(item)
    if unresolved_count and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
