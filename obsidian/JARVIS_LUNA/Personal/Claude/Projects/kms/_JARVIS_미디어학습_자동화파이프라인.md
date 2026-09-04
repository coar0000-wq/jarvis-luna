# JARVIS 미디어 학습 자동화 파이프라인

**버전**: 1.0  
**상태**: 설계 완료 (2026-08-03)  
**목표**: YouTube, Podcast, 논문 자동 수집 및 분석  
**예상 처리량**: 200개 자료/월 (자동화)  

---

## 🎯 미션

기존의 정적 수동 학습 방식에서 벗어나 **실시간 미디어 통합** 시스템 구축. 도현님이 추천한 영상, 논문, 팟캐스트를 자동으로 수집→분석→메모리화하여 JARVIS의 지식을 지속적으로 갱신.

---

## 📊 데이터 소스 (200개/월 목표)

### 1. YouTube 채널 (자동 구독)

#### AI 에이전트 & LLM 관련 (60개/월)
```
채널 1: KodeKloud
- 특징: 실습 랩, 명확한 설명
- 게시 빈도: 주 1-2회
- 추천: AI Agents, LangChain, RAG, MCP

채널 2: DeepLearning.AI
- 특징: 전문가 강의, 최신 기술
- 게시 빈도: 월 4-8회
- 추천: LLM, Prompting, Agents

채널 3: freeCodeCamp.org
- 특징: 장형 튜토리얼 (2-5시간)
- 게시 빈도: 월 2-4회
- 추천: 프로젝트 기반 학습

채널 4-10: 전문 채널 (7개)
- 각 20개/월 기여
- 총 140개 콘텐츠
```

#### 의료 & 과학 (40개/월)
```
채널: Nature Video, TED-Ed, Kurzgesagt
- 의료 동향, 생명과학, AI 윤리
- 각 10-15개/월
```

### 2. Podcast (30개/월)

```
구독 목록:
- Lex Fridman Podcast: AI 인터뷰 (주 1회)
- The Future: 기술 미래 (주 1회)
- Sam Harris Making Sense: 철학/윤리 (월 2-4회)
- 기술 팟캐스트 (한국): 3-4개 (월 10-15회)

처리: Whisper STT → 자동 요약 → 메모리 파일
```

### 3. arXiv 자동 수집 (50개/월)

```
분야별 Daily Feed:
- AI/Machine Learning: 15-20개/일 → 월 300-600개
  필터링: "agents" "LLM" "RAG" 키워드
  
- Physics: 5-10개/일 → 월 150-300개
  필터링: "quantum" "neural" 관련

- Biology: 3-5개/일 → 월 90-150개
  필터링: "AI" "machine learning" 관련

실제 수집: 우수한 논문만 선별 (50개/월)
```

### 4. 학술 데이터베이스 (20개/월)

```
PubMed (의료): 10개/월
Nature/Science: 5개/월
IEEE Xplore: 5개/월
```

### 5. 업계 뉴스레터 & 블로그 (0개, 자동화 아직)

```
예정:
- Substack (AI 뉴스레터): 월 5-10개
- Medium AI 칼럼: 월 3-5개
- 기술 블로그: 월 5-10개
```

---

## 🔄 자동화 파이프라인 아키텍처

```
┌──────────────────────────────────────────────────────┐
│          JARVIS 미디어 학습 자동화 시스템             │
└──────────────────────────────────────────────────────┘

                    [데이터 수집층]
         /      |         |         |       \
    YouTube  Podcast   arXiv    PubMed   Blogs
        |        |        |        |       |
        └────────┴────────┴────────┴───────┘
                        ↓
              [전처리 및 분석층]
                  /    |    \
            Meta    Content  Extract
            Data    Analysis   Info
                        ↓
              [자동 요약 생성층]
            (GPT-4 Chain-of-Thought)
                        ↓
              [메모리 파일 생성층]
          (Markdown + YAML 메타데이터)
                        ↓
              [Obsidian 통합층]
          (노드 생성 + 백링크 추가)
                        ↓
           [검증 및 품질 관리층]
         (전문가 검토 + 자동 점수화)
                        ↓
           [최종 JARVIS 지식그래프]
         (메모리 인덱스 자동 업데이트)
```

---

## 🛠️ 세부 구현 프로세스

### Phase 1: YouTube 자동 분석 (기초)

#### 1.1 메타데이터 수집

