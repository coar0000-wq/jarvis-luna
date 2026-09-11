#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
JARVIS Safe Auto-Fix Agent
==========================

목적
----
진단 → 우선순위 → 제한된 자동수정 → 결과 기록

안전 원칙
---------
1. 허용된 파일만 수정한다.
2. 코드(.py/.yml) 자동수정은 하지 않는다.
3. collection_status.json은 직접 수정하지 않는다.
4. 수집 실패 SKU는 조건이 맞을 때만 beauty_queue.json에 반영한다.
5. Obsidian 링크 정리는 기존 검증된 스크립트를 호출한다.
6. 모든 자동수정 결과는 data/agents/autofix_report.json에 남긴다.
7. 수정이 없어도 정상 종료한다.

허용 자동수정
-------------
A. Daiso 실패 SKU의 blacklist 동기화
   - reason에 "가격" 포함
   - og_title이 "다이소몰"/"Daiso"/빈값
   - sold_out이 false
   - 해당 pd_no를 blacklist에 추가
   - priority 목록에서 제거

B. Obsidian 링크 정규화
   - JARVIS_AUTOFIX_OBSIDIAN=1일 때만 실행
   - scripts/normalize_obsidian_links.py
   - 성공 후 graph rebuild 스크립트가 존재하면 실행 가능

C. Runtime은 필요할 때만 재생성
   - scripts/generate_dashboard_runtime.py가 존재하고
   - JARVIS_AUTOFIX_RUNTIME=1일 때만 실행

자동수정하지 않는 것
--------------------
- Python 코드 수정
- GitHub Actions YAML 수정
- Shopify Admin 등록
- 광고 집행
- 결제/법률/외부 계정 변경
- 강제 push
- collection_status.json 조작
- 임의의 상품 가격/재고 생성
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

AGENTS_DIR = ROOT / "data" / "agents"
DAISO_DIR = ROOT / "data" / "daiso_real"

COLLECTION_STATUS = DAISO_DIR / "collection_status.json"
BEAUTY_QUEUE = DAISO_DIR / "beauty_queue.json"
RUNTIME = ROOT / "data" / "dashboard_runtime.json"

NORMALIZE_SCRIPT = ROOT / "scripts" / "normalize_obsidian_links.py"
GRAPH_SCRIPT_CANDIDATES = [
    ROOT / "scripts" / "rebuild_obsidian_graph.py",
    ROOT / "scripts" / "rebuild_graph.py",
    ROOT / "scripts" / "rebuild_obsidian.py",
]

RUNTIME_SCRIPT = ROOT / "scripts" / "generate_dashboard_runtime.py"

REPORT = AGENTS_DIR / "autofix_report.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default if default is not None else {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] JSON load failed: {path} :: {exc}")
        return default if default is not None else {}


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")

    tmp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    tmp.replace(path)


def env_true(name: str, default: bool = False) -> bool:
    value = str(os.environ.get(name, "")).strip().lower()

    if value in {"1", "true", "yes", "y", "on"}:
        return True

    if value in {"0", "false", "no", "n", "off"}:
        return False

    return default


def ensure_list(value: Any) -> list:
    if isinstance(value, list):
        return value

    if value is None:
        return []

    return [value]


