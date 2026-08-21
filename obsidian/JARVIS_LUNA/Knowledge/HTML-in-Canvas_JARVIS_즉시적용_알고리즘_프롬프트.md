# HTML-in-Canvas — JARVIS-LUNA 즉시 적용 알고리즘·프롬프트

- **출처:** [YouTube 영상](https://www.youtube.com/watch?v=8ucoskmA1yg)
- **주제:** Chrome HTML-in-Canvas 실험 API
- **적용 대상:** JARVIS-LUNA Hero·시장 분석·상품 발굴·전략 보고서 실험 기능
- **상태:** 연구·PoC용. 운영 대시보드 전체 적용은 보류.

## 1. 핵심 판단

HTML-in-Canvas는 실제 HTML 요소의 DOM 상호작용성과 Canvas/WebGL/WebGPU의 시각 효과를 결합하는 기술이다. 현재 JARVIS-LUNA 운영 화면 전체에 적용하지 않고, 별도 `Immersive Intelligence Lab` 또는 Hero 실험 영역에서만 검증한다.

기본 운영 화면은 접근성·모바일 호환성·브라우저 지원을 위해 기존 HTML/CSS를 유지한다. 실험 브라우저가 API를 지원하지 않으면 자동으로 기존 HTML/CSS 화면을 보여주는 폴백을 필수로 둔다.

## 2. 즉시 적용 알고리즘

### 2.1 지원 여부 확인 및 폴백

```javascript
function canUseHtmlInCanvas() {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  return Boolean(
    canvas.layoutSubtree !== undefined &&
    ctx && typeof ctx.drawElementImage === 'function'
  );
}

function chooseExperience() {
  const lab = document.querySelector('#immersive-intelligence-lab');
  if (!lab) return;
  lab.dataset.mode = canUseHtmlInCanvas() ? 'experimental' : 'standard';
}
```

**원칙:** 지원되지 않는 브라우저에서 오류를 만들지 않는다. `standard` 모드는 현재 JARVIS-LUNA HTML/CSS 카드와 동일한 정보를 제공해야 한다.

### 2.2 DOM·Canvas 동기화 파이프라인

```text
1. 실제 HTML 요소를 DOM에 만든다.
2. canvas에 layoutsubtree를 설정한다.
3. 캔버스 픽셀 크기를 devicePixelRatio에 맞춘다.
4. paint 이벤트에서 HTML 요소를 캔버스에 그린다.
5. 반환된 DOMMatrix를 실제 HTML 요소의 CSS transform에 적용한다.
6. 포커스·입력·호버·텍스트 변경 시 다시 paint한다.
7. 실패·저성능·미지원 환경이면 standard HTML/CSS로 전환한다.
```

### 2.3 JARVIS-LUNA용 상태 모델

```javascript
const immersiveState = {
  mode: 'standard',
  browserSupport: false,
  performance: { fps: 0, frameTimeMs: 0, memoryWarning: false },
  accessibility: { domVisible: true, keyboardTested: false },
  fallbackReason: null,
};

function shouldFallback(state) {
  return !state.browserSupport ||
    state.performance.fps < 30 ||
    state.performance.frameTimeMs > 33 ||
    state.performance.memoryWarning ||
    !state.accessibility.domVisible;
}
```

**운영 기준:** 30fps 미만, 프레임 처리 33ms 초과, 모바일 발열·메모리 경고, 키보드 접근성 실패가 발생하면 즉시 정적 HTML/CSS 화면으로 돌아간다.

### 2.4 JARVIS-LUNA 적용 우선순위

| 우선순위 | 영역 | 적용 방식 | 운영 화면 영향 |
|---:|---|---|---|
| 1 | 별도 Immersive Intelligence Lab | HTML 카드와 3D 효과를 분리 검증 | 없음 |
| 2 | Hero 배경 | 그래프·빛·입자 효과만 Canvas로 실험 | 기존 텍스트·상태등 유지 |
| 3 | 시장 분석 | 노드·관계선만 WebGL로 시각화 | 실제 라벨·링크는 DOM 유지 |
| 4 | 상품 발굴 | 제품 카드 호버·확장 효과 | 모바일에서는 정적 카드 |
| 5 | 전략 보고서 | 매출 추이의 3D 표현 실험 | 기존 숫자·표를 폴백으로 유지 |

## 3. JARVIS 운영용 프롬프트

### 3.1 기술 검토 프롬프트

```text
너는 JARVIS-LUNA의 프론트엔드 실험 기술 검토자다.
HTML-in-Canvas 기능을 운영 대시보드에 적용할 때 다음 순서로 검토하라.

1. 현재 브라우저와 기기에서 지원 여부를 판정한다.
2. 지원되지 않으면 기존 HTML/CSS 화면을 유지한다.
3. 지원되면 DOM 상호작용성, 키보드 탐색, 스크린 리더 노출, 텍스트 선택을 점검한다.
4. 프레임률, 입력 지연, 메모리, 모바일 발열을 측정한다.
5. 기준을 통과한 경우에만 실험 효과를 활성화한다.
6. 결과를 지원 여부, 성능, 접근성, 폴백 필요성, 다음 액션 순서로 보고한다.

확인할 수 없는 값은 추정하지 말고 '측정 필요'라고 표시하라.
```

### 3.2 시장 분석 프롬프트

```text
JARVIS-LUNA 시장 분석팀으로서 HTML-in-Canvas와 몰입형 웹 경험의 사업 기회를 분석하라.

분석 항목:
- 어떤 고객군이 3D·WebGL·WebGPU 기반 웹 경험에 비용을 지불하는가
- 브랜드 사이트, 인터랙티브 전시, 웹 게임, 교육, 데이터 시각화 중 우선 시장은 무엇인가
- 고객이 기존 HTML/CSS 제작보다 추가 비용을 지불할 이유는 무엇인가
- 브라우저 호환성·성능·접근성 리스크는 무엇인가
- 2주 안에 검증 가능한 최소 PoC는 무엇인가

결과는 고객군, 문제, 제안 가치, 구현 난도, 예상 검증 지표, 리스크, 추천 우선순위 표로 작성하라.
근거가 없는 시장 규모나 매출 수치는 만들어내지 말고 데이터 부족으로 표시하라.
```

### 3.3 상품 발굴 프롬프트

```text
JARVIS-LUNA 상품 발굴팀으로서 HTML-in-Canvas 생태계에서 판매·제휴·템플릿화 가능한 상품을 찾아라.

후보 범위:
- 인터랙티브 웹 템플릿
- WebGL/WebGPU 셰이더 라이브러리
- HTML-in-Canvas UI 키트
- 3D 브랜드 랜딩페이지 패키지
- 데이터 시각화 컴포넌트
- 성능·접근성 테스트 도구

각 후보에 대해 고객, 사용 상황, 차별성, 구현에 필요한 기술, 브라우저 위험, 재사용성, 판매 가능성을 평가하라.
단순히 화려한 효과가 아니라 반복적으로 판매 가능한 문제 해결 제품을 우선하라.
```

### 3.4 전략 보고서 프롬프트

```text
최근 5일 동안 수집된 HTML-in-Canvas 관련 자료를 전략 보고서로 정리하라.

보고서 구조:
1. 새로 확인된 기술 변화
2. JARVIS-LUNA에 즉시 적용 가능한 항목
3. 별도 PoC가 필요한 항목
4. 적용하지 말아야 할 항목과 이유
5. 검증 지표: 프레임률, 입력 지연, 모바일 성능, 접근성, 브라우저 호환성
6. 다음 5일의 실행 계획

운영 화면의 안정성을 훼손하는 제안은 제외하고, 표준 HTML/CSS 폴백이 있는 실험만 추천하라.
```

## 4. 적용하지 않을 것

현재 공개 대시보드 전체를 Canvas로 변환하지 않는다. Live Briefing 텍스트, 프로젝트 진행도, 팀별 상태, 매출 숫자, 법무 안내는 검색·복사·접근성·모바일 가독성이 중요하므로 일반 DOM으로 유지한다.

또한 HTML-in-Canvas API를 일반 브라우저 전체에서 사용할 수 있다고 가정하지 않는다. 공식 자료상 API는 아직 실험·Origin Trial·개발 중인 사양 단계이므로, 운영 기능의 필수 의존성으로 만들지 않는다.[1] [2]

## 5. 다음 실행 작업

| 순서 | 작업 | 완료 기준 |
|---:|---|---|
| 1 | `Immersive Intelligence Lab` 별도 데모 구성 | 기존 대시보드에 영향 없이 열림 |
| 2 | Hero 그래프·빛 효과 PoC | 데스크톱에서 30fps 이상 |
| 3 | 모바일 정적 폴백 구현 | 모바일에서 동일 정보 접근 가능 |
| 4 | 키보드·스크린 리더 테스트 | DOM 요소 탐색·입력 가능 |
| 5 | 성능 비교 기록 | 표준 모드와 실험 모드의 차이 기록 |

## 참고 자료

[1]: https://developer.chrome.com/blog/html-in-canvas-origin-trial "Chrome for Developers — Introducing the HTML-in-Canvas API origin trial"
[2]: https://github.com/WICG/html-in-canvas "WICG — HTML-in-Canvas proposal"
[3]: https://chromestatus.com/feature/5172548013916160 "ChromeStatus — HTML-in-canvas feature status"
