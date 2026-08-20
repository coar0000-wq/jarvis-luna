<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JARVIS LUNA - AGI Evolution OS</title>
    <style>
        :root {
            --bg-color: #0d0d15;
            --panel-bg: #1e1e2f;
            --border-color: #3a3a5c;
            --text-main: #ffffff;
            --text-sub: #b8b8d1;
            --accent-blue: #00d2ff;
            --accent-orange: #ff9f43;
            --accent-green: #10ac84;
        }
        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 15px;
            margin-bottom: 25px;
        }
        h1 { margin: 0; font-size: 24px; color: var(--accent-blue); }
        .status-badge { background: #2a2a40; padding: 6px 12px; border-radius: 20px; font-size: 13px; border: 1px solid var(--border-color); }
        .grid-container {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        .card {
            background: var(--panel-bg);
            padding: 20px;
            border-radius: 12px;
            border: 1px solid var(--border-color);
        }
        .full-width { grid-column: span 2; }
        h3 { margin-top: 0; font-size: 18px; }
        ul { padding-left: 20px; font-size: 14px; line-height: 1.6; color: var(--text-sub); }
        .terminal {
            background: #0d0d15;
            font-family: monospace;
            font-size: 12px;
            padding: 12px;
            border-radius: 8px;
            height: 130px;
            overflow-y: auto;
            color: var(--accent-green);
            line-height: 1.5;
            border: 1px solid var(--border-color);
        }
        .chart-box {
            background: #2a2a40;
            height: 130px;
            border-radius: 8px;
            display: flex;
            align-items: flex-end;
            justify-content: space-around;
            padding: 10px;
        }
        .bar {
            width: 25%;
            border-radius: 4px;
            text-align: center;
            font-size: 11px;
            padding-top: 5px;
            color: #fff;
            font-weight: bold;
        }
        @media (max-width: 768px) {
            .grid-container { grid-template-columns: 1fr; }
            .full-width { grid-column: span 1; }
        }
    </style>
</head>
<body>

    <header>
        <h1>JARVIS LUNA - AGI Evolution OS</h1>
        <div class="status-badge">🟢 도현 (CEO) 감시중 | GitHub Actions 활성 | Obsidian 온라인</div>
    </header>

    <div class="grid-container">

        <!-- 3번: 현재 진행 중인 AGI / Phase 27 핵심 목표 요약 박스 -->
        <div class="card full-width">
            <h3 style="color: var(--accent-blue);">🎯 Phase 27 AGI & Neural-Symbolic Evolution Target</h3>
            <p style="font-size: 14px; color: var(--text-sub);">현재 도현 CEO와 자비스가 긴밀하게 실행 중인 핵심 마일스톤 및 자율 진화 현황입니다.</p>
            <ul>
                <li><b>Step 1 데이터셋 확보 & 자동화:</b> 의료/신경망 데이터 세트 구축 완료 및 검증 파이프라인 가동</li>
                <li><b>Step 2 신경망 코드 설계:</b> Neuro-Symbolic 하이브리드 아키텍처 구현 및 GitHub 자동 동기화 연동</li>
                <li><b>실시간 동기화 체계:</b> 로컬 Obsidian 노트와 GitHub 간 10분 주기 클라우드 자동화 구축 완료</li>
            </ul>
        </div>

        <!-- 2번: 트렌드 및 상품 증가 추이 미니 위젯 -->
        <div class="card">
            <h3 style="color: var(--accent-orange);">📈 다이소 / Shopify 수집 트렌드</h3>
            <p style="font-size: 13px; color: var(--text-sub);">최근 실시간 상품 발굴 및 누적 데이터 증가 추세</p>
            <div class="chart-box">
                <div class="bar" style="background: var(--accent-orange); height: 40%;">D-2<br>95개</div>
                <div class="bar" style="background: var(--accent-orange); height: 75%;">D-1<br>110개</div>
                <div class="bar" style="background: var(--accent-blue); height: 100%;">TODAY<br>118개</div>
            </div>
        </div>

        <!-- 1번: 실시간 AI 자율 에이전트 로그 스트림 -->
        <div class="card">
            <h3 style="color: var(--accent-green);">🤖 자비스 라이브 에이전트 로그</h3>
            <div class="terminal" id="terminal-log">
                [SYSTEM] 🟢 안전성 검증 및 에러 핸들링 로직 활성화<br>
                [19:02] 🟢 GitHub Actions 10분 주기 자동화 완료<br>
                [19:01] 🔄 Obsidian 로컬 노트 및 코어 파일 동기화 성공<br>
                [19:00] 🧠 Phase 27 신경망 아키텍처 세부 설계 패치 적용<br>
                [18:50] 🛒 Shopify 다이소 상품 수집 (총 118개 확정)
            </div>
        </div>

    </div>

    <script>
        // 안정성 및 디버그 로거 설정 (심도 검토 보고서 반영)
        const DEBUG_MODE = false;
        const Logger = {
            info: (tag, msg) => { if (DEBUG_MODE) console.log(`[${tag}] ${msg}`); }
        };
        Logger.info("JARVIS", "Dashboard UI initialized successfully.");
    </script>
</body>
</html>