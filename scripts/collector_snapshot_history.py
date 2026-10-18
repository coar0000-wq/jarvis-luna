#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rotating collector snapshots -> exact reason manifest entries (no guard waiver).

왜 필요한가 (2026-10-11)
  아마존 신상품·베스트셀러, SerpApi 시장가, 실지식 소스 목록은 매 실행마다 "지금 순위"로
  통째로 바뀐다. 순위에서 빠진 상품은 데이터 손실이 아니라 정상 교체다.
  그런데 발행 트랜잭션은 사라진 식별자(url/id 등)에 사유 기록을 요구한다. 사유 기록을
  만드는 장치가 없어서 이 수집기들은 10-09 이후 한 번도 발행하지 못했다.

무엇을 하나
  - 선언된 파일의 선언된 "순위 목록" 안에서만 사라진 식별자를 허용한다.
  - 그 밖(필드 삭제, 다른 목록의 식별자 삭제)은 그대로 막는다. 정책 파일은 건드리지 않는다.
  - 이전 스냅샷의 정확한 바이트는 git 커밋에 그대로 남아 있다. base_sha256 이 그 바이트를 가리킨다.
  - data/publish_deletions.json 에 path/base_sha256/replacement_sha256/ids/reason 을 적고,
    publish_transaction.deletion_authorized 로 실제 통과 여부를 확인한 뒤에만 쓴다.

사용: python scripts/collector_snapshot_history.py data/amazon_new_products.json [...]
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.publish_transaction import deletion_authorized, identity, removed_identities  # noqa: E402

MANIFEST = "data/publish_deletions.json"
POLICY = "config/publish_policy.json"
POLICY_REF = "scripts/collector_snapshot_history.py"