```python
import pytube
from youtube_transcript_api import YouTubeTranscriptApi
import requests

def collect_youtube_metadata(video_url):
    """YouTube 영상 메타데이터 수집"""
    
    # 기본 정보
    yt = pytube.YouTube(video_url)
    metadata = {
        "url": video_url,
        "title": yt.title,
        "channel": yt.author,
        "length_seconds": yt.length,
        "views": yt.views,
        "publish_date": yt.publish_date,
        "description": yt.description,
        "keywords": yt.keywords,
        "thumbnail": yt.thumbnail_url
    }
    
    # 자막/스크립트 추출
    try:
        transcript = YouTubeTranscriptApi.get_transcript(
            yt.video_id,
            languages=['en', 'ko']
        )
        metadata["transcript"] = " ".join([t['text'] for t in transcript])
    except:
        metadata["transcript"] = "Not available"
    
    return metadata
```

#### 1.2 음성→텍스트 변환

```python
import openai
import os

def transcribe_with_whisper(video_url):
    """Whisper API로 음성 변환"""
    
    # 1. 영상 다운로드
    os.system(f"youtube-dl -f 'bestaudio' -o '%(id)s.%(ext)s' {video_url}")
    
    # 2. 오디오만 추출
    os.system("ffmpeg -i video_id.webm -q:a 0 -map a audio.mp3")
    
    # 3. Whisper API 호출
    with open("audio.mp3", "rb") as audio_file:
        transcript = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file,
            language="en"  # 또는 "ko"
        )
    
    return transcript["text"]
```

#### 1.3 자동 요약 생성

```python
import openai

def generate_summary(transcript, title):
    """GPT-4로 자동 요약 생성"""
    
    prompt = f"""
    영상 제목: {title}
    
    영상 전사:
    {transcript[:5000]}...  # 토큰 제한으로 5000자까지만
    
    다음을 분석해주세요:
    1. 핵심 주제 (3줄)
    2. 주요 학습 포인트 (5-10개, 각각 짧은 설명)
    3. 기술 스택 및 프레임워크
    4. JARVIS Phase 관련성 (해당하는 Phase 나열)
    5. 의료 AI 적용 사례 (있으면)
    6. 팀별 할당 추천 (A/B/C/D 팀)
    """
    
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,  # 의료 관련이므로 낮은 온도
        max_tokens=2000
    )
    
    return response["choices"][0]["message"]["content"]
```

### Phase 2: 메모리 파일 자동 생성

#### 2.1 Markdown 생성

```python
def generate_memory_file(metadata, summary, analysis):
    """메모리 파일 자동 생성"""
    
    content = f"""---
name: youtube-{metadata['video_id']}-analysis
description: "{metadata['title']} - YouTube 영상 분석"
metadata:
  type: learning-resource
  source: YouTube
  url: {metadata['url']}
  channel: {metadata['channel']}
  analyzed_date: {datetime.now().isoformat()}
  
  related_phases: {analysis['related_phases']}
  domains: {analysis['domains']}
  
  key_insights: {len(analysis['learning_points'])}
  learning_level: {analysis['level']}
  duration: {metadata['length_seconds']}s
  views: {metadata['views']}
  
tags:
  - source-youtube
  - learning-resource
  - 2026-latest
  {analysis['tags']}

---

# 📺 {metadata['title']}

**채널**: {metadata['channel']}
**업로드**: {metadata['publish_date'].strftime('%Y-%m-%d')}
**길이**: {metadata['length_seconds']//60}분 {metadata['length_seconds']%60}초
**조회수**: {metadata['views']:,}

## 🎯 요약
{summary['overview']}

## 📚 핵심 학습 포인트

{self._format_learning_points(summary['learning_points'])}

## 🔗 관련 Phase & 연결

{self._format_phase_links(analysis['related_phases'])}

## 💡 JARVIS 응용

{self._format_applications(analysis['applications'])}

---

**통합 상태**: ✅ 자동 생성 완료
**검증 상태**: ⏳ 전문가 검토 필요
**팀 할당**: {analysis['assigned_teams']}
"""
    
    return content
```

#### 2.2 파일 저장 및 인덱싱

```python
def save_and_index_memory(content, video_id):
    """메모리 파일 저장 및 인덱싱"""
    
    # 1. 파일 저장
    filename = f"youtube_integration_{video_id}.md"
    filepath = f"/path/to/kms/{filename}"
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    # 2. 메모리 인덱스 업데이트
    index_entry = f"- [YouTube 분석: {title}](youtube_integration_{video_id}.md) — {description}"
    
    with open("/path/to/MEMORY.md", 'a', encoding='utf-8') as f:
        f.write("\n" + index_entry)
    
    # 3. Git 커밋 (선택사항)
    os.system(f"cd /path/to/kms && git add {filename} MEMORY.md")
    os.system(f'git commit -m "Add YouTube analysis: {title}"')
    
    return filepath
```

### Phase 3: Obsidian 자동 연동

#### 3.1 노드 생성 및 연결

