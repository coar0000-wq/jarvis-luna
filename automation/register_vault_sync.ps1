# Obsidian 볼트 자동 동기화를 Windows 작업 스케줄러에 등록한다.
# 관리자 권한 없이 현재 사용자 계정으로 등록된다.
#
#   PowerShell에서:  .\automation\register_vault_sync.ps1
#   해제:            Unregister-ScheduledTask -TaskName "JARVIS Obsidian Vault Sync"

$TaskName = "JARVIS Obsidian Vault Sync"
$Repo     = "C:\Users\Desktop\Claude\Projects\kms\jarvis-luna"
$Script   = Join-Path $Repo "automation\vault_sync.bat"

if (-not (Test-Path $Script)) {
    Write-Error "동기화 스크립트를 찾을 수 없습니다: $Script"
    exit 1
}

$action  = New-ScheduledTaskAction -Execute $Script -WorkingDirectory $Repo

# GitHub Actions가 매시 정각·30분에 노트를 올리므로 그 직후에 받아온다.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(5) `
           -RepetitionInterval (New-TimeSpan -Minutes 30)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "저장소의 obsidian/JARVIS_LUNA 볼트를 30분마다 GitHub과 동기화" | Out-Null

Write-Host "등록 완료: $TaskName (30분 간격)"
Write-Host "지금 바로 한 번 실행하려면:  Start-ScheduledTask -TaskName '$TaskName'"