# 파일별로 "통째로 교체되는 순위 목록" 경로만 선언한다. * 는 한 단계 키.
ROTATING = {
    "data/amazon_products.json": ["products"],
    "data/amazon_new_products.json": ["products"],
    "data/amazon_movers_products.json": ["products"],
    "data/walmart_products.json": ["products"],
    "data/oliveyoung_us_products.json": ["products"],
    "data/sokoglam_products.json": ["products"],
    "data/us_beauty_products.json": ["products", "items", "by_store/*", "by_store/*/products", "by_store/*/items"],
    # 2026-10-18: 실패 사유 칸(reason)은 수집이 정상이 되면 빠진다(SerpApi 39076729843: trends/reason).
    "data/serpapi_market.json": ["prices/items", "prices/failures", "trends/items", "trends/failures",
                                 "prices/reason", "trends/reason"],
    # 2026-10-16: YouTube 검색 결과도 실행마다 통째로 바뀐다. 선언이 없어서 SerpApi 수집이 10-06 이후
    # 'identity/field removal requires reason manifest: data/youtube_serpapi.json' 으로 발행에 실패했고,
    # 그 사이 새로 S등급이 된 4개(1049275·1068721·1074979·1068733)는 상품별 미국 시장가를 한 번도 못 받았다.
    # 검색어 목록(queries)은 설정이라 그대로 지킨다.
    "data/youtube_serpapi.json": ["videos", "top_by_views"],
    "data/knowledge/real_sources.json": ["sources/*/items"],
    # 환율 관측은 통째로 새 값으로 바뀐다 (대조 목록·보조 필드 포함). 다른 칸은 그대로 지킨다.
    # 2026-10-16: last_run/last_attempt/last_candidate_success 의 candidate_ids 는 '이번 실행이 본 후보'
    # 목록이라 매 실행 통째로 바뀐다. 여기 선언이 없어서 Daiso Real Product Collection 이 수집을 다
    # 끝낸 뒤 이 단계에서 'identity removal outside rotating lists: .../last_run/candidate_ids' 로
    # 10-03 이후 매 실행 실패했다(소싱팀 overall_workflow 미복구의 원인).
    # recover_daiso_candidates.py 는 이미 같은 세 경로만 교체를 허용하고 있다. 후보 상품 자체의
    # 보존은 candidate_pool.json 쪽 가드가 계속 지킨다. 다른 칸은 그대로 막는다.
    # 2026-10-17: candidate_ids 만 풀었더니 다음 실행이 같은 단계에서 'field removal outside rotating lists:
    # .../last_run/skipped_excluded/선크림' 로 또 막혔다. last_* 는 실행 1회의 요약 보고서라 매 실행 통째로
    # 바뀐다(제외 사유별 개수·버킷 부족 목록·프리페치 정책). 요약 전체를 교체 단위로 선언하고, 빠진 키는
    # 매니페스트에 정확한 base/replacement 해시와 함께 남긴다. totals·visited·sitemap 은 그대로 막는다.
    "data/daiso_real/collection_status.json": ["fx", "last_run", "last_attempt", "last_success",
                                               "last_candidate_success"],
    # 파생 상태 보고서: 실행마다 실패 이력 창과 범위별 판정이 통째로 바뀐다.
    # 운영 보드: 매 실행 state.json 에서 통째로 다시 만드는 파생 화면(계획·작업·감시 목록). 원본 state 는 그대로 보존된다.
    "data/operations/board.json": ["action_cards", "audit", "audit/counts", "business", "business/blockers", "counts", "engines", "feedback", "source_procedures", "source_procedures/continuity", "source_procedures/plans", "source_recovery", "source_recovery/counters", "source_recovery/episodes", "tasks", "watchers"],
    # 운영 지식 그래프: 매 실행 state 에서 다시 만드는 파생 그래프(노드·엣지). 원본 state 는 보존된다.
    "data/operations/knowledge_graph.json": ["nodes", "edges"],
    # 운영 상태: 출처 복구 에피소드의 '현재 막힘 코드' 목록만. 출처가 회복되면 코드가 빠진다(이력·영수증은 그대로 보존).
    # 2026-10-17: 감시 기록의 latest_attempt 는 "지금 가장 최근 실행" 관측이라, 실행 중인 회차로 바뀌면
    # finished_at·conclusion 이 빠진다(Core 39039584239). last_success 등 다른 칸은 그대로 막는다.
    # 2026-10-18: watch/pending_events 는 처리 대기 큐라, 처리되면 빠진다(Core 39063638782). seen_events 는 그대로 막는다.
    "data/operations/state.json": ["source_recovery/episodes/*/blocker_codes",
                                   "watch/sources/*/records/*/value/latest_attempt", "watch/pending_events"],
    # AI 수집팀(예전 로보틱스): 논문·블로그·유튜브 최신 목록이 통째로 바뀐다. 2026-10-11 수집원 전환 포함.
    "data/robotics_sources.json": ["sources/*/items", "sources/*/source_results", "sources/*/errors"],
    # 전담팀 카테고리 목록(다이소몰 공개 목록): 실행마다 목록이 통째로 새 관측으로 바뀐다.
    # 2026-10-17: 디자인팀 오프라인 팩은 현재 S·리스팅 카피에서 매 실행 다시 만드는 파생 보고서다. 카피가 0건이 되자
    # seo/items 9->0 으로 Core 발행이 막혔다. 팩의 목록 칸만 교체 단위로 둔다(디자인 시스템 값은 그대로 막힘).
    "data/design/offline_pack.json": ["seo/items", "sections/home", "sections/home/*/products", "assets"],
    # 2026-10-17: Deep 수집기 스냅샷. 발행 가드가 생긴(10월 초) 뒤 Deep 이 한 번도 발행하지 못해 선언이 없었다.
    # 로컬에서 Deep 수집기를 실제로 돌려 HEAD 와 비교해 찾은, 실행마다 통째로 바뀌는 순위·피드 목록만 둔다.
    "data/design_sources.json": ["articles/items", "articles/errors", "articles/failed", "failed_blocks",
                                 "fonts/top_popular", "fonts/top_trending", "fonts/korean_fonts",
                                 "fonts/last_attempt", "colors/last_attempt", "articles/source_results/*/last_attempt"],
    "data/google_trends_beauty.json": ["items", "feed_summaries"],
    "data/institution_sources.json": ["items", "by_org", "sources/*/failures"],
    "data/kbeauty_news.json": ["items", "demo_hit_samples", "failed_queries", "bucket_mentions", "bucket_share_pct",
                               "demo_mentions"],
    "data/open_beauty_facts.json": ["products"],
    "data/public_signals.json": ["sources/*/items", "sources/*/errors"],
    "data/public_trend_rss.json": ["relevant_items", "feed_summaries", "feeds"],  # feeds 의 식별자는 URL(슬래시 포함)이라 목록 단위로 둔다
    "data/reddit_beauty_signals.json": ["posts", "per_subreddit", "hot_keywords", "beauty_keywords"],
    "data/youtube_channels.json": ["items", "top_by_views", "failed", "지난결과_유지", "제목_바뀐_영상"],
    # 같은 날 확인: 위 수집 결과에서 매번 다시 만드는 팀 피드·검토 큐·채널 후보(파생 목록).
    "data/team_feeds.json": ["teams/*"],
    "data/youtube_review_queue.json": ["videos"],
    "data/agents/channel_expansion.json": ["verified_candidates", "unverified_candidates"],
    "data/design_team.json": ["references/items", "reference_workflow_updated_at"],
    # 2026-10-18: S 목록이 바뀌면 시장팀 보드의 우선순위·키워드·경쟁·주간 액션도 통째로 다시 만들어진다
    # (Deep 39045168903/39058477196: s_grade_priority). 보드는 파생 화면이다.
    "data/market_team.json": ["demand_signals/*", "s_grade_priority", "keyword_board", "competitor_watch",
                              "weekly_actions", "marketing_playbook/*", "shopify_strategy/launch_order",
                              "health/live_channels"],
    "data/team_learning.json": ["teams/*/review_pending"],
    "data/youtube_manual.json": ["updated_at"],
    # 2026-10-18: Deep 의 팀 라우터(MoE) 재학습 보고서. 매 학습 결과로 통째로 바뀐다(Deep 39095190590).
    "data/knowledge/team_router_report.json": ["trusted_teams", "validation", "baseline_majority", "classes"],
    "data/knowledge/moe_tuning_report.json": ["search_space", "best", "mean_gate_load"],
    "data/knowledge/training_status.json": ["mean_gate_load"],
    "data/knowledge/organic_skincare_products.json": ["items", "sites"],
    "data/daiso_real/desk_catalog.json": ["desks/*", "desks/*/products", "desks/*/categories", "errors", "kept_previous"],
    # 2026-10-17: daiso_pipeline_inputs.py 가 보고서를 {history_path, validation_sha256, health:{...}} 형식으로
    # 쓰도록 바뀐 뒤(10-06 이후) Core 가 한 번도 발행하지 못해, 첫 발행에서 옛 평면 칸(status 등)이 빠진다.
    # 파생 보고서라 status 도 교체 단위로 둔다. schema_version·public_authority 삭제는 그대로 막힌다.
    "data/agents/daiso_pipeline_health.json": ["failed_workflow_history", "input_errors", "scopes", "operating_staleness",
                                               "metadata_precision", "status"],
}