```python
def create_obsidian_node(metadata, analysis):
    """Obsidian에 새 노드 생성"""
    
    node_name = f"YouTube_{metadata['video_id']}"
    
    # 핵심 정보
    front_matter = f"""---
tags:
  - source-youtube
  - {analysis['domain']}
  - phase-{analysis['related_phases'][0]}

related_phases: {analysis['related_phases']}
domains: {analysis['domains']}
created: {datetime.now().isoformat()}
source_url: {metadata['url']}
channel: {metadata['channel']}
---
"""
    
    # 본문
    body = f"""
# {metadata['title']}

## 기본 정보
- **채널**: [[{metadata['channel']}]]
- **길이**: {metadata['length_seconds']//60}분
- **조회수**: {metadata['views']}

## 관련 Phase
{' '.join([f"[[{phase}]]" for phase in analysis['related_phases']])}

## 핵심 개념
{' '.join([f"[[{concept}]]" for concept in analysis['concepts']])}

## 기술 스택
{' '.join([f"[[{tech}]]" for tech in analysis['tech_stack']])}

## 메모리 파일
[[youtube_integration_{metadata['video_id']}]]
"""
    
    node_content = front_matter + body
    
    # 파일 저장
    obsidian_path = f"Obsidian_Vault/YouTube_Resources/{node_name}.md"
    with open(obsidian_path, 'w', encoding='utf-8') as f:
        f.write(node_content)
    
    return node_name
```

#### 3.2 백링크 자동 생성

```python
def create_backlinks(node_name, analysis):
    """기존 파일에 백링크 추가"""
    
    # 관련된 모든 Phase 파일에 링크 추가
    for phase in analysis['related_phases']:
        phase_file = f"Obsidian_Vault/{phase}.md"
        
        if os.path.exists(phase_file):
            with open(phase_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 참고 자료 섹션에 추가
            if "## 참고 자료" not in content:
                content += "\n## 참고 자료\n"
            
            # 중복 방지
            if f"[[{node_name}]]" not in content:
                content += f"- [[{node_name}]]\n"
            
            with open(phase_file, 'w', encoding='utf-8') as f:
                f.write(content)
```

### Phase 4: 품질 관리 및 검증

#### 4.1 자동 점수화

```python
def score_analysis_quality(metadata, summary, analysis):
    """분석 품질 자동 평가"""
    
    score = {
        "metadata_completeness": 0,
        "summary_quality": 0,
        "phase_relevance": 0,
        "technical_accuracy": 0,
        "overall_score": 0
    }
    
    # 메타데이터 완성도 (0-25점)
    required_fields = ['title', 'channel', 'length_seconds', 'views', 'transcript']
    score['metadata_completeness'] = (
        sum(1 for field in required_fields if metadata.get(field)) 
        / len(required_fields) * 25
    )
    
    # 요약 품질 (0-25점)
    summary_length = len(summary['overview'].split())
    learning_points_count = len(summary['learning_points'])
    score['summary_quality'] = min(25, summary_length / 20 + learning_points_count * 2)
    
    # Phase 관련성 (0-25점)
    score['phase_relevance'] = min(25, len(analysis['related_phases']) * 5)
    
    # 기술 정확성 (0-25점) - 전문가 수동 검토
    score['technical_accuracy'] = 0  # 나중에 추가
    
    # 종합 점수
    score['overall_score'] = sum([
        score['metadata_completeness'],
        score['summary_quality'],
        score['phase_relevance'],
        score['technical_accuracy']
    ]) / 4
    
    return score
```

#### 4.2 알림 시스템

```python
def send_quality_alert(score, video_title):
    """품질 문제 알림"""
    
    if score['overall_score'] < 50:
        alert = f"""
⚠️ 품질 경고: {video_title}
종합 점수: {score['overall_score']:.1f}/100

문제점:
"""
        if score['metadata_completeness'] < 20:
            alert += "- 메타데이터 불완전\n"
        if score['summary_quality'] < 20:
            alert += "- 요약 품질 낮음\n"
        if score['phase_relevance'] < 20:
            alert += "- Phase 관련성 낮음\n"
        
        alert += "\n추천: 수동 검토 필요"
        
        # 이메일 또는 Slack 알림
        send_notification(alert)
```

---

## 📅 주간 자동화 스케줄

```
월요일 00:00 UTC
├─ arXiv 최신 논문 수집 (50개)
├─ PubMed 의료 논문 (10개)
└─ 데이터베이스에 추가

화요일 09:00 UTC
├─ YouTube 채널 확인 (KodeKloud, DeepLearning.AI 등)
├─ 신규 영상 3-5개 발견
├─ Whisper로 자막 생성
└─ 요약 생성 시작

수요일 12:00 UTC
├─ 요약 완료 (전 날 영상)
├─ 메모리 파일 생성
├─ Obsidian 노드 생성
└─ 품질 평가

목요일 15:00 UTC
├─ Podcast 에피소드 확인 (10-15개)
├─ 음성→텍스트 처리 (배치)
└─ 요약 생성 시작

금요일 18:00 UTC
├─ 주간 처리 완료
├─ 품질 리포트 생성
├─ 전문가 검토 목록 작성
└─ 다음 주 계획 수립

토일 & 일요일: 유휴
(필요시 수동 검토)
```

