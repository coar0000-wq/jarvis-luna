# 🎙️ JARVIS 카카오톡 봇 설정 가이드

**목표**: 매일 08:00에 카카오톡으로 자동 메시지 발송 (완전 무료!)

---

## 📋 3단계 설정 가이드

### **Step 1️⃣ : 카카오 개발자 계정 준비**

1. **카카오 개발자 센터 접속**
   ```
   https://developers.kakao.com/
   ```

2. **로그인 (카카오 계정 필요)**
   - 없으면 회원가입 (무료)

3. **'내 애플리케이션' → '새 애플리케이션 만들기'**
   - 앱 이름: `JARVIS`
   - 앱 타입: `서버`

---

### **Step 2️⃣ : Open Builder로 봇 생성**

1. **API 메뉴 → 'Open Builder'**

2. **새 봇 생성**
   - 이름: `JARVIS 아침 비서`
   - 설명: `매일 아침 음성 메시지`

3. **기본 설정**
   - 시작 대사: "좋은 아침입니다!"
   - 저장

4. **봇 ID 확인** 🔑
   - 설정 → API → **Bot ID 복사**
   ```
   예: 5ab1a7a1c8a7d5c3b2a1f9e8
   ```

---

### **Step 3️⃣ : 환경변수 설정**

**PowerShell (관리자)에서 실행:**

```powershell
# 카카오 봇 ID 설정
$env:KAKAO_BOT_ID = "YOUR_BOT_ID_HERE"

# 테스트 사용자 ID (당신의 카카오 ID)
$env:KAKAO_USER_ID = "your_kakao_user_id"

# 날씨 API 키 (이미 설정했으면 생략)
$env:OPENWEATHER_API_KEY = "your_openweather_key"

# 확인
echo $env:KAKAO_BOT_ID
```

---

## 🚀 빠른 시작 (5분)

### 1️⃣ 폴더 이동
```powershell
cd C:\Users\Desktop\Claude\Projects\kms
```

### 2️⃣ 패키지 설치
```powershell
python -m pip install requests schedule --break-system-packages
```

### 3️⃣ 테스트 실행
```powershell
python jarvis_kakao_morning_message.py
```

✅ 성공하면: **"✅ 카카오톡 메시지 발송 성공!"**

### 4️⃣ 자동화 설정
```powershell
python setup_kakao_scheduler.py
```

✅ 완료하면: **매일 08:00에 자동 메시지 발송!**

---

## 💡 작동 원리

```
08:00
  ↓
Windows Task Scheduler 작동
  ↓
jarvis_kakao_morning_message.py 실행
  ↓
OpenWeather API → 날씨 조회
  ↓
Kakao API → 카카오톡 메시지 발송
  ↓
당신의 카카오톡 앱 수신 📲
  ↓
"좋은 아침입니다, 도현님! 🌅
  서울은 맑음이고 기온은 15도입니다
  오늘도 최고의 하루가 되길 응원합니다!"
```

---

## 🔧 환경변수 영구 설정 (선택)

**PowerShell을 재시작해도 유지하려면:**

```powershell
# 시스템 환경변수로 등록
[Environment]::SetEnvironmentVariable("KAKAO_BOT_ID", "YOUR_BOT_ID", "User")
[Environment]::SetEnvironmentVariable("KAKAO_USER_ID", "YOUR_USER_ID", "User")

# PowerShell 재시작 후 확인
$env:KAKAO_BOT_ID
```

---

## ❓ 자주 묻는 질문

### Q: 봇 ID는 어디서 찾나요?
**A:** Kakao Developers → 내 애플리케이션 → Open Builder → 설정 → **App Key**

### Q: 테스트할 때 메시지가 안 옵니다
**A:** 
1. 봇 ID 확인
2. 카카오톡 앱에서 해당 봇과 채팅 시작
3. 다시 테스트 실행

### Q: Task Scheduler에서 자동 실행이 안 됨
**A:**
1. Task Scheduler 열기 (Win+R → taskschd.msc)
2. "JARVIS_Kakao_MorningMessage_08AM" 우클릭
3. 속성 → 실행 (동작 탭에 python.exe 경로 확인)

### Q: 메시지 포맷을 바꿀 수 있나요?
**A:** `jarvis_kakao_morning_message.py` 의 `send_morning_message()` 함수 수정

---

## 💰 비용

| 항목 | 비용 |
|------|------|
| 카카오 Open Builder | 무료 |
| 카카오톡 메시지 API | 무료 |
| OpenWeather API | 무료 (1000 요청/일) |
| **총 비용** | **$0** |

---

## 📊 현재 상태

✅ Python 스크립트 완성  
✅ Task Scheduler 자동화 준비  
⏳ 카카오 봇 설정 (당신이 진행)  
⏳ 첫 테스트 실행  
⏳ 자동화 활성화  

---

## 🎯 다음 단계

1. **Step 1-3 완료** (위 가이드 따라하기)
2. **테스트 실행** (`python jarvis_kakao_morning_message.py`)
3. **자동화 설정** (`python setup_kakao_scheduler.py`)
4. **매일 08:00에 카카오톡 수신! 🎉**

---

**완료되면 알려주세요!** 🚀
