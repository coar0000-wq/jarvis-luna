# 🚀 JARVIS OS - Obsidian 그래프 뷰 대시보드

Claude AI 기반의 Obsidian 노트 관리 대시보드입니다.

## 📋 설치 방법

### 1. 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. 앱 실행
```bash
python jarvis_app.py
```

또는 Uvicorn으로 직접 실행:
```bash
uvicorn jarvis_app:app --reload --port 8000
```

### 3. 브라우저 접속
```
http://localhost:8000
```

## 🎯 주요 기능

✅ **Obsidian 그래프 뷰**
- 실시간 노트 시각화 (D3.js)
- 노트 간 링크 표시
- 대화형 드래그 앤 드롭

✅ **AI WORKSHOP OS 스타일**
- 왼쪽 사이드바 (카테고리, FORCES, DISPLAY)
- 중앙 그래프 영역
- 우측 필터 패널
- 하단 AI 채팅 인터페이스

✅ **Claude AI 채팅**
- 자연스러운 대화
- 노트 관련 질문
- 빠른 명령어 (Ask, Remind me, Good morning, Show)

✅ **실시간 통계**
- 총 노트 개수
- 연결 개수
- 카테고리별 분류

## 🔧 설정

### Obsidian 폴더 경로 변경
`jarvis_app.py`의 다음 줄을 수정:

```python
OBSIDIAN_VAULT = Path("당신의/Obsidian/경로")
```

### 포트 변경
```bash
uvicorn jarvis_app:app --port 3000
```

## 📝 사용법

1. **그래프 탐색**
   - 노드 드래그로 위치 조정
   - 마우스 휠로 줌
   - 노드 클릭으로 상세 정보

2. **AI 채팅**
   - 하단 입력창에 질문 입력
   - 빠른 명령어 버튼 사용
   - Enter 또는 📤 버튼으로 전송

3. **필터링**
   - 우측 패널의 필터로 노트 분류
   - 카테고리별 표시/숨김

4. **FORCES 조정**
   - Repel 슬라이더: 노드 간 반발력
   - Link length: 연결선 길이

## 🛠 기술 스택

- **Backend**: Python FastAPI
- **Server**: Uvicorn
- **Frontend**: HTML5, CSS3, JavaScript
- **Visualization**: D3.js v7
- **AI**: Anthropic Claude API
- **Data**: Obsidian Markdown Files

## 📂 폴더 구조

```
도현 physical/
├── jarvis_app.py           # FastAPI 앱
├── requirements.txt        # 의존성
├── templates/
│   └── index.html         # 웹 UI
└── static/
    ├── style.css          # 스타일
    ├── script.js          # 채팅 기능
    └── graph.js           # 그래프 시각화
```

## 🚀 빠른 시작

### PowerShell에서:
```powershell
cd "C:\Users\Desktop\Desktop\도현 physical"
pip install -r requirements.txt
python jarvis_app.py
```

### 그 후 브라우저에서:
```
http://localhost:8000
```

## 🎨 커스터마이징

### 색상 변경
`static/style.css`에서 변수 수정:
```css
--primary: #52d273;
--secondary: #90e0ef;
```

### 그래프 강도 조정
`static/graph.js`에서:
```javascript
.force('charge', d3.forceManyBody().strength(-300))
```

## 🔌 API 엔드포인트

- `GET /` - 메인 페이지
- `GET /api/graph` - Obsidian 그래프 데이터
- `POST /api/chat` - Claude AI 채팅
- `GET /api/stats` - 시스템 통계

## ⚠️ 문제 해결

**포트 8000이 이미 사용 중이라면:**
```bash
# 다른 포트로 실행
python jarvis_app.py --port 3000
```

**Obsidian 파일이 읽히지 않으면:**
- 폴더 경로 확인
- `.md` 파일 존재 확인
- 파일 인코딩이 UTF-8인지 확인

## 📞 지원

질문이나 문제가 있으면 이슈를 등록하세요.

---

**Made with ❤️ using Claude AI**