---

## 📊 월간 처리량 목표

```
목표: 200개 자료/월

구성:
├─ YouTube 영상: 60개/월 (3개/일)
│  └─ 실제 분석: 30개/월 (우수 콘텐츠만 선별)
├─ Podcast: 30개/월 (주 7개)
├─ arXiv 논문: 50개/월 (주 12개)
├─ PubMed 의료: 10개/월 (주 2.5개)
├─ 기타 데이터베이스: 10개/월
└─ 뉴스레터/블로그: 10개/월 (추후 추가)

품질 보증:
- 80% 이상 자동화
- 90% 이상 정확도 (초기)
- 95% 이상 정확도 (6개월 후)
```

---

## 🔐 데이터 관리

### 저장소 구조

```
/JARVIS_Knowledge/
├── YouTube_Analysis/
│   ├── youtube_integration_ZaPbP9DwBOE.md
│   ├── youtube_integration_XXXXX.md
│   └── index.json
├── Papers/
│   ├── arxiv_2405_12345.md
│   ├── pubmed_2408_67890.md
│   └── index.json
├── Podcasts/
│   ├── lexfridman_ep123.md
│   ├── thefuture_ep45.md
│   └── index.json
└── MEMORY.md (통합 인덱스)
```

### 자동 백업

```
일일 자동 백업:
- 12:00 UTC: Amazon S3에 백업
- 00:00 UTC: 로컬 외장 드라이브에 백업

복구 시간:
- RTO (Recovery Time Objective): < 1시간
- RPO (Recovery Point Objective): < 24시간
```

---

## 🛡️ 보안 및 개인정보 보호

### 데이터 처리

```
수집 → 캐싱 → 분석 → 저장
 ↓
개인정보 필터링:
- 이메일 주소 제거
- 전화번호 제거
- 개인 식별자 마킹

의료 데이터:
- PHI (Protected Health Information) 제거
- 환자 사례는 익명화
```

### API 키 관리

```
환경 변수 저장:
OPENAI_API_KEY=sk-...
YOUTUBE_API_KEY=AIz...
PINECONE_API_KEY=pc-...

.env 파일 .gitignore 추가
```

---

## ⚠️ 리스크 및 완화 방법

| 리스크 | 심각도 | 완화 방법 |
|--------|--------|---------|
| API 과금 | 중간 | 일일 쿼리 제한, 배치 처리 |
| 저장소 용량 | 낮음 | 압축 저장, 클라우드 확장 |
| 분석 오류 | 중간 | 전문가 검토, QA 자동화 |
| 규제 변화 | 낮음 | 정기적 컴플라이언스 검토 |
| 기술 부채 | 중간 | 분기별 코드 리팩토링 |

---

## 🎯 성공 메트릭

| 메트릭 | 목표 | 측정 빈도 |
|--------|------|---------|
| 월간 자료 수집 | 200개 | 월간 |
| 자동화율 | 80% | 월간 |
| 오류율 | <5% | 주간 |
| 평균 분석 시간 | <30분 | 주간 |
| 메모리 파일 품질 | 4/5 | 월간 |
| Obsidian 그래프 성장 | +500 노드 | 월간 |

---

## 💡 향후 개선 (6개월 후)

1. **다중언어 지원**
   - 한국어, 중국어 콘텐츠 자동 처리
   - 자동 번역 및 요약

2. **인터랙티브 요약**
   - 영상별 챕터 자동 생성
   - 타임스탬프 기반 클립 추천

3. **고급 분석**
   - 핵심 연사/전문가 식별
   - 중복 콘텐츠 자동 필터링
   - 트렌드 분석 및 예측

4. **협업 기능**
   - 팀원 간 검토 워크플로우
   - 주석 및 토론 기능
   - 공유 및 내보내기

5. **실시간 대시보드**
   - 수집 통계 시각화
   - 품질 메트릭 모니터링
   - 팀 성과 추적

---

## ✅ 체크리스트

- [ ] 모든 API 키 설정 (YouTube, OpenAI, Whisper)
- [ ] 데이터 저장소 구조 생성
- [ ] 자동화 스크립트 개발
- [ ] 로깅 및 모니터링 시스템 구축
- [ ] 전문가 검토 프로세스 정의
- [ ] 백업 및 복구 계획 수립
- [ ] 팀 교육 실시
- [ ] 파일럿 실행 (50개 자료)
- [ ] 피드백 수렴 및 개선
- [ ] 프로덕션 배포

---

**예상 완성일**: 2026년 8월 말  
**영향**: JARVIS 학습 속도 5배 증가 (Level 2.8 → 2.9 진화)