def sha(raw: bytes | None) -> str | None:
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def head_bytes(root: Path, rel: str) -> bytes | None:
    p = subprocess.run(["git", "-C", str(root), "show", "HEAD:" + rel], capture_output=True)
    return p.stdout if p.returncode == 0 else None


def rotating(rel: str, where: tuple[str, ...]) -> bool:
    path = "/".join(where)
    return any(fnmatch.fnmatchcase(path, pat) and path.count("/") == pat.count("/") for pat in ROTATING.get(rel, []))


def allowed_removals(rel: str, old, new, policy: dict, where: tuple[str, ...] = ()) -> list[str]:
    """Identities removed only inside declared rotating lists; anything else raises."""
    contract = {"identity_fields": policy["identity_fields"]}
    if rotating(rel, where):
        if not isinstance(old, (list, dict)) and not isinstance(new, (list, dict)):
            return []  # 선언된 요약 값(예: status 문자열)은 새 값으로 바뀐다
        if not ((isinstance(old, list) and isinstance(new, list)) or (isinstance(old, dict) and isinstance(new, dict))):
            raise ValueError(f"rotating container type changed: {rel}/{'/'.join(where)}")
        return list(removed_identities(old, new, contract))
    if isinstance(old, dict):
        if not isinstance(new, dict):
            raise ValueError(f"container replaced: {rel}/{'/'.join(where)}")
        out = []
        for key, value in old.items():
            if key not in new:
                if rotating(rel, where + (key,)):
                    # 2026-10-17: 선언된 교체 목록이 비어서 칸째 빠지는 경우(daiso_pipeline_health 의
                    # failed_workflow_history). 발행 가드가 계산하는 식별자(칸 이름)를 그대로 기록한다.
                    out.append(str(key))
                    continue
                raise ValueError(f"field removal outside rotating lists: {rel}/{'/'.join(where + (key,))}")
            out.extend(allowed_removals(rel, value, new[key], policy, where + (key,)))
        return out
    if isinstance(old, list):
        if not isinstance(new, list):
            raise ValueError(f"list replaced: {rel}/{'/'.join(where)}")
        if removed_identities(old, new, contract):
            raise ValueError(f"identity removal outside rotating lists: {rel}/{'/'.join(where)}")
        field = identity(old + new, contract["identity_fields"])
        if field:
            rows = {str(r[field]): r for r in new}
            out = []
            for r in old:
                out.extend(allowed_removals(rel, r, rows[str(r[field])], policy, where + (str(r[field]),)))
            return out
    return []


