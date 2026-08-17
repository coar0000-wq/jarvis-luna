# Windows Task Scheduler에 JARVIS 자동화 등록

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "🤖 Windows Task Scheduler 자동 작업 등록" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# 현재 디렉토리
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$startBatPath = Join-Path $scriptPath "start_automation.bat"
$schedulerPyPath = Join-Path $scriptPath "create_scheduler.py"

# 관리자 권한 확인
$isAdmin = [Security.Principal.WindowsIdentity]::GetCurrent().Groups -contains `
  [Security.Principal.SecurityIdentifier]"S-1-5-32-544"

if (-not $isAdmin) {
    Write-Host "❌ 관리자 권한이 필요합니다!" -ForegroundColor Red
    Write-Host ""
    Write-Host "이 스크립트를 다시 실행하세요:" -ForegroundColor Yellow
    Write-Host "   1. PowerShell을 마우스 오른쪽 버튼으로 클릭" -ForegroundColor White
    Write-Host "   2. '관리자로 실행' 클릭" -ForegroundColor White
    Write-Host "   3. 다음 명령어 입력:" -ForegroundColor White
    Write-Host "      Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process" -ForegroundColor White
    Write-Host "      .\register_task.ps1" -ForegroundColor White
    exit 1
}

# 작업 1: 부팅 시 JARVIS 자동 시작
Write-Host "1️⃣ 부팅 시 JARVIS 자동 시작 등록..." -ForegroundColor Yellow

$taskName = "JARVIS-Auto-Start"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -File '$startBatPath'"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable

try {
    # 기존 작업 제거
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null

    # 새 작업 등록
    Register-ScheduledTask -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -RunLevel Highest | Out-Null

    Write-Host "✅ 부팅 시작 작업 등록 완료" -ForegroundColor Green
} catch {
    Write-Host "❌ 등록 실패: $_" -ForegroundColor Red
}

# 작업 2: 로그인 시 Python 스케줄러 시작
Write-Host ""
Write-Host "2️⃣ 로그인 시 JARVIS 스케줄러 시작 등록..." -ForegroundColor Yellow

$taskName2 = "JARVIS-Scheduler"
$pythonExe = (Get-Command python).Source
$action2 = New-ScheduledTaskAction -Execute $pythonExe `
    -Argument "`"$schedulerPyPath`"" `
    -WorkingDirectory $scriptPath
$trigger2 = New-ScheduledTaskTrigger -AtLogOn
$settings2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable -IdleDuration (New-TimeSpan -Minutes 5)

try {
    # 기존 작업 제거
    Unregister-ScheduledTask -TaskName $taskName2 -Confirm:$false -ErrorAction SilentlyContinue | Out-Null

    # 새 작업 등록
    Register-ScheduledTask -TaskName $taskName2 `
        -Action $action2 `
        -Trigger $trigger2 `
        -Settings $settings2 `
        -RunLevel Highest | Out-Null

    Write-Host "✅ 로그인 시작 작업 등록 완료" -ForegroundColor Green
} catch {
    Write-Host "❌ 등록 실패: $_" -ForegroundColor Red
}

# 작업 3: 매일 09:00에 Obsidian 서버 재시작
Write-Host ""
Write-Host "3️⃣ 일일 정기 점검 작업 등록 (매일 09:00 KST)..." -ForegroundColor Yellow

$taskName3 = "JARVIS-Daily-Maintenance"
$action3 = New-ScheduledTaskAction -Execute $pythonExe `
    -Argument "`"$schedulerPyPath`"" `
    -WorkingDirectory $scriptPath
$trigger3 = New-ScheduledTaskTrigger -Daily -At 09:00AM
$settings3 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable

try {
    # 기존 작업 제거
    Unregister-ScheduledTask -TaskName $taskName3 -Confirm:$false -ErrorAction SilentlyContinue | Out-Null

    # 새 작업 등록
    Register-ScheduledTask -TaskName $taskName3 `
        -Action $action3 `
        -Trigger $trigger3 `
        -Settings $settings3 `
        -RunLevel Highest | Out-Null

    Write-Host "✅ 일일 정기 점검 작업 등록 완료" -ForegroundColor Green
} catch {
    Write-Host "❌ 등록 실패: $_" -ForegroundColor Red
}

# 확인
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "📋 등록된 작업 목록:" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

Get-ScheduledTask -TaskName "JARVIS-*" | Select-Object TaskName, State, @{N="NextRun";E={$_.Triggers.StartBoundary}} | Format-Table -AutoSize

Write-Host ""
Write-Host "✅ 모든 자동화 작업 등록 완료!" -ForegroundColor Green
Write-Host ""
Write-Host "🎯 설정 내용:" -ForegroundColor Cyan
Write-Host "   1️⃣ 부팅 시: JARVIS 자동화 시스템 시작" -ForegroundColor White
Write-Host "   2️⃣ 로그인 시: Python 스케줄러 시작" -ForegroundColor White
Write-Host "      - 매 10분: 다이소 상품 발굴" -ForegroundColor White
Write-Host "      - 매 15분: Obsidian 서버 모니터링 & 자동 재시작" -ForegroundColor White
Write-Host "   3️⃣ 매일 09:00 KST: 정기 점검 및 Obsidian 재시작" -ForegroundColor White
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
