#!/usr/bin/env python3
"""Normalize Obsidian wikilinks against the actual vault files.

기능
----
1. 실제 Obsidian vault 파일을 기준으로 일반 wikilink를 정규화한다.
2. 경로/확장자/URL-encoded 변형을 실제 note stem으로 변환한다.
3. 구형 Record-번호--제목 형식 링크를 현재의
   Record <hash> · 제목 형식 note로 자동 마이그레이션한다.
4. 현재 존재하는 stable Record note를 기준으로 legacy Record 링크를
   제목 기반으로 정확하게 매핑한다.
5. 애매한 링크는 기존 방식대로 exact → partial → longest 순서로 처리한다.
6. 실제로 해결할 수 없는 링크는 경고만 출력하며 기본적으로 pipeline을
   실패시키지 않는다. --strict 사용 시 unresolved가 있으면 종료 코드 1.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote


WIKILINK = re.compile(
    r"\[\[([^\]|#]+)(#[^\]|]+)?(\|[^\]]+)?\]\]"
)

# 구형 Record 파일명
# 예:
# Record-1199--상품명
# Record-1230--some-title.md
LEGACY_RECORD = re.compile(
    r"^record[-_](\d+)[-_]{2}(.+)$",
    re.IGNORECASE,
)

# 현재 stable Record 파일명
# 예:
# Record a1b2c3d4e5 · 상품명
STABLE_RECORD = re.compile(
    r"^record\s+[0-9a-f]{10}\s+[·•]\s*(.+)$",
    re.IGNORECASE,
)


def normalize_unicode(value: str) -> str:
    """문자열 Unicode 형태를 NFC로 통일한다."""
    return unicodedata.normalize("NFC", value)


def key(value: str) -> str:
    """경로/확장자/URL 인코딩 차이를 제거한 비교용 key."""
    value = normalize_unicode(unquote(value.strip()))
    value = value.replace("\\", "/")
    value = value.removeprefix("./").lstrip("/")

    if value.lower().endswith(".md"):
        value = value[:-3]

    return value.casefold().strip()


def title_key(value: str) -> str:
    """Record 제목 비교용 key."""
    value = normalize_unicode(unquote(value.strip()))
    value = value.replace("\\", "/")

    # 경로가 들어온 경우 마지막 부분만 사용
    value = value.split("/")[-1]

    if value.lower().endswith(".md"):
        value = value[:-3]

    value = value.strip()

    return value.casefold()


def note_maps(
    vault: Path,
) -> tuple[dict[str, set[str]], dict[str, Path]]:
    """실제 vault note 기준 alias map을 만든다."""
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

        # 깊은 폴더에 있는 note도 basename으로 찾을 수 있게 한다.
        parts = Path(rel).parts
        if len(parts) >= 2:
            variants.add(key(parts[-1]))
            variants.add(key(Path(parts[-1]).stem))

        for variant in variants:
            if variant:
                aliases.setdefault(variant, set()).add(stem)

    return aliases, paths


def build_record_migration_map(
    vault: Path,
    paths: dict[str, Path],
) -> dict[str, str]:
    """구형 Record-번호--제목 링크를 stable Record note로 매핑한다.

    예:
        Record-1199--some-product
            ↓
        Record a1b2c3d4e5 · some-product

    현재 vault 안에 실제 stable Record note가 존재하는 경우에만 매핑한다.
    제목이 완전히 동일한 경우만 연결하여 잘못된 링크 선택을 최대한 방지한다.
    """
    migration: dict[str, str] = {}

    # stable title -> 실제 stable stem
    stable_by_title: dict[str, set[str]] = {}

    for stem, path in paths.items():
        if not path.exists():
            continue

        match = STABLE_RECORD.match(stem)
        if not match:
            continue

        stable_title = match.group(1).strip()
        stable_key = title_key(stable_title)

        if not stable_key:
            continue

        stable_by_title.setdefault(stable_key, set()).add(stem)

    # 현재 vault 안의 구형 Record 파일을 기준으로
    # "번호 제거 + 제목"을 stable Record에 연결한다.
    for stem in paths:
        match = LEGACY_RECORD.match(stem)
        if not match:
            continue

        legacy_title = match.group(2).strip()
        legacy_title_key = title_key(legacy_title)

        if not legacy_title_key:
            continue

        candidates = stable_by_title.get(legacy_title_key, set())

        # 하나만 존재하는 경우에만 안전하게 migration
        if len(candidates) == 1:
            migration[key(stem)] = next(iter(candidates))

    return migration


def legacy_record_target(
    target: str,
    record_migration: dict[str, str],
) -> str | None:
    """구형 Record 링크를 stable Record로 변환할 후보를 반환한다."""
    normalized = key(target)

    direct = record_migration.get(normalized)
    if direct:
        return direct

    # 경로가 붙은 legacy Record 링크
    base = key(
        Path(target.replace("\\", "/")).name
    )

    direct = record_migration.get(base)
    if direct:
        return direct

    return None


def pick_candidate(
    target: str,
    candidates: set[str],
) -> str | None:
    """후보 note 중 가장 적절한 하나를 선택한다."""
    if not candidates:
        return None

    if len(candidates) == 1:
        return next(iter(candidates))

    t = key(target)

    # 1) exact stem
    exact = [
        candidate
        for candidate in candidates
        if key(candidate) == t
    ]

    if len(exact) == 1:
        return exact[0]

    # 2) 부분 일치
    partial = [
        candidate
        for candidate in candidates
        if (
            key(candidate) == t
            or key(candidate).endswith(t)
            or t.endswith(key(candidate))
        )
    ]

    if len(partial) == 1:
        return partial[0]

    if partial:
        # 가장 긴 stem을 full note로 우선한다.
        return sorted(
            partial,
            key=lambda value: (-len(value), value),
        )[0]

    # 3) 기존 stable fallback
    return sorted(
        candidates,
        key=lambda value: (-len(value), value),
    )[0]


def normalize_vault(
    vault: Path,
) -> tuple[int, int, list[str]]:
    """전체 vault의 wikilink를 정규화한다."""
    aliases, paths = note_maps(vault)

    # 구형 Record-번호--제목 → stable Record 해시 제목
    record_migration = build_record_migration_map(
        vault,
        paths,
    )

    changed = 0
    problems: list[str] = []

    if record_migration:
        print(
            "legacy Record migration candidates: "
            f"{len(record_migration)}"
        )
    else:
        print("legacy Record migration candidates: 0")

    for note in sorted(vault.rglob("*.md")):
        original = note.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        def replace(match: re.Match[str]) -> str:
            target = match.group(1)
            heading = match.group(2) or ""
            alias = match.group(3) or ""

            # ---------------------------------------------------------
            # 1. 구형 Record 링크를 가장 먼저 처리
            # ---------------------------------------------------------
            migrated = legacy_record_target(
                target,
                record_migration,
            )

            if migrated is not None:
                current_target = f"[[{migrated}{heading}{alias}]]"

                problems.append(
                    "legacy-record-migrated: "
                    f"{note.relative_to(vault)} -> "
                    f"{target} => {migrated}"
                )

                return current_target

            # ---------------------------------------------------------
            # 2. 일반 alias 기반 탐색
            # ---------------------------------------------------------
            candidates = aliases.get(
                key(target),
                set(),
            )

            # ---------------------------------------------------------
            # 3. target basename 기반 재탐색
            # ---------------------------------------------------------
            if not candidates:
                base = key(
                    Path(
                        target.replace("\\", "/")
                    ).name
                )

                candidates = aliases.get(
                    base,
                    set(),
                )

            chosen = pick_candidate(
                target,
                candidates,
            )

            # ---------------------------------------------------------
            # 4. 실제로 찾을 수 없는 link
            # ---------------------------------------------------------
            if chosen is None:
                problems.append(
                    "unresolved: "
                    f"{note.relative_to(vault)} -> {target}"
                )

                return match.group(0)

            # ---------------------------------------------------------
            # 5. ambiguous resolution 기록
            # ---------------------------------------------------------
            if (
                len(candidates) > 1
                and key(chosen) != key(target)
            ):
                problems.append(
                    "ambiguous-resolved: "
                    f"{note.relative_to(vault)} -> "
                    f"{target} => {chosen}"
                )

            return f"[[{chosen}{heading}{alias}]]"

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
        problem
        for problem in problems
        if problem.startswith("unresolved:")
    ]

    return (
        changed,
        len(unresolved_only),
        problems,
    )


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--vault",
        default="obsidian/JARVIS_LUNA",
        type=Path,
        help="Obsidian vault path",
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "exit 1 if any unresolved link remains "
            "(old behavior)"
        ),
    )

    parser.add_argument(
        "--allow-unresolved",
        action="store_true",
        help=(
            "deprecated alias: "
            "same as default non-strict mode"
        ),
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
    ) = normalize_vault(args.vault)

    legacy_migrated = sum(
        1
        for problem in problems
        if problem.startswith(
            "legacy-record-migrated:"
        )
    )

    ambiguous_count = sum(
        1
        for problem in problems
        if problem.startswith(
            "ambiguous-resolved:"
        )
    )

    print(
        f"normalized files: {files_changed}"
    )
    print(
        f"legacy Record links migrated: "
        f"{legacy_migrated}"
    )
    print(
        f"ambiguous links resolved: "
        f"{ambiguous_count}"
    )
    print(
        f"unresolved links: "
        f"{unresolved_count}"
    )
    print(
        "notes (legacy-migrated + "
        "ambiguous-resolved + unresolved): "
        f"{len(problems)}"
    )

    for item in problems[:200]:
        print(item)

    # strict 모드에서만 실제 실패 처리
    if unresolved_count and args.strict:
        return 1

    # 기본값은 경고만 하고 Deep Analysis를 막지 않는다.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
