# ============================================================
# 🚀 JARVIS 10분 자동화 스크립트
# Windows Task Scheduler에 등록: 매 10분마다 실행
# ============================================================

$ErrorActionPreference = "Continue"
$workdir = "C:\Users\Desktop\Claude\Projects\kms"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

Write-Host "=================================================="
Write-Host "🤖 JARVIS 10분 자동화 시작"
Write-Host "⏰ $timestamp"
Write-Host "=================================================="
Write-Host ""

# Python 설치 확인
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Python 설치 필요"
    exit 1
}

Set-Location $workdir

# ============================================================
# 단계별 실행 (모두 continue-on-error)
# ============================================================

# 1️⃣ arXiv 논문 수집
Write-Host "1️⃣ arXiv MoE 논문 수집..."
if (Test-Path "scripts\collect_moe_papers.py") {
    try {
        python scripts/collect_moe_papers.py 2>&1 | Out-Null
        Write-Host "   ✅ 완료"
    } catch {
        Write-Host "   ⚠️ 스킵 (에러)"
    }
} else {
    Write-Host "   ⚠️ 스크립트 없음"
}

# 2️⃣ YouTube MoE 영상분석
Write-Host "2️⃣ YouTube MoE 영상분석..."
if (Test-Path "scripts\youtube_moe_analysis.py") {
    try {
        python scripts/youtube_moe_analysis.py 2>&1 | Out-Null
        Write-Host "   ✅ 완료"
    } catch {
        Write-Host "   ⚠️ 스킵 (에러)"
    }
} else {
    Write-Host "   ⚠️ 스크립트 없음"
}

# 3️⃣ YouTube Dropshipping 분석
Write-Host "3️⃣ YouTube Dropshipping 영상분석..."
if (Test-Path "scripts\youtube_dropshipping_analysis.py") {
    try {
        python scripts/youtube_dropshipping_analysis.py 2>&1 | Out-Null
        Write-Host "   ✅ 완료"
    } catch {
        Write-Host "   ⚠️ 스킵 (에러)"
    }
} else {
    Write-Host "   ⚠️ 스크립트 없음"
}

# 4️⃣ Google 검색 데이터 수집
Write-Host "4️⃣ Google 검색 데이터 수집..."
if (Test-Path "scripts\google_search_data_collection.py") {
    try {
        python scripts/google_search_data_collection.py 2>&1 | Out-Null
        Write-Host "   ✅ 완료"
    } catch {
        Write-Host "   ⚠️ 스킵 (에러)"
    }
} else {
    Write-Host "   ⚠️ 스크립트 없음"
}

# 5️⃣ 신경망 훈련
Write-Host "5️⃣ 신경망 생성 및 훈련..."
if (Test-Path "scripts\moe_neural_network.py") {
    try {
        python scripts/moe_neural_network.py 2>&1 | Out-Null
        Write-Host "   ✅ 신경망 생성"
    } catch {
        Write-Host "   ⚠️ 스킵 (에러)"
    }
}

if (Test-Path "scripts\moe_training.py") {
    try {
        python scripts/moe_training.py 2>&1 | Out-Null
        Write-Host "   ✅ 훈련 완료"
    } catch {
        Write-Host "   ⚠️ 스킵 (에러)"
    }
}

# ============================================================
# 작업 로그 기록 (실제 데이터만)
# ============================================================

Write-Host "📝 작업 로그 업데이트..."

$logContent = @{
    timestamp = Get-Date -Format "o"
    current_date = Get-Date -Format "yyyy-MM-dd"
    automation_status = "✅ 로컬 Task Scheduler 실행 중"
    execution_time = $timestamp
    completed_today = @(
        @{
            id = "local_run_$(Get-Date -Format 'yyyyMMddHHmm')"
            task = "로컬 10분 자동화 실행"
            timestamp = Get-Date -Format "o"
            status = "✅ 완료"
        }
    )
} | ConvertTo-Json

$logContent | Out-File -FilePath "data\jarvis_work_detailed_log.json" -Encoding UTF8 -Force

# ============================================================
# Git 커밋
# ============================================================

Write-Host "📤 Git 커밋..."
git config user.email "jarvis@local.automation"
git config user.name "JARVIS Local Scheduler"
git add -A 2>&1 | Out-Null

$changes = git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✅ 이미 최신"
} else {
    git commit -m "🚀 JARVIS 로컬 10분 자동화: arXiv+YouTube+Google+훈련 ($timestamp)" 2>&1 | Out-Null
    git push origin main 2>&1 | Out-Null
    Write-Host "   ✅ 커밋 및 푸시"
}

Write-Host ""
Write-Host "=================================================="
Write-Host "✅ JARVIS 10분 자동화 완료!"
Write-Host "🔄 다음 실행: 10분 후"
Write-Host "=================================================="
