#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Records 를 팀 허브 아래로 묶는다.

왜
  Records 가 37,082개로 볼트 전체의 98.6% 다. Topics 28개와 Orgs 35개에
  비해 압도적이라 그래프뷰를 열면 허브 몇 개에 점 수만 개가 매달린 모습이
  된다. 지금도 열리기는 하지만 탐색이 안 되고, 노트가 더 쌓이면 렌더링도
  버거워진다.

  중간 층을 하나 넣는다. Record 가 Topic 에 바로 붙는 대신
  Record -> Topic -> 팀 순서로 붙게 한다. 그래프뷰를 팀 단위로 접어서
  볼 수 있고, "이 팀이 지금 뭘 보고 있나" 를 한 화면에서 읽을 수 있다.

무엇을 만드나
  Knowledge/Teams/ 아래 팀 노트 하나씩. 각 팀 노트가
    - 그 팀에 속한 Topic 을 링크로 걸고
    - 팀이 쓰는 수집원과 최근 산출물 수를 적는다
  Record 파일 3만 7천 개는 건드리지 않는다. Topic 노트에 팀 링크를 한 줄
  더하는 것으로 층이 생긴다. 파일을 3만 개 고쳐 쓰면 커밋이 터진다.

팀 배정 근거
  기존 Topic 이름을 팀에 매핑한다. 새로 분류하지 않는다.
  분류기를 또 만들면 기존 분류와 어긋나서 같은 자료가 두 곳에 들어간다.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "obsidian" / "JARVIS_LUNA"
TOPICS = VAULT / "Knowledge" / "Topics"
RECORDS = VAULT / "Knowledge" / "Records"
TEAMS = VAULT / "Knowledge" / "Teams"
DATA = ROOT / "data"
OUT = DATA / "team_hubs.json"

# Topic -> 팀. 기존 Topic 이름을 그대로 쓴다.
# 한 Topic 이 여러 팀에 걸릴 수 있다. 예를 들어 이커머스는 리스팅과
# 마케팅이 같이 본다. 그럴 때는 둘 다 건다.
TEAM_TOPICS = {
    "상품 소싱팀": ["뷰티스킨케어"],
    "마케팅 조사팀": ["뷰티스킨케어", "마케팅광고", "소셜콘텐츠", "이커머스Shopify",
                "Shopify-Commerce"],
    "리스팅 제작팀": ["이커머스Shopify", "Shopify-Commerce", "마케팅광고"],
    "가격 정책팀": ["물류통관", "경영전략"],
    "법률·규제팀": ["법률규제", "물류통관", "의료바이오"],
    "디자인팀": ["소셜콘텐츠", "마케팅광고"],
    "채널 운영팀": ["소셜콘텐츠", "데이터분석"],
    "지식 수집팀": ["AI-Research", "AI-Agents", "AI-에이전트", "LLM언어모델",
               "Machine-Learning-Research", "머신러닝-연구", "Model-Routing-and-MoE",
               "모델-라우팅MoE", "컴퓨터-비전", "AI-Image-Generation", "음성오디오",
               "데이터분석", "보안프라이버시", "인프라클라우드", "과학수학"],
    "기관 수집팀": ["투자은행금융", "반도체하드웨어", "경영전략"],
    "로보틱스 수집": ["로보틱스"],
}

TEAM_NOTE = """---
title: "팀 · {team}"
type: team-hub
status: generated
updated_at: {now}
tags: [team, hub]
---

# 팀 · {team}

> {role}

**담당 주제** {n_topics}개 · **이번 회차 수집분** {n_current:,}건

> 수집분은 이번 회차 코퍼스 기준입니다. 볼트의 Record 는 누적분이라
> 훨씬 많습니다. 둘은 다른 수입니다.

수집원별: {src_line}

## 이 팀이 보는 주제

{topic_links}

## 수집원

{sources}

## 산출물

{outputs}

[[JARVIS Real Knowledge Index]]
"""

