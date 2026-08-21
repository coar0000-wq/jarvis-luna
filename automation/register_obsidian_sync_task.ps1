param(
    [string]$TaskName = "JARVIS LUNA Obsidian GitHub Sync",
    [int]$IntervalMinutes = 5
)

$ErrorActionPreference = "Stop"
$ScriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunnerPath = Join-Path $ScriptDirectory "run_obsidian_sync.bat"
$ConfigPath = Join-Path $ScriptDirectory "obsidian_sync_config.json"

if ($IntervalMinutes -lt 5) {
    throw "The synchronization interval must be at least 5 minutes."
}
if (-not (Test-Path $RunnerPath)) {
    throw "Runner file not found: $RunnerPath"
}
if (-not (Test-Path $ConfigPath)) {
    throw "Configuration file not found: $ConfigPath"
}

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$RunnerPath`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
$description = "Synchronizes the JARVIS_LUNA Obsidian workspace with GitHub every $IntervalMinutes minutes."

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description $description -User $env:USERNAME -RunLevel Limited -Force | Out-Null

Write-Host "Scheduled task registered: $TaskName"
Write-Host "Synchronization interval: $IntervalMinutes minutes"
Write-Host "Check status: Get-ScheduledTask -TaskName `"$TaskName`""
