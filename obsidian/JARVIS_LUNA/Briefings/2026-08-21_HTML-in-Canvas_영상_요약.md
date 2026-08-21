# HTML-in-Canvas 영상 요약

- **분석 대상:** [YouTube 영상](https://www.youtube.com/watch?v=8ucoskmA1yg)
- **관련 시스템:** JARVIS-LUNA
- **분류:** 기술 동향 · 몰입형 웹 · 프론트엔드 실험
- **작성일:** 2026-08-21
- **상태:** 검토 완료 · PoC 후보

## 한 줄 요약

Chrome의 HTML-in-Canvas API는 실제 HTML 요소의 DOM 상호작용성과 접근성을 유지하면서 2D Canvas·WebGL·WebGPU 장면 안에 HTML UI를 배치하려는 실험 기술이다.

## 영상 핵심

영상은 3D 공간에 HTML 폼과 컨트롤을 배치하고, 젤리·픽셀 왜곡·셰이더·글로우 같은 효과를 적용하는 데모를 보여준다. 기존 Canvas는 강력한 그래픽 표현이 가능하지만 텍스트 선택, 입력 폼, 키보드 조작, 접근성, 반응형 처리를 직접 구현해야 한다는 문제가 있다.

HTML-in-Canvas는 이 문제를 DOM과 Canvas의 결합으로 해결하려 한다. 주요 구성은 `layoutsubtree`, `drawElementImage()`, WebGL의 `texElementImage2D`, WebGPU의 `copyElementImageToTexture`, 그리고 변경 내용을 다시 그리는 `paint` 이벤트다.

## JARVIS-LUNA에 주는 의미

JARVIS-LUNA의 운영 화면 전체를 Canvas로 바꿀 필요는 없다. Live Briefing, 프로젝트 진행도, 매출 지표, 팀별 상태와 법무 정보는 검색·복사·접근성·모바일 가독성이 중요하므로 기존 HTML/CSS가 우선이다.

대신 MD Family의 브랜드 경험을 높이는 별도 실험 영역에 적용한다. 가장 적합한 후보는 `Immersive Intelligence Lab`, Hero 배경 그래프, 시장 분석 노드 시각화, 상품 카드 호버 효과, 전략 보고서의 3D 매출 추이다.

## 즉시 실행할 판단

| 항목 | 판단 |
|---|---|
| 공개 대시보드 전체 변환 | 보류 |
| 별도 실험 페이지 | 진행 후보 |
| Hero의 그래프·빛 효과 | 1차 PoC 후보 |
| 시장 분석 노드 시각화 | 2차 PoC 후보 |
| 모바일 처리 | 기존 HTML/CSS 정적 폴백 필수 |
| 운영 의존성 | 실험 API에 의존하지 않음 |

## 검증 체크리스트

- Chrome Canary·Origin Trial 외 브라우저에서 정상 폴백되는가
- 데스크톱 30fps 이상을 유지하는가
- 모바일에서 프레임 저하·발열·배터리 소모가 없는가
- DOM 요소가 키보드·스크린 리더·텍스트 선택으로 접근되는가
- 실제 DOM 위치와 Canvas에 그려진 위치가 정확히 일치하는가
- API 변경 시 기존 대시보드가 영향을 받지 않는가

## 다음 5일 액션

1. `Immersive Intelligence Lab` 페이지의 정적 HTML/CSS 기본 화면을 설계한다.
2. HTML-in-Canvas 지원 여부를 확인하는 기능 감지 코드를 추가한다.
3. 지원 환경에서만 Hero 그래프·빛 효과를 활성화한다.
4. 지원되지 않는 환경에서는 동일한 정보의 정적 Hero를 표시한다.
5. 프레임률·입력 지연·접근성·모바일 성능을 비교 기록한다.
6. 검증 결과를 다음 전략 보고서의 `Immersive Web PoC` 항목으로 기록한다.

## 핵심 결론

HTML-in-Canvas는 JARVIS-LUNA 운영 안정성을 직접 높이는 알고리즘이라기보다, MD Family의 차세대 인터랙티브 브랜드 경험을 만들 수 있는 선행기술이다. 따라서 **운영 정보는 DOM으로 유지하고, 시각 효과만 선택적으로 Canvas/WebGL/WebGPU로 확장하는 하이브리드 전략**이 가장 적절하다.

## 참고 자료

[1]: https://developer.chrome.com/blog/html-in-canvas-origin-trial "Chrome for Developers — Introducing the HTML-in-Canvas API origin trial"
[2]: https://github.com/WICG/html-in-canvas "WICG — HTML-in-Canvas proposal"
[3]: https://chromestatus.com/feature/5172548013916160 "ChromeStatus — HTML-in-canvas feature status"
