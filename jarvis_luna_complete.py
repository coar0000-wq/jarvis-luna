#!/usr/bin/env python3
import os
import json
import asyncio
import aiohttp
import feedparser
from datetime import datetime
import google.generativeai as genai
import pathlib

# Obsidian vault 경로 (동적 설정)
OBSIDIAN_VAULT = os.getenv('OBSIDIAN_VAULT', os.path.expanduser('~/Obsidian'))
OBSIDIAN_FOLDER = os.path.join(OBSIDIAN_VAULT, "JARVIS_LUNA_Data")
OUTPUT_FILE = "jarvis_luna_realtime.json"

# Gemini API 키 (필수)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    print("⚠️ Warning: GEMINI_API_KEY environment variable not set. Using mock mode.")
    GEMINI_API_KEY = "mock-key-for-testing"

# Gemini 클라이언트 초기화
try:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-pro')
except Exception as e:
    print(f"⚠️ Warning: Could not initialize Gemini client: {e}")

async def fetch_youtube_realtime():
    """YouTube 데이터 수집"""
    try:
        # 더미 데이터 (실제로는 YouTube API 사용)
        return [{
            "title": f"YouTube Video {datetime.now().strftime('%H:%M')}",
            "channel": "Channel Name",
            "url": "https://youtube.com"
        }]
    except Exception as e:
        print(f"YouTube 오류: {e}")
        return []

async def fetch_arxiv_realtime():
    """arXiv 논문 수집"""
    try:
        feed = feedparser.parse('http://export.arxiv.org/rss/cs.AI?max_results=10')
        return [{
            "title": entry.get('title', 'No Title')[:100],
            "authors": entry.get('author', 'Unknown'),
            "url": entry.get('id', '')
        } for entry in feed.entries[:5]]
    except Exception as e:
        print(f"arXiv 오류: {e}")
        return []

async def fetch_google_news_realtime():
    """Google News 수집"""
    try:
        feed = feedparser.parse('https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko')
        return [{
            "title": entry.get('title', 'No Title')[:100],
            "source": entry.get('source', {}).get('title', 'Unknown'),
            "url": entry.get('link', '')
        } for entry in feed.entries[:5]]
    except Exception as e:
        print(f"News 오류: {e}")
        return []

def analyze_with_gemini(data, topic):
    """Gemini API로 분석"""
    try:
        prompt = f"""다음 {topic} 데이터를 간단히 분석해주세요 (2-3줄):
        {json.dumps(data, ensure_ascii=False, indent=2)}"""

        # Gemini API 호출
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"⚠️ Gemini 분석 오류: {e}")
        return f"분석 불가 ({topic})"

def save_to_obsidian(youtube_data, arxiv_data, news_data):
    """Obsidian 폴더에 markdown 파일 저장"""
    try:
        # Obsidian 폴더 생성
        obsidian_path = pathlib.Path(OBSIDIAN_FOLDER)
        obsidian_path.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        # JARVIS LUNA 인덱스 페이지
        index_content = f"""---
title: JARVIS LUNA 실시간 수집
date: {date_str}
tags: [jarvis-luna, realtime, youtube, arxiv, news]
---

# 🤖 JARVIS LUNA 실시간 데이터

**마지막 업데이트:** {time_str}

## 📺 YouTube
[[JARVIS LUNA YouTube {date_str}]]

## 📄 arXiv
[[JARVIS LUNA arXiv {date_str}]]

## 📰 Google News
[[JARVIS LUNA News {date_str}]]

---
자동 생성됨: JARVIS LUNA Gemini Edition
"""

        # YouTube 페이지
        youtube_content = f"""---
title: JARVIS LUNA YouTube {date_str}
date: {date_str}
category: youtube
tags: [youtube, video, realtime]
---

# 📺 YouTube 실시간 수집

**시간:** {time_str}

## 데이터
{json.dumps(youtube_data, ensure_ascii=False, indent=2)}

## 분석
{analyze_with_gemini(youtube_data, 'YouTube 영상')}

---
[[JARVIS LUNA 실시간 수집]]
"""

        # arXiv 페이지
        arxiv_content = f"""---
title: JARVIS LUNA arXiv {date_str}
date: {date_str}
category: arxiv
tags: [arxiv, papers, research]
---

# 📄 arXiv 논문 수집

**시간:** {time_str}

## 데이터
{json.dumps(arxiv_data, ensure_ascii=False, indent=2)}

## 분석
{analyze_with_gemini(arxiv_data, 'arXiv 논문')}

---
[[JARVIS LUNA 실시간 수집]]
"""

        # News 페이지
        news_content = f"""---
title: JARVIS LUNA News {date_str}
date: {date_str}
category: news
tags: [news, google-news, realtime]
---

# 📰 Google News

**시간:** {time_str}

## 데이터
{json.dumps(news_data, ensure_ascii=False, indent=2)}

## 분석
{analyze_with_gemini(news_data, 'News')}

---
[[JARVIS LUNA 실시간 수집]]
"""

        # 파일 저장
        (obsidian_path / "JARVIS_LUNA_실시간_수집.md").write_text(index_content, encoding='utf-8')
        (obsidian_path / f"JARVIS_LUNA_YouTube_{date_str}.md").write_text(youtube_content, encoding='utf-8')
        (obsidian_path / f"JARVIS_LUNA_arXiv_{date_str}.md").write_text(arxiv_content, encoding='utf-8')
        (obsidian_path / f"JARVIS_LUNA_News_{date_str}.md").write_text(news_content, encoding='utf-8')

        print(f"✅ Obsidian 저장 완료: {obsidian_path}")
        return True
    except Exception as e:
        print(f"Obsidian 저장 오류: {e}")
        return False

async def main():
    """메인 실행 함수"""
    print("🚀 JARVIS LUNA 시작...")

    # 데이터 수집
    youtube_data = await fetch_youtube_realtime()
    arxiv_data = await fetch_arxiv_realtime()
    news_data = await fetch_google_news_realtime()

    # JSON 저장
    data = {
        "timestamp": datetime.now().isoformat(),
        "youtube_data": youtube_data,
        "arxiv_data": arxiv_data,
        "google_news_data": news_data
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ JSON 저장 완료: {OUTPUT_FILE}")

    # Obsidian 저장
    save_to_obsidian(youtube_data, arxiv_data, news_data)

    print("✅ JARVIS LUNA 완료!")

if __name__ == "__main__":
    asyncio.run(main())
