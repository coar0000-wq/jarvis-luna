param(
    [string]$TaskName = "JARVIS LUNA Obsidian GitHub Sync",
    [int]$IntervalMinutes = 5
)

$ErrorActionPreference = "Stop"
$ScriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunnerPath = Join-Path $ScriptDirectory "run_obsidian_sync.bat"
$ConfigPath = Join-Path $ScriptDirectory "obsidian_sync_config.json"

if ($IntervalMinutes -lt 5) {
    throw "동기화 간격은 5분 이상으로 설정하세요."
}
if (-not (Test-Path $RunnerPath)) {
    throw "실행 파일을 찾을 수 없습니다: $RunnerPath"
}
if (-not (Test-Path $ConfigPath)) {
    throw "설정 파일을 찾을 수 없습니다: $ConfigPath`n예제 설정 파일을 복사하고 vault_path를 실제 경로로 바꾼 뒤 다시 실행하세요."
}

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$RunnerPath`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
$description = "Synchronizes the JARVIS_LUNA Obsidian workspace with GitHub every $IntervalMinutes minutes."

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description $description -User $env:USERNAME -RunLevel Limited -Force | Out-Null

Write-Host "작업 스케줄러 등록 완료: $TaskName"
Write-Host "실행 간격: $IntervalMinutes 분"
Write-Host "현재 상태 확인: Get-ScheduledTask -TaskName `"$TaskName`""