TEAM_META = {
    "상품 소싱팀": ("다이소몰에서 실제 상품을 수집하고 미국 수요와 맞는지 점수를 매긴다.",
              ["다이소몰 상품 상세 (robots Crawl-delay 30 준수)"],
              ["data/daiso_real/shopify_demand_score.json",
               "data/daiso_real/shopify_s_recommendations.json"]),
    "마케팅 조사팀": ("미국에서 무엇이 팔리고 무엇이 화제인지 본다. 판매 신호와 매체 신호를 나눠 센다.",
               ["올리브영US·틱톡샵·세포라·울타·아마존·월마트", "Google News K-beauty",
                "SerpApi YouTube 검색"],
               ["data/market_team.json", "data/kbeauty_news.json"]),
    "리스팅 제작팀": ("영문 상품명과 상세를 만든다. 미국에서 못 쓰는 표현은 생성 단계에서 막는다.",
               ["Gemini (us_claim_rules.json 금지어 50개 주입)"],
               ["data/shopify_listing_copy.json", "data/listing_gate.json"]),
    "가격 정책팀": ("고시 용량과 우체국 요금표로 배송비를 계산해 단품·1+1 판매가를 낸다.",
              ["SerpApi Google Shopping (미국 시장가)", "우체국 국제우편 요금표"],
              ["data/pricing_model.json"]),
    "법률·규제팀": ("우리가 고른 상품을 미국에 팔아도 되는지 확인한다. 문제가 있으면 소싱 단계에서 막는다.",
              ["openFDA 화장품 이상사례·OTC 라벨", "FDA 리콜 RSS",
               "미국 국제무역위원회 HTS"],
              ["data/legal_products.json", "data/legal_export_prep.json"]),
    "디자인팀": ("브랜드 자산과 스토어 화면을 준비한다. 브랜드는 사람이 정한 것을 따른다.",
             ["Coar Family 사이트 (사용자 제작)", "Google Fonts", "Open Color",
              "@uxpeak 등 지정 채널"],
             ["data/brand_kit.json", "data/design_sources.json"]),
    "채널 운영팀": ("수집 채널이 살아 있는지 지키고 새 채널을 실측으로 검증한다.",
              ["Google Trends", "Wikipedia 조회수", "Open Beauty Facts", "Allure"],
              ["data/channel_candidates.json", "data/source_health.json"]),
    "지식 수집팀": ("AI·데이터 분야 논문과 기사를 모아 그래프에 넣는다.",
              ["arXiv", "Google News", "지정 YouTube 채널·영상"],
              ["data/knowledge/real_sources.json"]),
    "기관 수집팀": ("투자은행·반도체·AI연구소 35곳의 발표물과 논문을 모은다.",
              ["기관 RSS·사이트맵", "OpenAlex"],
              ["data/institution_sources.json"]),
    "로보틱스 수집": ("로봇 분야 논문과 매체를 모은다.",
               ["arXiv cs.RO·eess.SY", "IEEE Spectrum", "Robot Report"],
               ["data/robotics_sources.json"]),
}


def base_ref() -> str:
    """어느 커밋을 기준으로 셀지 고른다.

    처음에는 HEAD 로 셌더니 Records 가 30,436 으로 나왔다. 원격은 37,082 이었다.
    작업 사본이 원격보다 뒤처져 있었던 것이다. 디스크를 직접 세도 30,403 이라
    같은 이유로 틀린다. 원격을 알 수 있으면 원격이 기준이다.
    Actions 에서는 둘이 같은 커밋이라 어느 쪽을 골라도 결과가 같다.
    """
    for ref in ("origin/main", "HEAD"):
        r = subprocess.run(["git", "rev-parse", "--verify", "-q", ref + "^{commit}"],
                           capture_output=True, cwd=ROOT)
        if r.returncode == 0:
            return ref
    return "HEAD"


REF = base_ref()


def git_ls(path: str) -> list[str]:
    """커밋된 파일 목록. -z 로 받아야 한글 이름이 안 깨진다."""
    out = subprocess.run(["git", "ls-tree", "-r", "--name-only", "-z", REF, path],
                         capture_output=True, cwd=ROOT).stdout.decode("utf-8", "replace")
    return [x for x in out.split("\0") if x.endswith(".md")]


# 수집원 -> 팀. 코퍼스의 source 값을 그대로 쓴다.
SOURCE_TEAMS = {
    "institutions": ["기관 수집팀"],
    "arxiv": ["지식 수집팀"],
    "robotics": ["로보틱스 수집"],
    "google": ["지식 수집팀", "마케팅 조사팀"],
    "youtube": ["지식 수집팀", "디자인팀"],
    "us_beauty": ["마케팅 조사팀", "상품 소싱팀"],
}


def corpus_by_source() -> Counter:
    """현재 코퍼스를 수집원별로 센다.

    처음에는 Record 3만 7천 개를 훑어 Topic 별로 세려 했는데 끝나지 않았다.
    그럴 필요가 없었다. 코퍼스 파일 하나에 source 가 이미 들어 있다.

    주의: 코퍼스는 이번 회차 수집분이고 Records 는 누적분이다.
    둘은 다른 수다. 그래서 노트에도 서로 다른 이름으로 적는다.
    """
    counts: Counter = Counter()
    path = ROOT / "data" / "knowledge" / "training_corpus.jsonl"
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    counts[json.loads(line).get("source") or "?"] += 1
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return counts


def vault_totals() -> dict:
    """볼트 전체 규모. 파일 목록만 받으므로 내용은 읽지 않는다."""
    def n(sub):
        return len(git_ls(f"obsidian/JARVIS_LUNA/Knowledge/{sub}/"))
    return {"ref": REF, "records": n("Records"),
            "topics": n("Topics"), "orgs": n("Orgs")}