def update(root: Path, paths: list[str]) -> dict:
    root = Path(root).absolute()
    policy = json.loads((root / POLICY).read_text(encoding="utf-8"))
    mpath = root / MANIFEST
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {"schema_version": 1, "deletions": []}
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("deletions"), list):
        raise ValueError("publish deletion manifest malformed")
    result = deepcopy(manifest)
    report = {}
    for rel in paths:
        if rel not in ROTATING:
            raise ValueError(f"not a declared rotating snapshot: {rel}")
        base = head_bytes(root, rel)
        local_path = root / rel
        result["deletions"] = [r for r in result["deletions"]
                               if not (r.get("path") == rel and r.get("policy_ref") == POLICY_REF)]
        if base is None or not local_path.exists():
            report[rel] = "no_base_or_local"
            continue
        local = local_path.read_bytes()
        if local == base:
            report[rel] = "unchanged"
            continue
        ids = sorted(set(str(x) for x in allowed_removals(rel, json.loads(base), json.loads(local), policy)))
        if not ids:
            report[rel] = "no_removals"
            continue
        # replacement_sha256 는 넣지 않는다. 발행 시 원격 최신과 합친 결과가 local 과 달라질 수 있어
        # (실지식 동기화 10-11 실패 원인) base 바이트와 사라진 식별자에만 묶는다.
        entry = {"path": rel, "base_sha256": sha(base), "ids": ids,
                 "reason": "Rotating ranking/search snapshot replaced by a newer capture; exact prior bytes remain in git at base_sha256.",
                 "policy_ref": POLICY_REF, "delete_file": False}
        result["deletions"].append(entry)
        if not deletion_authorized(rel, base, ids, result):
            raise ValueError(f"manifest entry does not satisfy removal contract: {rel}")
        report[rel] = f"authorized {len(ids)} rotated ids"
    if result != manifest:
        mpath.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


def main() -> int:
    paths = [p for p in sys.argv[1:] if p in ROTATING]
    if "--all-declared" in sys.argv[1:]:
        # 2026-10-17: Core 의 기존 팀 소스 복구는 어느 팀 파일이든 다시 수집할 수 있다(첫 정상 실행에서
        # robotics_sources.json 이 바뀌었는데 목록에 없어 발행이 막힘). 선언된 파일을 모두 본다.
        # 바뀌지 않은 파일은 그대로, 선언 밖 삭제는 여전히 막힌다.
        changed = [rel for rel in ROTATING if (ROOT / rel).exists()
                   and head_bytes(ROOT, rel) not in (None, (ROOT / rel).read_bytes())]
        paths = sorted(set(paths) | set(changed))
    try:
        report = update(ROOT, paths)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"COLLECTOR_SNAPSHOT_BLOCKED {exc}")
        return 1
    print("COLLECTOR_SNAPSHOT_OK " + json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
