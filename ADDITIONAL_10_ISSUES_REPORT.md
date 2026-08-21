# 🔴 추가 발견된 10개 심각 문제 & 즉시 해결 방안

**발견일:** 2026-08-17  
**영향도:** 높음 (Timeout, Race Condition, Memory Leak)  
**해결 시간:** ~30분  

---

## 📋 10개 새 문제 상세 분석

### 🔴 CRITICAL - 1개

#### #1: fetchWithTimeout 미사용 (5개 위치에서 fetch 직접 호출)
**라인:** 612, 638, 680, 850, 873  
**현재 코드:**
```javascript
const response = await fetch('./data/phase_26_progress.json?t=' + Date.now());
// ❌ 타임아웃 없음 → 무한 대기 가능
```

**문제점:**
- fetchWithTimeout이 구현되었지만 loadRealData에만 사용
- 나머지 4개 함수에서는 fetch() 직접 호출
- 느린 네트워크 → 30초 이상 대기 → UI 프리징

**해결책:**
```javascript
// ✅ 모든 fetch() → fetchWithTimeout()으로 변경
const response = await fetchWithTimeout('./data/phase_26_progress.json?t=' + Date.now());
```

**적용 위치:**
- loadPhaseData() - 라인 612, 638
- loadCumulativeCount() - 라인 680
- updateScheduleInfo() - 라인 850, 873

---

### 🟠 HIGH - 3개

#### #2: 이중 console 호출 (중복 로깅)
**라인:** 612-615, 638-640, 680-682  
**현재 코드:**
```javascript
const response = await fetch(...);
if (response.ok) {
    const data = await response.json();
    console.log('✅ [Phase 26] 진행도 데이터 로드 성공:', data);
}
```

**문제점:**
- Logger 클래스로 통합했는데 일부는 여전히 console.log 사용
- 같은 정보가 2번 로깅됨 → 성능 저하

**해결책:**
```javascript
const data = await response.json();
Logger.info('Phase26', '진행도 데이터 로드 성공');
// ✅ console.log 모두 제거
```

---

#### #3: response.ok 검증 미흡
**라인:** 612-614, 638-641, 680-683  
**현재 코드:**
```javascript
const response = await fetch(...);
if (response.ok) { /* 처리 */ }
// ❌ else 블록이 없음 (암시적 실패)
```

**문제점:**
- 404, 500 등의 HTTP 에러를 무시함
- response.json()을 시도 → JSON 파싱 에러로 이어짐
- 원인 추적 불가능

**해결책:**
```javascript
if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
}
const data = await response.json();
Logger.info('Phase26', '데이터 로드 성공');
```

---

#### #4: JSON.parse 예외처리 약함
**라인:** 599 (LocalStorage)  
**현재 코드:**
```javascript
const cached = JSON.parse(localStorage.getItem('jarvis_product_cache'));
// ❌ JSON.parse 실패 → 전체 함수 실패
```

**문제점:**
- 캐시가 손상되면 JSON.parse 에러
- 에러 객체만 전달 → 원인 불명

**해결책:**
```javascript
try {
    const cached = JSON.parse(localStorage.getItem('jarvis_product_cache') || '{}');
    if (cached.total_products) {
        Logger.warn('상품계산', `캐시 사용: ${cached.total_products}개`);
        return cached;
    }
} catch (e) {
    Logger.error('상품계산', 'JSON 파싱 실패', e.message);
    // 캐시 무효화
    localStorage.removeItem('jarvis_product_cache');
}
```

---

### 🟡 MEDIUM - 6개

#### #5: 캐시 만료 시간(TTL) 없음
**라인:** 730-739 (캐시 저장)  
**현재 코드:**
```javascript
localStorage.setItem('jarvis_product_cache', JSON.stringify({
    total_products: totalCumulativeProducts,
    timestamp: new Date().toISOString()
}));
// ❌ 1년 된 데이터도 그냥 사용
```

**문제점:**
- timestamp는 있지만 TTL 체크 없음
- 오래된 데이터로 잘못된 결정 가능

**해결책:**
```javascript
const CACHE_TTL = 5 * 60 * 1000; // 5분

function isCacheValid(timestamp) {
    if (!timestamp) return false;
    const age = Date.now() - new Date(timestamp).getTime();
    return age < CACHE_TTL;
}

// 사용처
if (cached.timestamp && isCacheValid(cached.timestamp)) {
    Logger.info('상품계산', '유효한 캐시 사용');
    return cached;
} else {
    Logger.warn('상품계산', '캐시 만료 (5분 초과)');
}
```

---

#### #6: 이벤트 배열 순서 불명확
**라인:** 831, 843-844, 912  
**현재 코드:**
```javascript
const events = currentData.events || [];
const completedEvents = events.filter(...);

// 어디서는 events[0], 어디서는 events[events.length-1]
const latestEvent = events[0];  // 라인 912
const oldestEvent = events[events.length - 1];  // 라인 843
```

**문제점:**
- 배열이 최신순인지 오래된순인지 불명확
- 코드 리뷰어도 헷갈림
- 정렬 순서 변경 시 버그 가능

**해결책:**
```javascript
// 배열 정렬 명확화
const events = currentData.events || [];
// events[0] = 가장 최신 (내림차순)
// events[length-1] = 가장 오래됨

// 또는 명시적 주석
const latestEvent = events[0];  // ✅ 가장 최신 이벤트 (내림차순)
const oldestEvent = events[events.length - 1];  // ✅ 가장 오래된 이벤트
```

---

#### #7: 날짜 포맷 불일치
**라인:** Multiple  
**현재 코드:**
```javascript
toLocaleString('ko-KR')  // "2026-08-17 15:XX:XX"
toISOString()  // "2026-08-17T15:XX:XXZ"
formatSafeDate()  // "2026년 8월 17일..."
```