def normalize_pd_no(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def get_collection_last_run(collection_status: dict) -> dict:
    value = collection_status.get("last_run")

    if isinstance(value, dict):
        return value

    return {}


def extract_failed_products(collection_status: dict) -> list[dict]:
    """
    현재 collection_status에서 자동수정 대상으로 삼을
    parse_failed 샘플을 추출한다.
    """

    last_run = get_collection_last_run(collection_status)

    samples = last_run.get("parse_fail_samples")

    if not isinstance(samples, list):
        return []

    return [x for x in samples if isinstance(x, dict)]


def is_safe_daiso_blacklist_candidate(sample: dict) -> bool:
    """
    다음 조건을 모두 만족할 때만 자동 blacklist 대상.

    - pd_no 존재
    - 가격 관련 실패
    - og_title이 다이소몰 계열
    - sold_out이 아님
    """

    pd_no = normalize_pd_no(sample.get("pd_no"))

    if not pd_no:
        return False

    reason = str(sample.get("reason") or "").strip()

    if "가격" not in reason:
        return False

    og_title = str(sample.get("og_title") or "").strip()

    allowed_titles = {
        "",
        "다이소몰",
        "Daiso",
        "DAISO",
        "daiso",
    }

    if og_title not in allowed_titles:
        return False

    sold_out = sample.get("sold_out")

    if sold_out is True:
        return False

    return True


def get_blacklist(queue: dict) -> tuple[list[Any], str]:
    """
    기존 queue 구조를 최대한 보존한다.

    반환값:
      blacklist 리스트
      실제 사용된 필드명
    """

    if "blacklist_pd_nos" in queue:
        value = queue.get("blacklist_pd_nos")

        if isinstance(value, list):
            return value, "blacklist_pd_nos"

    if "blacklist" in queue:
        value = queue.get("blacklist")

        if isinstance(value, list):
            return value, "blacklist"

    queue["blacklist"] = []

    return queue["blacklist"], "blacklist"


def get_priority_pd_nos(queue: dict) -> tuple[list[Any] | None, str | None]:
    """
    priority/queue 구조를 보존하기 위해
    실제 존재하는 리스트 필드를 찾는다.
    """

    candidate_fields = [
        "priority_pd_nos",
        "priority",
        "pd_nos",
        "priority_products",
    ]

    for field in candidate_fields:
        value = queue.get(field)

        if isinstance(value, list):
            return value, field

    return None, None


def remove_pd_from_priority_list(
    queue: dict,
    pd_no: str,
) -> tuple[bool, str | None]:
    """
    우선순위 리스트에서 실패 SKU 제거.
    """

    priority_list, field = get_priority_pd_nos(queue)

    if priority_list is None or field is None:
        return False, None

    original = list(priority_list)

    filtered = []

    for value in priority_list:
        current = normalize_pd_no(value)

        if current == pd_no:
            continue

        filtered.append(value)

    changed = original != filtered

    if changed:
        queue[field] = filtered

    return changed, field


def maybe_remove_from_url_list(
    queue: dict,
    pd_no: str,
) -> tuple[bool, str | None]:
    """
    urls 리스트가 pd_no를 명확하게 포함하는 경우에만 제거한다.

    임의 URL은 제거하지 않는다.
    """

    urls = queue.get("urls")

    if not isinstance(urls, list):
        return False, None

    original = list(urls)
    filtered = []

    for value in urls:
        text = str(value)

        if pd_no in text:
            continue

        filtered.append(value)

    changed = original != filtered

    if changed:
        queue["urls"] = filtered

    return changed, "urls" if changed else None


def repair_daiso_queue(
    collection_status: dict,
    queue: dict,
) -> dict:
    """
    가격없음 + og_title only 실패 SKU를 blacklist에 자동 동기화.
    """

    report = {
        "action": "repair_daiso_queue",
        "started_at": now_iso(),
        "enabled": True,
        "changed": False,
        "added_to_blacklist": [],
        "already_blacklisted": [],
        "removed_from_priority": [],
        "removed_from_urls": [],
        "skipped": [],
        "reason": None,
    }

    samples = extract_failed_products(collection_status)

    candidates = [
        sample
        for sample in samples
        if is_safe_daiso_blacklist_candidate(sample)
    ]

    if not candidates:
        report["reason"] = "safe_blacklist_candidate=0"
        report["finished_at"] = now_iso()
        return report

    blacklist, blacklist_field = get_blacklist(queue)

    existing = {
        normalize_pd_no(value)
        for value in blacklist
        if normalize_pd_no(value)
    }

    for sample in candidates:
        pd_no = normalize_pd_no(sample.get("pd_no"))

        if not pd_no:
            continue

        if pd_no in existing:
            report["already_blacklisted"].append(pd_no)
        else:
            blacklist.append(pd_no)
            existing.add(pd_no)

            report["added_to_blacklist"].append(pd_no)
            report["changed"] = True

        priority_changed, priority_field = remove_pd_from_priority_list(
            queue,
            pd_no,
        )

        if priority_changed:
            report["removed_from_priority"].append(
                {
                    "pd_no": pd_no,
                    "field": priority_field,
                }
            )

            report["changed"] = True

        url_changed, url_field = maybe_remove_from_url_list(
            queue,
            pd_no,
        )

        if url_changed:
            report["removed_from_urls"].append(
                {
                    "pd_no": pd_no,
                    "field": url_field,
                }
            )

            report["changed"] = True

    queue[blacklist_field] = blacklist

    report["blacklist_field"] = blacklist_field
    report["candidate_count"] = len(candidates)
    report["finished_at"] = now_iso()

    return report


def run_command(
    command: list[str],
    label: str,
    timeout: int = 120,
) -> dict:
    """
    외부 스크립트 실행 결과를 구조화한다.
    """

    result = {
        "label": label,
        "command": command,
        "started_at": now_iso(),
        "returncode": None,
        "ok": False,
        "stdout": "",
        "stderr": "",
        "timed_out": False,
    }

    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

        result["returncode"] = completed.returncode
        result["stdout"] = (completed.stdout or "")[-8000:]
        result["stderr"] = (completed.stderr or "")[-8000:]
        result["ok"] = completed.returncode == 0

    except subprocess.TimeoutExpired as exc:
        result["timed_out"] = True
        result["stdout"] = str(getattr(exc, "stdout", "") or "")[-8000:]
        result["stderr"] = str(getattr(exc, "stderr", "") or "")[-8000:]

    except Exception as exc:
        result["stderr"] = str(exc)

    result["finished_at"] = now_iso()

    print(
        f"[{'OK' if result['ok'] else 'FAIL'}] "
        f"{label} "
        f"returncode={result['returncode']}"
    )

    return result


def run_obsidian_normalizer() -> dict:
    """
    기존 정규화 스크립트를 호출한다.
    """

    if not NORMALIZE_SCRIPT.exists():
        return {
            "label": "normalize_obsidian_links",
            "ok": False,
            "skipped": True,
            "reason": "script_not_found",
        }

    return run_command(
        [
            sys.executable,
            str(NORMALIZE_SCRIPT),
        ],
        label="normalize_obsidian_links",
        timeout=180,
    )


def find_graph_script() -> Path | None:
    for candidate in GRAPH_SCRIPT_CANDIDATES:
        if candidate.exists():
            return candidate

    return None


def run_graph_rebuild() -> dict:
    """
    존재하는 그래프 rebuild 스크립트만 실행한다.
    없으면 스킵.
    """

    script = find_graph_script()

    if script is None:
        return {
            "label": "graph_rebuild",
            "ok": True,
            "skipped": True,
            "reason": "graph_script_not_found",
        }

    return run_command(
        [
            sys.executable,
            str(script),
        ],
        label="graph_rebuild",
        timeout=180,
    )


def run_runtime_generation() -> dict:
    """
    dashboard_runtime 재생성.
    """

    if not RUNTIME_SCRIPT.exists():
        return {
            "label": "generate_dashboard_runtime",
            "ok": False,
            "skipped": True,
            "reason": "script_not_found",
        }

    return run_command(
        [
            sys.executable,
            str(RUNTIME_SCRIPT),
        ],
        label="generate_dashboard_runtime",
        timeout=180,
    )


def validate_queue_after_fix(queue: dict) -> dict:
    """
    자동수정 후 최소 구조 검증.
    """

    valid = isinstance(queue, dict)

    blacklist, blacklist_field = get_blacklist(queue)

    checks = {
        "queue_is_dict": valid,
        "blacklist_is_list": isinstance(blacklist, list),
        "blacklist_field": blacklist_field,
    }

    checks["ok"] = all(
        value
        for key, value in checks.items()
        if key.endswith("_is_list")
        or key == "queue_is_dict"
    )

    return checks


def build_summary(
    queue_report: dict,
    obsidian_report: dict | None,
    graph_report: dict | None,
    runtime_report: dict | None,
) -> dict:

    changed_files = []

    if queue_report.get("changed"):
        changed_files.append(str(BEAUTY_QUEUE.relative_to(ROOT)))

    if obsidian_report and obsidian_report.get("ok"):
        if not obsidian_report.get("skipped"):
            changed_files.append("obsidian/")

    if graph_report and graph_report.get("ok"):
        if not graph_report.get("skipped"):
            changed_files.append("obsidian/graph artifacts")

    if runtime_report and runtime_report.get("ok"):
        if not runtime_report.get("skipped"):
            changed_files.append("data/dashboard_runtime.json")

    return {
        "changed": bool(changed_files),
        "changed_files": changed_files,
        "safe_scope": [
            "data/daiso_real/beauty_queue.json",
            "obsidian/",
            "data/dashboard_runtime.json",
            "data/agents/",
        ],
        "never_modified": [
            "Python source code",
            "GitHub Actions YAML",
            "collection_status.json",
            "Shopify Admin",
            "ad accounts",
            "payment/legal/external accounts",
        ],
    }


def main() -> int:
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("JARVIS SAFE AUTO-FIX")
    print("=" * 72)

    collection_status = load_json(COLLECTION_STATUS, {})
    queue = load_json(BEAUTY_QUEUE, {})

    if not isinstance(collection_status, dict):
        collection_status = {}

    if not isinstance(queue, dict):
        queue = {}

    last_run = get_collection_last_run(collection_status)

    parse_failed = int(
        last_run.get("parse_failed") or 0
    )

    print(f"parse_failed={parse_failed}")

    autofix_force = env_true(
        "JARVIS_AUTOFIX_FORCE",
        default=False,
    )

    autofix_enabled = env_true(
        "JARVIS_AUTOFIX",
        default=True,
    )

    if not autofix_enabled:
        report = {
            "generated_at": now_iso(),
            "enabled": False,
            "ran": False,
            "trigger": "JARVIS_AUTOFIX disabled",
        }

        save_json(REPORT, report)

        print("SAFE AUTO-FIX disabled.")

        return 0

    trigger_reasons = []

    if autofix_force:
        trigger_reasons.append("force")

    if parse_failed >= 1:
        trigger_reasons.append(
            f"parse_failed={parse_failed}"
        )

    if not trigger_reasons:
        trigger_reasons.append("manual_or_workflow")

    queue_report = repair_daiso_queue(
        collection_status,
        queue,
    )

    if queue_report.get("changed"):
        save_json(
            BEAUTY_QUEUE,
            queue,
        )

        print(
            "[WRITE]",
            BEAUTY_QUEUE,
        )

    else:
        print(
            "[NO CHANGE]",
            BEAUTY_QUEUE,
        )

    queue_validation = validate_queue_after_fix(
        queue
    )

    if not queue_validation.get("ok"):
        print(
            "[ERROR] beauty_queue validation failed"
        )

        failure_report = {
            "generated_at": now_iso(),
            "status": "failed",
            "trigger": trigger_reasons,
            "queue": queue_report,
            "queue_validation": queue_validation,
        }

        save_json(
            REPORT,
            failure_report,
        )

        return 1

    obsidian_report = None
    graph_report = None
    runtime_report = None

    if env_true(
        "JARVIS_AUTOFIX_OBSIDIAN",
        default=False,
    ):
        print(
            "[RUN] Obsidian normalization"
        )

        obsidian_report = run_obsidian_normalizer()

        if obsidian_report.get("ok"):
            graph_report = run_graph_rebuild()

    if env_true(
        "JARVIS_AUTOFIX_RUNTIME",
        default=False,
    ):
        print(
            "[RUN] dashboard runtime regeneration"
        )

        runtime_report = run_runtime_generation()

    summary = build_summary(
        queue_report,
        obsidian_report,
        graph_report,
        runtime_report,
    )

    final_status = "success"

    if (
        obsidian_report
        and not obsidian_report.get("ok")
        and not obsidian_report.get("skipped")
    ):
        final_status = "warning"

    if (
        graph_report
        and not graph_report.get("ok")
        and not graph_report.get("skipped")
    ):
        final_status = "warning"

    if (
        runtime_report
        and not runtime_report.get("ok")
        and not runtime_report.get("skipped")
    ):
        final_status = "warning"

    report = {
        "agent": "Safe-Auto-Fix",
        "generated_at": now_iso(),
        "status": final_status,
        "enabled": True,
        "trigger": trigger_reasons,
        "parse_failed": parse_failed,
        "queue": queue_report,
        "queue_validation": queue_validation,
        "obsidian": obsidian_report,
        "graph_rebuild": graph_report,
        "runtime_generation": runtime_report,
        "summary": summary,
        "policy": {
            "allow_code_autofix": False,
            "allow_workflow_autofix": False,
            "allow_collection_status_edit": False,
            "allow_shopify_write": False,
            "allow_external_account_write": False,
            "allow_force_push": False,
            "allow_deterministic_data_repair": True,
        },
    }

    save_json(
        REPORT,
        report,
    )

    print("=" * 72)
    print(
        "SAFE AUTO-FIX RESULT:",
        final_status,
    )

    if queue_report.get("added_to_blacklist"):
        print(
            "Added blacklist:",
            queue_report["added_to_blacklist"],
        )

    if queue_report.get("already_blacklisted"):
        print(
            "Already blacklisted:",
            queue_report["already_blacklisted"],
        )

    if summary.get("changed_files"):
        print(
            "Changed:",
            summary["changed_files"],
        )
    else:
        print(
            "Changed: none"
        )

    print(
        "Report:",
        REPORT,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
