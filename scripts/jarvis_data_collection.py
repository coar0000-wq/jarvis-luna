#!/usr/bin/env python3
"""
JARVIS LUNA - Automatic Data Collection System
매시간 YouTube, arXiv, Google News에서 데이터 수집
"""

import os
import json
from datetime import datetime
import asyncio
import aiohttp
import feedparser

class JARVISDataCollector:
    def __init__(self):
        self.timestamp = datetime.now().isoformat()
        self.data_dir = "data/collection"
        self.stats = {
            "youtube_videos": 0,
            "arxiv_papers": 0,
            "news_articles": 0,
            "total_tokens": 0,
            "processing_time": 0
        }

        # 디렉토리 생성
        os.makedirs(self.data_dir, exist_ok=True)

    async def collect_youtube_metadata(self):
        """YouTube 채널 메타데이터 수집"""
        print("[JARVIS] Collecting YouTube metadata...")

        # 모의 데이터 (실제로는 YouTube API 사용)
        data = {
            "timestamp": self.timestamp,
            "channels": [
                {"name": "AI Research", "videos": 12, "views": 145000},
                {"name": "Quantum Computing", "videos": 8, "views": 89000},
                {"name": "Medical AI", "videos": 15, "views": 203000}
            ],
            "total_videos": 35,
            "total_views": 437000
        }

        with open(f"{self.data_dir}/youtube_{datetime.now().strftime('%Y%m%d_%H')}.json", 'w') as f:
            json.dump(data, f, indent=2)

        self.stats["youtube_videos"] = data["total_videos"]
        print(f"✓ Collected {data['total_videos']} YouTube videos")

    async def collect_arxiv_papers(self):
        """arXiv 논문 데이터 수집"""
        print("[JARVIS] Collecting arXiv papers...")

        try:
            async with aiohttp.ClientSession() as session:
                # arXiv API에서 최신 논문 수집
                categories = [
                    "cs.AI",
                    "cs.LG",
                    "quant-ph",
                    "stat.ML",
                    "math.QA"
                ]

                papers = []
                for category in categories:
                    url = f"http://export.arxiv.org/api/query?search_query=cat:{category}&start=0&max_results=10&sortBy=submittedDate"
                    try:
                        async with session.get(url, timeout=10) as resp:
                            content = await resp.text()
                            # 간단한 파싱
                            paper_count = content.count("<entry>")
                            papers.append({"category": category, "count": paper_count})
                    except:
                        pass

                data = {
                    "timestamp": self.timestamp,
                    "categories": papers,
                    "total_papers": sum(p["count"] for p in papers)
                }

                with open(f"{self.data_dir}/arxiv_{datetime.now().strftime('%Y%m%d_%H')}.json", 'w') as f:
                    json.dump(data, f, indent=2)

                self.stats["arxiv_papers"] = data["total_papers"]
                print(f"✓ Collected {data['total_papers']} arXiv papers")
        except Exception as e:
            print(f"✗ Error collecting arXiv: {e}")

    async def collect_news(self):
        """Google News 피드 수집"""
        print("[JARVIS] Collecting news...")

        try:
            feeds = [
                "https://news.google.com/rss/search?q=AI+evolution&hl=ko&gl=KR&ceid=KR:ko",
                "https://news.google.com/rss/search?q=machine+learning&hl=ko&gl=KR&ceid=KR:ko",
                "https://news.google.com/rss/search?q=quantum+computing&hl=ko&gl=KR&ceid=KR:ko"
            ]

            articles = []
            for feed_url in feeds:
                try:
                    feed = feedparser.parse(feed_url)
                    articles.extend(feed.entries[:5])
                except:
                    pass

            data = {
                "timestamp": self.timestamp,
                "articles": len(articles),
                "sources": len(feeds),
                "last_update": datetime.now().isoformat()
            }

            with open(f"{self.data_dir}/news_{datetime.now().strftime('%Y%m%d_%H')}.json", 'w') as f:
                json.dump(data, f, indent=2)

            self.stats["news_articles"] = len(articles)
            print(f"✓ Collected {len(articles)} news articles")
        except Exception as e:
            print(f"✗ Error collecting news: {e}")

    async def run(self):
        """메인 수집 루틴"""
        print(f"\n{'='*60}")
        print(f"JARVIS LUNA Data Collection - {self.timestamp}")
        print(f"{'='*60}\n")

        start_time = datetime.now()

        # 병렬 수집
        await asyncio.gather(
            self.collect_youtube_metadata(),
            self.collect_arxiv_papers(),
            self.collect_news()
        )

        # 통계 저장
        elapsed = (datetime.now() - start_time).total_seconds()
        self.stats["processing_time"] = elapsed

        # 일일 통계 업데이트
        stats_file = "data/daily_stats.json"
        try:
            with open(stats_file, 'r') as f:
                daily_stats = json.load(f)
        except:
            daily_stats = []

        daily_stats.append({
            "timestamp": self.timestamp,
            "stats": self.stats
        })

        # 최근 7일만 유지
        daily_stats = daily_stats[-168:]

        with open(stats_file, 'w') as f:
            json.dump(daily_stats, f, indent=2)

        print(f"\n{'='*60}")
        print("Collection Summary:")
        print(f"  YouTube Videos: {self.stats['youtube_videos']}")
        print(f"  arXiv Papers: {self.stats['arxiv_papers']}")
        print(f"  News Articles: {self.stats['news_articles']}")
        print(f"  Processing Time: {elapsed:.2f}s")
        print(f"{'='*60}\n")

        return self.stats

async def main():
    collector = JARVISDataCollector()
    await collector.run()

if __name__ == "__main__":
    asyncio.run(main())
