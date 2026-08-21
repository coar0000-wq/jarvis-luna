# ============================================================
# Windows Task Scheduler 자동 등록
# 매 10분마다 JARVIS 자동화 실행
# ============================================================

Write-Host "=================================================="
Write-Host "⚙️ Task Scheduler 등록 시작"
Write-Host "=================================================="
Write-Host ""

$scriptPath = "C:\Users\Desktop\Claude\Projects\kms\run_jarvis_10min.ps1"
$taskName = "JARVIS_Automation_10min"
$taskPath = "\" + $taskName

# 기존 작업 제거 (있다면)
Write-Host "기존 작업 확인..."
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Write-Host "기존 작업 제거 중..."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Start-Sleep -Seconds 2
    Write-Host "✅ 제거됨"
} else {
    Write-Host "기존 작업 없음"
}

Write-Host ""
Write-Host "새 작업 등록 중..."

# PowerShell 실행 정책 설정
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`""

# 매 10분마다 실행
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration (New-TimeSpan -Days 365)

# 작업 설정
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

# 작업 등록
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings `
    -Description "JARVIS 10분 자동화: arXiv+YouTube+Google+훈련"

Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null

Write-Host "✅ 작업 등록됨"
Write-Host ""

# 확인
$task = Get-ScheduledTask -TaskName $taskName
Write-Host "📋 작업 상세:"
Write-Host "  • 이름: $($task.TaskName)"
Write-Host "  • 상태: $($task.State)"
Write-Host "  • 다음 실행: $($task.Triggers[0].StartBoundary)"
Write-Host "  • 반복: 10분마다"
Write-Host ""

Write-Host "=================================================="
Write-Host "✅ 완료! JARVIS가 매 10분마다 자동 실행됩니다"
Write-Host "=================================================="
