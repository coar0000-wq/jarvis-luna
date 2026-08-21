#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧠 MoE 논문 실제 데이터 수집 스크립트
arXiv에서 Mixture of Experts 관련 최신 논문을 수집합니다
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

def collect_moe_papers():
    """arXiv에서 MoE 논문 수집 (실제 API 호출)"""
    try:
        import requests
        import feedparser
    except ImportError:
        print("❌ requests/feedparser 없음. 설치: pip install requests feedparser")
        return None

    # arXiv API 쿼리
    queries = [
        'cat:cs.LG AND ("mixture of experts" OR "MoE" OR "sparse routing")',
        'cat:cs.AI AND (router OR "expert network" OR "conditional computation")',
        'cat:stat.ML AND ("gating network" OR "expert selection")',
    ]

    all_papers = []

    for query in queries:
        try:
            url = 'http://export.arxiv.org/api/query'
            params = {
                'search_query': query,
                'start': 0,
                'max_results': 30,
                'sortBy': 'submittedDate',
                'sortOrder': 'descending'
            }

            response = requests.get(url, params=params, timeout=10)

            if response.status_code != 200:
                print(f"⚠️ arXiv API 오류 (상태: {response.status_code})")
                continue

            feed = feedparser.parse(response.content)

            for entry in feed.entries:
                paper = {
                    'title': entry.get('title', 'Unknown').replace('\n', ' '),
                    'authors': [author.name for author in entry.get('authors', [])],
                    'published': entry.get('published', '')[:10],
                    'arxiv_id': entry.get('id', '').split('/abs/')[-1],
                    'summary': entry.get('summary', '')[:500],
                    'pdf_url': f"https://arxiv.org/pdf/{entry.get('id', '').split('/abs/')[-1]}.pdf",
                    'categories': entry.get('arxiv_primary_category', {}).get('term', '')
                }
                all_papers.append(paper)

        except Exception as e:
            print(f"⚠️ 쿼리 오류: {str(e)}")
            continue

    return all_papers

def analyze_papers(papers):
    """수집된 논문 분석"""
    if not papers:
        return None

    analysis = {
        'timestamp': datetime.now().isoformat(),
        'total_papers': len(papers),
        'date_range': {
            'earliest': min(p['published'] for p in papers),
            'latest': max(p['published'] for p in papers)
        },
        'authors': len(set(
            author for paper in papers
            for author in paper['authors']
        )),
        'categories': list(set(p['categories'] for p in papers if p['categories'])),
        'top_authors': [],
        'papers': papers[:50]  # 상위 50개만 저장
    }

    # 상위 저자 분석
    author_count = {}
    for paper in papers:
        for author in paper['authors'][:2]:  # 처음 2명만 고려
            author_count[author] = author_count.get(author, 0) + 1

    analysis['top_authors'] = sorted(
        author_count.items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]

    return analysis

def generate_report(analysis):
    """수집 결과 리포트 생성"""
    if not analysis:
        return {
            'status': '❌ 실패',
            'timestamp': datetime.now().isoformat(),
            'reason': '논문 수집 실패',
            'papers_collected': 0
        }

    report = {
        'status': '✅ 성공',
        'timestamp': analysis['timestamp'],
        'papers_collected': analysis['total_papers'],
        'summary': {
            'total': analysis['total_papers'],
            'unique_authors': analysis['authors'],
            'categories': analysis['categories'],
            'date_range': analysis['date_range']
        },
        'top_10_papers': analysis['papers'][:10],
        'top_authors': analysis['top_authors'][:5],
        'next_action': '신경망 설계 및 라우팅 알고리즘 구현'
    }

    return report

def save_results(papers, analysis, report):
    """결과 저장"""
    output_dir = Path('data/phase26_moe')
    output_dir.mkdir(parents=True, exist_ok=True)

    # 전체 논문 저장
    with open(output_dir / 'moe_papers_full.json', 'w', encoding='utf-8') as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)

    # 분석 결과 저장
    with open(output_dir / 'moe_analysis.json', 'w', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    # 리포트 저장
    with open(output_dir / 'moe_collection_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return output_dir

def main():
    """메인 실행"""
    print("🚀 JARVIS Phase 26: MoE 논문 수집 시작...")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 논문 수집
    print("📡 arXiv에서 MoE 논문 수집 중...")
    papers = collect_moe_papers()

    if not papers:
        print("❌ 논문 수집 실패")
        return 1

    print(f"✅ {len(papers)}개 논문 수집 완료")

    # 분석
    print("📊 논문 분석 중...")
    analysis = analyze_papers(papers)

    # 리포트 생성
    print("📝 리포트 생성 중...")
    report = generate_report(analysis)

    # 결과 저장
    print("💾 결과 저장 중...")
    output_dir = save_results(papers, analysis, report)

    # 최종 출력
    print()
    print("=" * 60)
    print(f"✅ Phase 26 MoE 논문 수집 완료!")
    print("=" * 60)
    print()
    print(f"📊 수집 통계:")
    print(f"   • 총 논문: {report['papers_collected']}개")
    print(f"   • 고유 저자: {report['summary']['unique_authors']}명")
    print(f"   • 범주: {', '.join(report['summary']['categories'][:3])}")
    print(f"   • 기간: {report['summary']['date_range']['earliest']} ~ {report['summary']['date_range']['latest']}")
    print()
    print(f"🔝 상위 논문:")
    for i, paper in enumerate(report['top_10_papers'][:3], 1):
        print(f"   {i}. {paper['title'][:60]}...")
        print(f"      저자: {', '.join(paper['authors'][:2])}")
        print(f"      ID: {paper['arxiv_id']}")
    print()
    print(f"📁 저장 위치: {output_dir}")
    print()
    print("🎯 다음 단계:")
    print("   1. 신경망 설계 (3개 도메인 전문가)")
    print("   2. MoE 라우터 구현")
    print("   3. 성능 벤치마킹")
    print()

    return 0

if __name__ == '__main__':
    sys.exit(main())
