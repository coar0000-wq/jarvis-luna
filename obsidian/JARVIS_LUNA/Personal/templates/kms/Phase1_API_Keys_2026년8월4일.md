---
name: phase1-api-keys-setup
description: Phase 1 Week 1 실행을 위한 3개 API 키 저장 (2026-08-04)
metadata:
  type: API Configuration
  status: Active
  date: 2026-08-04
  phase: Phase 1 Week 1
  nodes_connected: 3
---

# 🔑 Phase 1 Week 1: API 키 설정 완료

**작성일**: 2026-08-04
**상태**: ✅ 활성화됨
**다음 실행**: 2026-08-05 (내일)

---

## 📊 발급된 API 키 (3개)

### 1️⃣ NewsAPI
```
키: 51a641bc42eb40fa9f0022969b58aca9
환경변수: NEWSAPI_KEY
용도: 뉴스 검색 및 뉴스 에이전트 (12:00 뉴스브리핑)
상태: ✅ Active
```

**설정 방법:**
```powershell
$env:NEWSAPI_KEY = "51a641bc42eb40fa9f0022969b58aca9"
```

---

### 2️⃣ Alpha Vantage
```
키: GVD1R10Z7YTYBCMF
환경변수: ALPHA_VANTAGE_KEY
용도: 주식 시장 데이터 (17:30 비즈니스 리포트)
상태: ✅ Active
```

**설정 방법:**
```powershell
$env:ALPHA_VANTAGE_KEY = "GVD1R10Z7YTYBCMF"
```

---

### 3️⃣ OpenWeatherMap
```
키: 56393288cc71f2fab8dza53846fcb51f31
환경변수: OPENWEATHER_API_KEY
용도: 날씨 데이터 (08:00 모닝콜)
상태: ✅ Active
```

**설정 방법:**
```powershell
$env:OPENWEATHER_API_KEY = "56393288cc71f2fab8dza53846fcb51f31"
```

---

## 🛠️ 환경 변수 영구 설정

### Windows PowerShell (추천)

```powershell
# 현재 세션에만 적용
$env:NEWSAPI_KEY = "51a641bc42eb40fa9f0022969b58aca9"
$env:ALPHA_VANTAGE_KEY = "GVD1R10Z7YTYBCMF"
$env:OPENWEATHER_API_KEY = "56393288cc71f2fab8dza53846fcb51f31"

# 영구 설정 (시스템 환경변수)
[Environment]::SetEnvironmentVariable("NEWSAPI_KEY", "51a641bc42eb40fa9f0022969b58aca9", "User")
[Environment]::SetEnvironmentVariable("ALPHA_VANTAGE_KEY", "GVD1R10Z7YTYBCMF", "User")
[Environment]::SetEnvironmentVariable("OPENWEATHER_API_KEY", "56393288cc71f2fab8dza53846fcb51f31", "User")
```

### Python 코드에서 사용

```python
import os

newsapi_key = os.getenv("NEWSAPI_KEY")
alpha_vantage_key = os.getenv("ALPHA_VANTAGE_KEY")
openweather_key = os.getenv("OPENWEATHER_API_KEY")

print(f"NewsAPI: {newsapi_key}")
print(f"Alpha Vantage: {alpha_vantage_key}")
print(f"OpenWeather: {openweather_key}")
```

---

## 📅 다음 일정

| 시간 | 작업 | 상태 |
|------|------|------|
| 2026-08-05 08:00 | **1️⃣ API 키 발급** | ✅ 완료 |
| 2026-08-05 10:00 | **2️⃣ 패키지 설치** | ⏳ 예정 |
| 2026-08-05 10:10 | **3️⃣ pyttsx3 여성음 테스트** | ⏳ 예정 |
| 2026-08-05 10:15 | **4️⃣ 첫 모닝콜 테스트** | ⏳ 예정 |
| 2026-08-05 10:25 | **5️⃣ Asterisk 설정** | ⏳ 예정 |
| 2026-08-05 ~ 08-11 | **Phase 1 Week 1 전체 구현** | ⏳ 진행 중 |
| 2026-08-12 ~ 08-19 | **Phase 1 Week 2 (뉴스, 비즈니스, 철학 에이전트)** | ⏳ 예정 |
| 2026-08-19 | **Phase 1 정식 출시** | 🎯 목표 |

---

## 🔗 관련 노드

- [[JARVIS]]
- [[Phase 1 음성 시스템]]
- [[뉴스 에이전트]]
- [[비즈니스 에이전트]]
- [[철학 에이전트]]
- [[pyttsx3 여성음 설정]]
- [[n8n 워크플로우]]
- [[Asterisk PBX]]

---

**🚀 내일 10:00에 패키지 설치로 Phase 1 Week 1 공식 시작!**
