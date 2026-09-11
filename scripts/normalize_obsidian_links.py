#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Normalize Obsidian wikilinks against the actual vault and real corpus.

핵심 목적
---------
1. 실제 Obsidian vault 파일을 기준으로 일반 wikilink를 정규화한다.
2. 경로/확장자/URL-encoded 변형을 실제 note stem으로 변환한다.
3. 구형 Record-번호--제목 링크를 stable Record 링크로 마이그레이션한다.
4. stable Record 파일이 아직 디스크에 없더라도
   training_corpus.jsonl을 기준으로 stable 이름을 계산해서 링크를 먼저 복구한다.
5. stable 이름 규칙은 expand_obsidian_graph와 동일하게 유지한다.

중요
----
현재 workflow 순서는

    Normalize
      ↓
    Rebuild Graph

이다.

따라서 Normalize 시점에 stable Record note가 아직 생성되지 않았을 수 있다.
이 파일은 그 상황에서도 training_corpus.jsonl에서 stable 이름을 계산하여
링크를 먼저 stable 이름으로 바꿀 수 있도록 설계한다.

자동 수정 범위
--------------
- obsidian/**/*.md 내부 wikilink
- 링크 target만 수정
- heading/alias(# / |)는 유지

수정하지 않는 것
----------------
- 원본 데이터
- training_corpus.jsonl
- real_sources.json
- 상품 가격
- 상품 점수
- Python/YAML 코드
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]

CORPUS = ROOT / "data" / "knowledge" / "training_corpus.jsonl"
RAW = ROOT / "data" / "knowledge" / "real_sources.json"


WIKILINK = re.compile(
    r"\[\[([^\]|#]+)(#[^\]|]+)?(\|[^\]]+)?\]\]"
)


LEGACY_RECORD = re.compile(
    r"^record[-_\s]+(\d+)[-_]{1,2}(.+)$",
    re.IGNORECASE,
)


STABLE_DISPLAY = re.compile(
    r"^record\s+([0-9a-f]{10})\s+[·•]\s*(.+)$",
    re.IGNORECASE,
)


STABLE_SLUG = re.compile(
    r"^record[-_\s]([0-9a-f]{10})[-_](.+)$",
    re.IGNORECASE,
)


HASH_ONLY = re.compile(
    r"^record[-_\s]?([0-9a-f]{10})$",
    re.IGNORECASE,
)


SLUG_RE = re.compile(
    r"[^\w가-힣 -]+",
    re.UNICODE,
)


LOOSE_TITLE_RE = re.compile(
    r"[^\w가-힣]+",
    re.UNICODE,
)


NAME_MAX_BYTES = 180


# ----------------------------------------------------------------------
# 기본 문자열 정규화
# ----------------------------------------------------------------------