def link_team_from_topic(topic_path: Path, teams: list[str]) -> bool:
    """Topic 노트에 팀 링크를 한 줄 넣는다. 이미 있으면 건드리지 않는다."""
    try:
        text = topic_path.read_text(encoding="utf-8-sig")
    except OSError:
        return False
    marker = "## 담당 팀"
    if marker in text:
        return False
    links = " ".join(f"[[팀 · {t}]]" for t in teams)
    text = text.rstrip() + f"\n\n{marker}\n\n{links}\n"
    try:
        topic_path.write_text(text, encoding="utf-8")
    except OSError:
        return False
    return True


def main() -> int:
    if not TOPICS.exists():
        print(f"{TOPICS} 가 없다. organize_obsidian_graph.py 를 먼저 돌려야 한다.",
              file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc).isoformat()
    TEAMS.mkdir(parents=True, exist_ok=True)

    have = {p.stem for p in TOPICS.glob("*.md")}
    by_source = corpus_by_source()
    totals = vault_totals()

    # 수집원 -> 팀 을 뒤집어 팀별 현재 수집분을 만든다.
    team_corpus: Counter = Counter()
    for src, n in by_source.items():
        for t in SOURCE_TEAMS.get(src, []):
            team_corpus[t] += n

    # Topic -> 팀들 (역방향)
    topic_teams: dict = {}
    for team, topics in TEAM_TOPICS.items():
        for t in topics:
            topic_teams.setdefault(t, []).append(team)

    rows, missing = [], []
    for team, topics in TEAM_TOPICS.items():
        mine = [t for t in topics if t in have]
        missing += [t for t in topics if t not in have]
        n_cur = team_corpus.get(team, 0)
        my_src = [s_ for s_, ts in SOURCE_TEAMS.items() if team in ts]
        role, sources, outputs = TEAM_META.get(team, ("", [], []))
        note = TEAM_NOTE.format(
            team=team, now=now, role=role,
            n_topics=len(mine), n_current=n_cur,
            src_line=(" · ".join(f"{s_} {by_source.get(s_, 0):,}" for s_ in my_src)
                      or "직접 수집 없음"),
            topic_links=(" ".join(f"[[{t}]]" for t in mine) or "_아직 없음_"),
            sources="\n".join(f"- {s}" for s in sources) or "_없음_",
            outputs="\n".join(f"- `{o}`" for o in outputs) or "_없음_",
        )
        path = TEAMS / f"팀 · {team}.md"
        try:
            path.write_text(note, encoding="utf-8")
        except OSError as e:
            print(f"  {team} 기록 실패: {type(e).__name__}", file=sys.stderr)
            continue
        rows.append({"team": team, "topics": mine, "corpus_now": n_cur,
                     "sources": my_src, "note": str(path.relative_to(ROOT))})

    linked = 0
    for topic, teams in topic_teams.items():
        p = TOPICS / f"{topic}.md"
        if p.exists() and link_team_from_topic(p, teams):
            linked += 1

    orphan = sorted(t for t in have if t not in topic_teams)

    payload = {
        "generated_at": now,
        "generator": "scripts/build_team_hubs.py",
        "왜": ("Records 가 볼트의 98.6% 라 그래프뷰가 허브 몇 개에 점 수만 개가 "
              "매달린 모습이었다. Record -> Topic -> 팀 으로 층을 하나 넣는다."),
        "방식": ("Record 파일 3만 7천 개는 건드리지 않는다. Topic 노트에 팀 링크를 "
               "한 줄 더하는 것으로 층이 생긴다. 파일을 3만 개 고쳐 쓰면 커밋이 터진다."),
        "vault": totals,
        "corpus_by_source": dict(by_source),
        "teams": len(rows),
        "topics_linked": linked,
        "topics_without_team": orphan,
        "topics_missing": sorted(set(missing)),
        "items": sorted(rows, key=lambda r: -r["corpus_now"]),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for _ in range(4):
        OUT.write_text(body, encoding="utf-8")
        try:
            json.loads(OUT.read_text(encoding="utf-8-sig"))
            break
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            time.sleep(0.5)
    else:
        print("기록 검증 실패", file=sys.stderr)
        return 1

    print(f"팀 허브 {len(rows)}개 · Topic 에 팀 링크 {linked}개 추가")
    print(f"  볼트({totals['ref']}) Records {totals['records']:,} · "
          f"Topics {totals['topics']} · Orgs {totals['orgs']}")
    for r in payload["items"]:
        print(f"  {r['team']:12s} 주제 {len(r['topics']):2d}개 · 이번 수집 {r['corpus_now']:5,}건 "
              f"· 수집원 {','.join(r['sources']) or '-'}")
    if orphan:
        print(f"  팀이 없는 주제 {len(orphan)}개: {', '.join(orphan[:6])}")
    if payload["topics_missing"]:
        print(f"  매핑에만 있고 볼트에 없는 주제: {payload['topics_missing']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
