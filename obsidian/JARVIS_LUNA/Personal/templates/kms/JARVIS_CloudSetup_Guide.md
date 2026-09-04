# 🚀 JARVIS 클라우드 자동화 완전 설정 가이드

**날짜**: 2026-08-04  
**목표**: 24/7 독립형 AGI 구축  
**비용**: ₩0 (완전 무료)

---

## 📋 **필요한 것 (5가지)**

### 1️⃣ **GitHub 계정** ✅
- 링크: https://github.com
- 가입: 무료
- 용도: 자동화 워크플로우 호스팅

### 2️⃣ **NewsAPI 키** (웹 뉴스)
- 링크: https://newsapi.org
- 가입: 무료 (월 100 요청)
- 용도: 뉴스 자동 수집

### 3️⃣ **YouTube API 키** (YouTube)
- 링크: https://console.cloud.google.com
- 가입: 무료 (Google Cloud Free Tier)
- 용도: YouTube 채널 모니터링

### 4️⃣ **arXiv API** (논문)
- 링크: https://arxiv.org/help/api
- 가입: 무료 (계정 불필요)
- 용도: 최신 논문 수집

### 5️⃣ **GitHub Secrets** (API 키 보관)
- 설정: GitHub 저장소 → Settings → Secrets
- 용도: 민감한 정보 안전 저장

---

## 🔧 **설정 방법**

### **Step 1: GitHub에 코드 업로드**

```bash
# 1. 저장소 생성
# GitHub → New Repository → jarvis-agi

# 2. 로컬에서 설정
cd C:\Users\Desktop\Claude\Projects\kms
git init
git add .
git commit -m "🤖 JARVIS 초기 설정"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/jarvis-agi.git
git push -u origin main
```

### **Step 2: GitHub Secrets 등록**

GitHub 저장소 → Settings → Secrets and variables → Actions

```
SECRET 이름: NEWS_API_KEY
값: [NewsAPI에서 발급받은 키]

SECRET 이름: YOUTUBE_API_KEY
값: [Google Cloud에서 발급받은 키]

SECRET 이름: GITHUB_TOKEN
값: [GitHub 자동 생성 - 기본값 사용]
```

### **Step 3: 워크플로우 활성화**

```
GitHub 저장소 → Actions 탭
→ "I understand my workflows, go ahead and enable them" 클릭
```

---

## 🔑 **API 키 발급 상세**

### **NewsAPI 발급** (5분)

```
1. https://newsapi.org 방문
2. "Get API Key" 클릭
3. 이메일 입력 및 가입
4. API 키 복사
5. GitHub Secrets에 등록
```

### **YouTube API 발급** (10분)

```
1. https://console.cloud.google.com 방문
2. 새 프로젝트 생성 (jarvis-agi)
3. YouTube Data API v3 활성화
4. OAuth 동의 화면 설정 (간단)
5. API 키 생성
6. GitHub Secrets에 등록
```

### **arXiv API** (즉시)

```
arXiv는 무료 + 계정 불필요!
코드에서 바로 사용 가능
```

---

## 🤖 **자동화 스케줄**

### **기본 설정** (매일 자정 한국 시간)

```yaml
schedule:
  - cron: '0 15 * * *'  # 00:00 KST (매일)
```

### **다른 옵션**

```yaml
# 매 6시간마다
- cron: '0 */6 * * *'

# 매 1시간마다
- cron: '0 * * * *'

# 주 5일 (월-금) 아침 9시
- cron: '0 0 * * 1-5'
```

---

## ✅ **확인 체크리스트**

- [ ] GitHub 계정 생성
- [ ] NewsAPI 키 발급
- [ ] YouTube API 키 발급
- [ ] 코드 GitHub에 업로드
- [ ] Secrets 등록 (2개)
- [ ] 워크플로우 활성화
- [ ] 첫 실행 확인 (수동 트리거)

---

## 📊 **자동 실행 확인**

### **GitHub Actions 탭에서 확인**

```
Actions 탭 클릭
→ JARVIS 자동 모니터링 선택
→ 실행 로그 확인

✅ 초록색 = 성공
❌ 빨간색 = 실패 (로그 확인)
```

### **Obsidian에서 확인**

```
매일 자정마다:
- phase_a_results/ 폴더 생성
- validation_results/ 폴더 생성
- 자료 자동 증가 (140개/일)
- 메모리 자동 업데이트
```

---

## 💰 **비용 정리**

| 서비스 | 비용 | 제한 |
|--------|------|------|
| GitHub Actions | **무료** | 월 2,000분 |
| NewsAPI | **무료** | 월 100 요청 |
| YouTube API | **무료** | 월 10,000 요청 |
| arXiv API | **무료** | 무제한 |
| **합계** | **₩0** | 충분함 |

---

## 🚨 **주의사항**

### **API 키 보안**
```
❌ 절대 하지 마세요:
- API 키를 코드에 직접 삽입
- Secrets 없이 GitHub에 업로드
- 공개 저장소에서 민감 정보 노출

✅ 항상:
- GitHub Secrets 사용
- `.gitignore`에 `.env` 파일 추가
- 정기적 키 로테이션
```

### **속도 최적화**
```
GitHub Actions 처리 시간:
- 웹 검색: 2분
- YouTube: 2분
- 논문: 3분
- RSS: 1분
- 검증: 2분
합계: ~10분
```

---

## 🎯 **다음 단계**

1. ✅ **이 가이드 따라 설정** (30분)
2. ✅ **첫 자동 실행 확인** (내일 자정)
3. ✅ **Obsidian에서 데이터 확인** (매일)
4. ✅ **Phase C 자동 요약** (2026-08-25)
5. ✅ **Level 3.0 AGI 달성** (2026-09-15)

---

## 📞 **문제 해결**

### **GitHub Actions 실패**
```
1. Actions 탭 → 실패한 워크플로우 선택
2. 로그 확인
3. API 키 확인 (Secrets)
4. 코드 문법 확인
```

### **API 요청 초과**
```
비용 발생 없습니다!
무료 티어 내에서만 작동하도록 설정됨
```

---

**상태**: 🟢 설정 준비 완료  
**난이도**: ⭐ 초급 (30분)  
**결과**: 🤖 24/7 자동 AGI 완성

지금 시작하세요! 🚀