def normalize_unicode(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def slug(text: str, fallback: str = "Node") -> str:
    text = normalize_unicode(text)

    clean = SLUG_RE.sub("", text)
    clean = clean.strip().replace(" ", "-")

    clean = clean[:70]

    while len(clean.encode("utf-8")) > NAME_MAX_BYTES and clean:
        clean = clean[:-1]

    return clean or fallback


def record_key(row: dict) -> str:
    """
    expand_obsidian_graph와 동일한 stable key 규칙.

    SHA-256(url|title가 아니라 실제 구현은
    url이 있으면 url, 없으면 title)
    """

    url = str(row.get("url") or "").strip()

    title = normalize_unicode(
        str(row.get("title") or "Untitled").strip()
    )

    seed = url or title

    digest = hashlib.sha256(
        seed.encode("utf-8")
    ).hexdigest()[:10]

    return f"Record {digest} · {slug(title, 'Record')}"


def record_stem(row: dict) -> str:
    return slug(record_key(row))


# ----------------------------------------------------------------------
# 링크/제목 비교용 key
# ----------------------------------------------------------------------

def key(value: str) -> str:
    """
    일반적인 경로 비교용 key.
    """

    value = normalize_unicode(
        unquote(str(value).strip())
    )

    value = value.replace("\\", "/")

    value = value.removeprefix("./")
    value = value.lstrip("/")

    if value.lower().endswith(".md"):
        value = value[:-3]

    return value.casefold().strip()


def loose_title_key(value: str) -> str:
    """
    제목 비교를 강하게 정규화한다.

    예:
      Some-Title
      Some_Title
      Some Title
      Some.Title

    등을 같은 제목으로 볼 수 있게 한다.

    단, 실제 매칭은 unique candidate일 때만 적용한다.
    """

    value = normalize_unicode(
        unquote(str(value).strip())
    )

    value = value.replace("\\", "/")
    value = value.split("/")[-1]

    if value.lower().endswith(".md"):
        value = value[:-3]

    # stable Record 표시형식 제거
    m = STABLE_DISPLAY.match(value)

    if m:
        value = m.group(2)

    # stable Record slug 제거
    m = STABLE_SLUG.match(value)

    if m:
        value = m.group(2)

    # hash only
    m = HASH_ONLY.match(value)

    if m:
        return f"record {m.group(1).casefold()}"

    # legacy numeric Record
    m = LEGACY_RECORD.match(value)

    if m:
        value = m.group(2)

    value = value.replace("-", " ")
    value = value.replace("_", " ")

    value = LOOSE_TITLE_RE.sub(" ", value)

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    return value.casefold()


def title_key(value: str) -> str:
    return loose_title_key(value)


# ----------------------------------------------------------------------
# Vault 검사
# ----------------------------------------------------------------------

def note_maps(
    vault: Path,
) -> tuple[dict[str, set[str]], dict[str, Path]]:
    aliases: dict[str, set[str]] = {}
    paths: dict[str, Path] = {}

    for note in sorted(vault.rglob("*.md")):
        rel = note.relative_to(vault).as_posix()
        stem = note.stem

        paths[stem] = note

        variants = {
            key(rel),
            key(rel[:-3]) if rel.lower().endswith(".md") else key(rel),
            key(stem),
            title_key(stem),
        }

        parts = Path(rel).parts

        if len(parts) >= 2:
            variants.add(
                key(parts[-1])
            )

            variants.add(
                key(Path(parts[-1]).stem)
            )

        for variant in variants:
            if variant:
                aliases.setdefault(
                    variant,
                    set(),
                ).add(stem)

    return aliases, paths


# ----------------------------------------------------------------------
# Corpus
# ----------------------------------------------------------------------

def load_corpus_rows() -> list[dict]:
    rows: list[dict] = []

    if CORPUS.exists():
        text = CORPUS.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        for line in text.splitlines():
            if not line.strip():
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(row, dict):
                rows.append(row)

    if rows:
        return rows

    if RAW.exists():
        try:
            raw = json.loads(
                RAW.read_text(
                    encoding="utf-8-sig"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return []

        sources = raw.get("sources") or {}

        for source_name, source in sources.items():
            for item in source.get("items") or []:

                if not isinstance(item, dict):
                    continue

                rows.append(
                    {
                        "title": (
                            item.get("title")
                            or item.get("product")
                            or "Untitled"
                        ),
                        "text": (
                            item.get("text")
                            or item.get("summary")
                            or ""
                        ),
                        "url": item.get("url") or "",
                        "source": (
                            item.get("source")
                            or source_name
                        ),
                    }
                )

    return rows


# ----------------------------------------------------------------------
# Corpus 기반 stable map
# ----------------------------------------------------------------------

def build_corpus_maps(
    rows: list[dict],
) -> tuple[
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, str],
]:
    """
    반환값

    title_to_stable:
        제목 -> stable stem 집합

    hash_to_stable:
        hash -> stable stem 집합

    stable_to_stable:
        stable variant -> stable stem
    """

    title_to_stable: dict[str, set[str]] = defaultdict(set)
    hash_to_stable: dict[str, set[str]] = defaultdict(set)
    stable_to_stable: dict[str, str] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        title = str(
            row.get("title")
            or "Untitled"
        ).strip()

        stable_stem = record_stem(row)

        stable_display = record_key(row)

        title_k = title_key(title)

        if title_k:
            title_to_stable[title_k].add(
                stable_stem
            )

        # stable hash 추출
        stable_match = re.search(
            r"Record\s+([0-9a-f]{10})",
            stable_display,
            re.IGNORECASE,
        )

        if stable_match:
            hx = stable_match.group(1).casefold()

            hash_to_stable[hx].add(
                stable_stem
            )

            stable_to_stable[
                key(stable_display)
            ] = stable_stem

            stable_to_stable[
                key(stable_stem)
            ] = stable_stem

            stable_to_stable[
                key(f"Record {hx}")
            ] = stable_stem

            stable_to_stable[
                key(f"Record-{hx}")
            ] = stable_stem

    return (
        dict(title_to_stable),
        dict(hash_to_stable),
        stable_to_stable,
    )


# ----------------------------------------------------------------------
# Legacy Record -> stable map
# ----------------------------------------------------------------------

def build_record_migration_map(
    vault: Path,
    paths: dict[str, Path],
) -> dict[str, str]:

    migration: dict[str, str] = {}

    stems_on_disk = set(
        paths.keys()
    )

    stems_cf = {
        s.casefold(): s
        for s in stems_on_disk
    }

    # --------------------------------------------------------------
    # 1. 실제 디스크 note 제목 map
    # --------------------------------------------------------------

    disk_by_title: dict[str, set[str]] = defaultdict(set)

    for stem in stems_on_disk:
        tk = title_key(stem)

        if tk:
            disk_by_title[tk].add(
                stem
            )

    # --------------------------------------------------------------
    # 2. 실제 training corpus
    #
    # 중요:
    # stable note가 아직 디스크에 없어도 map을 만든다.
    # --------------------------------------------------------------

    rows = load_corpus_rows()

    (
        corpus_by_title,
        corpus_by_hash,
        corpus_stable_map,
    ) = build_corpus_maps(rows)

    corpus_stems = 0
    corpus_title_mappings = 0
    corpus_hash_mappings = 0

    for row in rows:
        if not isinstance(row, dict):
            continue

        title = str(
            row.get("title")
            or "Untitled"
        ).strip()

        stable_stem = record_stem(row)
        stable_display = record_key(row)

        # ----------------------------------------------------------
        # stable 이름 자체
        # 파일이 아직 없어도 mapping에 넣는다.
        # ----------------------------------------------------------

        migration[
            key(stable_stem)
        ] = stable_stem

        migration[
            key(stable_display)
        ] = stable_stem

        # ----------------------------------------------------------
        # hash-only variant
        # ----------------------------------------------------------

        stable_match = re.search(
            r"Record\s+([0-9a-f]{10})",
            stable_display,
            re.IGNORECASE,
        )

        if stable_match:
            hx = stable_match.group(1)

            migration[
                key(f"Record {hx}")
            ] = stable_stem

            migration[
                key(f"Record-{hx}")
            ] = stable_stem

            migration[
                key(f"record_{hx}")
            ] = stable_stem

            corpus_hash_mappings += 1

        # ----------------------------------------------------------
        # title -> stable
        # 단일 제목일 때만 등록
        # ----------------------------------------------------------

        title_k = title_key(title)

        title_candidates = (
            corpus_by_title.get(title_k, set())
        )

        if len(title_candidates) == 1:
            migration[
                key(title)
            ] = stable_stem

            migration[
                title_k
            ] = stable_stem

            corpus_title_mappings += 1

        if (
            stable_stem.casefold()
            in stems_cf
        ):
            corpus_stems += 1

    # --------------------------------------------------------------
    # 3. 실제 디스크에 존재하는 stable/legacy note 기반 보강
    # --------------------------------------------------------------

    for stem in stems_on_disk:

        # stable slug 자체가 존재하는 경우
        m = STABLE_SLUG.match(stem)

        if m:
            hx = m.group(1).casefold()
            title = m.group(2)

            migration[
                key(stem)
            ] = stem

            migration.setdefault(
                key(f"Record {hx}"),
                stem,
            )

            migration.setdefault(
                key(f"Record-{hx}"),
                stem,
            )

            display = (
                f"Record {hx} · "
                f"{title.replace('-', ' ')}"
            )

            migration.setdefault(
                key(display),
                stem,
            )

            migration.setdefault(
                title_key(title),
                stem,
            )

            continue

        # ----------------------------------------------------------
        # 4. legacy Record-번호--제목
        # ----------------------------------------------------------

        legacy = LEGACY_RECORD.match(stem)

        if not legacy:
            continue

        legacy_title = legacy.group(2).strip()
        tk = title_key(legacy_title)

        # corpus에서 stable로 연결
        corpus_candidates = set(
            corpus_by_title.get(
                tk,
                set(),
            )
        )

        if len(corpus_candidates) == 1:
            target = next(
                iter(corpus_candidates)
            )

            migration[
                key(stem)
            ] = target

            migration[
                key(legacy_title)
            ] = target

            continue

        # corpus가 없거나 애매하면
        # 실제 디스크 stable note를 사용
        disk_candidates = {
            candidate
            for candidate in disk_by_title.get(
                tk,
                set(),
            )
            if not LEGACY_RECORD.match(candidate)
        }

        if len(disk_candidates) == 1:
            target = next(
                iter(disk_candidates)
            )

            migration[
                key(stem)
            ] = target

            migration[
                key(legacy_title)
            ] = target

    # --------------------------------------------------------------
    # 5. corpus stable map 병합
    # --------------------------------------------------------------

    for variant, stable in corpus_stable_map.items():
        migration.setdefault(
            variant,
            stable,
        )

    print(
        f"corpus rows: {len(rows)} · "
        f"stable stems on disk matched: {corpus_stems} · "
        f"corpus title mappings: {corpus_title_mappings} · "
        f"corpus hash mappings: {corpus_hash_mappings} · "
        f"migration keys: {len(migration)}"
    )

    return migration


# ----------------------------------------------------------------------
# legacy target resolution
# ----------------------------------------------------------------------

def legacy_record_target(
    target: str,
    record_migration: dict[str, str],
) -> str | None:

    normalized = key(target)

    # 1. exact
    direct = record_migration.get(
        normalized
    )

    if direct:
        return direct

    # 2. title-normalized
    tk = title_key(target)

    if tk:
        # exact title_key가 migration key로 있을 수 있다.
        direct = record_migration.get(tk)

        if direct:
            return direct

    # 3. basename
    base = key(
        Path(
            target.replace(
                "\\",
                "/",
            )
        ).name
    )

    direct = record_migration.get(base)

    if direct:
        return direct

    # 4. URL decode 후 legacy pattern
    raw = unquote(
        target.strip()
    )

    raw = raw.replace(
        "\\",
        "/",
    )

    raw_name = Path(raw).name

    if raw_name.lower().endswith(".md"):
        raw_name = raw_name[:-3]

    m = LEGACY_RECORD.match(
        raw_name
    )

    if m:
        legacy_title = m.group(2).strip()
        legacy_title_key = title_key(
            legacy_title
        )

        direct = record_migration.get(
            legacy_title_key
        )

        if direct:
            return direct

    return None


# ----------------------------------------------------------------------
# 일반 후보 선택
# ----------------------------------------------------------------------

def pick_candidate(
    target: str,
    candidates: set[str],
) -> str | None:

    if not candidates:
        return None

    if len(candidates) == 1:
        return next(
            iter(candidates)
        )

    target_key = key(target)
    target_title = title_key(target)

    # exact
    exact = [
        c
        for c in candidates
        if key(c) == target_key
    ]

    if len(exact) == 1:
        return exact[0]

    # title exact
    title_exact = [
        c
        for c in candidates
        if title_key(c) == target_title
    ]

    if len(title_exact) == 1:
        return title_exact[0]

    # suffix / prefix
    partial = [
        c
        for c in candidates
        if (
            key(c).endswith(target_key)
            or target_key.endswith(key(c))
        )
    ]

    if len(partial) == 1:
        return partial[0]

    # title partial
    title_partial = [
        c
        for c in candidates
        if (
            title_key(c) == target_title
            or title_key(c).endswith(target_title)
            or target_title.endswith(title_key(c))
        )
    ]

    if len(title_partial) == 1:
        return title_partial[0]

    # 여러 개면 기존처럼 가장 긴 것을
    # 무작정 선택하지 않는다.
    #
    # 잘못된 자동 연결보다 unresolved가 안전하다.
    return None


# ----------------------------------------------------------------------
# Vault 전체 정규화
# ----------------------------------------------------------------------

def normalize_vault(
    vault: Path,
) -> tuple[int, int, list[str]]:

    aliases, paths = note_maps(
        vault
    )

    record_migration = (
        build_record_migration_map(
            vault,
            paths,
        )
    )

    changed = 0
    problems: list[str] = []

    print(
        (
            "legacy Record migration candidates: "
            f"{len(record_migration)}"
        )
        if record_migration
        else
        "legacy Record migration candidates: 0"
    )

    all_notes = sorted(
        vault.rglob("*.md")
    )

    for note in all_notes:

        original = note.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        def replace(
            match: re.Match[str],
        ) -> str:

            target = match.group(1)
            heading = match.group(2) or ""
            alias = match.group(3) or ""

            # ------------------------------------------------------
            # A. Record migration
            # ------------------------------------------------------

            migrated = legacy_record_target(
                target,
                record_migration,
            )

            if migrated is not None:

                if key(migrated) != key(target):

                    problems.append(
                        "legacy-record-migrated: "
                        f"{note.relative_to(vault)} -> "
                        f"{target} => {migrated}"
                    )

                return (
                    f"[[{migrated}"
                    f"{heading}"
                    f"{alias}]]"
                )

            # ------------------------------------------------------
            # B. 실제 vault alias
            # ------------------------------------------------------

            candidates = aliases.get(
                key(target),
                set(),
            )

            if not candidates:
                base = key(
                    Path(
                        target.replace(
                            "\\",
                            "/",
                        )
                    ).name
                )

                candidates = aliases.get(
                    base,
                    set(),
                )

            # ------------------------------------------------------
            # C. title normalized fallback
            # ------------------------------------------------------

            if not candidates:
                target_title = title_key(
                    target
                )

                if target_title:
                    title_candidates = set()

                    for stem in paths:
                        if title_key(stem) == target_title:
                            title_candidates.add(
                                stem
                            )

                    candidates = title_candidates

            chosen = pick_candidate(
                target,
                candidates,
            )

            # ------------------------------------------------------
            # D. unresolved
            # ------------------------------------------------------

            if chosen is None:

                problems.append(
                    f"unresolved: "
                    f"{note.relative_to(vault)} -> "
                    f"{target}"
                )

                return match.group(0)

            # ------------------------------------------------------
            # E. 일반 normalization
            # ------------------------------------------------------

            if key(chosen) != key(target):

                problems.append(
                    "ambiguous-resolved: "
                    f"{note.relative_to(vault)} -> "
                    f"{target} => {chosen}"
                )

            return (
                f"[[{chosen}"
                f"{heading}"
                f"{alias}]]"
            )

        updated = WIKILINK.sub(
            replace,
            original,
        )

        if updated != original:

            note.write_text(
                updated,
                encoding="utf-8",
            )

            changed += 1

    unresolved_only = [
        p
        for p in problems
        if p.startswith(
            "unresolved:"
        )
    ]

    return (
        changed,
        len(unresolved_only),
        problems,
    )


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------

def main() -> int:

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--vault",
        default="obsidian/JARVIS_LUNA",
        type=Path,
    )

    parser.add_argument(
        "--strict",
        action="store_true",
    )

    parser.add_argument(
        "--allow-unresolved",
        action="store_true",
    )

    args = parser.parse_args()

    if not args.vault.exists():

        print(
            f"vault not found: {args.vault}",
            file=sys.stderr,
        )

        return 2

    (
        files_changed,
        unresolved_count,
        problems,
    ) = normalize_vault(
        args.vault
    )

    legacy_migrated = sum(
        1
        for p in problems
        if p.startswith(
            "legacy-record-migrated:"
        )
    )

    ambiguous_count = sum(
        1
        for p in problems
        if p.startswith(
            "ambiguous-resolved:"
        )
    )

    print(
        f"normalized files: {files_changed}"
    )

    print(
        "legacy Record links migrated: "
        f"{legacy_migrated}"
    )

    print(
        "ambiguous links resolved: "
        f"{ambiguous_count}"
    )

    print(
        f"unresolved links: {unresolved_count}"
    )

    print(
        "notes (legacy-migrated + "
        "ambiguous-resolved + unresolved): "
        f"{len(problems)}"
    )

    for item in problems[:300]:
        print(item)

    if (
        unresolved_count
        and args.strict
        and not args.allow_unresolved
    ):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