**문제점:**
- 3가지 형식 혼용
- 비교/정렬/필터링 불가능
- 사용자 혼동

**해결책:**
```javascript
// ✅ 통일: 모든 내부 저장소는 ISO 8601
const DATE_FORMAT = 'ISO'; // "2026-08-17T15:XX:XXZ"
const DISPLAY_FORMAT = 'ko-KR'; // "2026-08-17 15:XX:XX"

function formatDate(date, format = DISPLAY_FORMAT) {
    const d = new Date(date);
    if (format === 'ISO') return d.toISOString();
    return d.toLocaleString('ko-KR');
}
```

---

#### #8: 에러 로깅이 너무 간결
**라인:** Multiple  
**현재 코드:**
```javascript
Logger.error('Phase26', '진행도 데이터 로드 실패', error.message);
// ❌ 스택 트레이스 없음 → 원인 불명
```

**문제점:**
- error.message만 출력
- 스택 트레이스 없음
- 어디서 에러가 났는지 모름

**해결책:**
```javascript
Logger.error('상품계산', '전체 상품 로드 실패', {
    message: error.message,
    stack: error.stack,  // ✅ 스택 트레이스
    url: './data/all_products.json',  // ✅ 실패한 URL
    status: error.status,  // HTTP 상태
    timestamp: new Date().toISOString()
});
```

---

#### #9: 메모리 누수 위험 (setInterval)
**라인:** 1084-1126  
**현재 코드:**
```javascript
setInterval(async () => {
    // 30초마다 데이터 갱신
    const newData = await loadRealData();
    if (newData) { ... }
}, 30000);
// ❌ 정지 불가능 → 탭 닫을 때까지 계속 실행
```

**문제점:**
- setInterval ID를 저장하지 않음
- 탭 닫을 때까지 백그라운드에서 계속 실행
- 네트워크 대역폭 낭비
- 배터리 소모

**해결책:**
```javascript
let refreshIntervalId = null;

function startRefresh() {
    if (refreshIntervalId) clearInterval(refreshIntervalId);
    refreshIntervalId = setInterval(async () => {
        const newData = await loadRealData();
        if (newData) updateWorkLog();
    }, REFRESH_INTERVAL);
    Logger.info('갱신', '30초 주기 갱신 시작');
}

function stopRefresh() {
    if (refreshIntervalId) {
        clearInterval(refreshIntervalId);
        refreshIntervalId = null;
        Logger.info('갱신', '갱신 중지');
    }
}

// 페이지 언로드 시 정지
window.addEventListener('beforeunload', stopRefresh);

// 사용
startRefresh();
```

---

#### #10: Race Condition 가능성
**라인:** 1084-1126, 990  
**현재 코드:**
```javascript
setInterval(async () => {
    const newData = await loadRealData();  // 비동기 대기
    if (newData) {
        currentData = newData;  // Race condition!
        updateWorkLog(newData);
    }
}, 30000);

// 동시에 초기화 함수도 loadRealData() 호출
async function initialize() {
    const realData = await loadRealData();  // 경쟁
    if (realData) {
        currentData = realData;
        updateWorkLog();
    }
}
```

**문제점:**
- initialize()와 setInterval이 동시에 실행
- currentData 덮어쓰기 충돌
- 일관성 없는 데이터 표시

**해결책:**
```javascript
class DataLock {
    constructor() {
        this.locked = false;
    }
    
    async acquire() {
        while (this.locked) {
            await new Promise(r => setTimeout(r, 10));
        }
        this.locked = true;
    }
    
    release() {
        this.locked = false;
    }
}

const dataLock = new DataLock();

async function loadDataSafely() {
    await dataLock.acquire();
    try {
        const data = await loadRealData();
        if (data) {
            APP_STATE.currentData = data;
            updateWorkLog(data);
        }
    } finally {
        dataLock.release();
    }
}
```

---

## 🛠️ 해결 우선순위 및 시간

| # | 문제 | 우선도 | 시간 | 총합 |
|---|------|--------|------|------|
| 1 | fetchWithTimeout 적용 | 🔴 Critical | 5분 | 5분 |
| 2 | console.log → Logger | 🟠 High | 3분 | 8분 |
| 3 | response.ok 강화 | 🟠 High | 5분 | 13분 |
| 4 | JSON.parse 예외처리 | 🟠 High | 3분 | 16분 |
| 5 | 캐시 TTL 추가 | 🟡 Medium | 4분 | 20분 |
| 6 | 배열 순서 문서화 | 🟡 Medium | 2분 | 22분 |
| 7 | 날짜 포맷 통일 | 🟡 Medium | 3분 | 25분 |
| 8 | 에러 로깅 강화 | 🟡 Medium | 3분 | 28분 |
| 9 | setInterval → 제어 | 🟡 Medium | 4분 | 32분 |
| 10 | Race condition 해결 | 🟡 Medium | 5분 | 37분 |

**총 해결 시간: ~37분**

---

## ✅ 다음 액션

1. **지금 당장:** Critical 1개 + High 3개 해결 (16분)
2. **이어서:** Medium 6개 해결 (21분)
3. **최종:** 테스트 및 GitHub 푸시

---

## 📊 누적 통계

| 카테고리 | 발견 | 해결 | 진행중 | 진행률 |
|---------|------|------|--------|--------|
| 처음 심도검토 | 35 | 15 | 8 | 43% |
| 사용자 피드백 | 3 | 3 | 0 | 100% |
| 새 문제 발굴 | 10 | 0 | 0 | 0% |
| **합계** | **48** | **18** | **8** | **38%** |

**목표:** 48/48 완벽 해결 (다음 2시간 내)
