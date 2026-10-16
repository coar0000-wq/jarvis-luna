# Uses only existing runtimes and standard libraries. No installs or network calls.
[CmdletBinding()]
param([string]$Python = 'python', [string]$Node = 'node')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$files = @((Join-Path $root 'run_local_analysis_tools.ps1'), (Join-Path $root 'embeddinggemma/run.ps1'), $PSCommandPath)
foreach ($file in $files) {
  $tokens = $null; $parseErrors = $null
  $null = [System.Management.Automation.Language.Parser]::ParseFile($file, [ref]$tokens, [ref]$parseErrors)
  if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
}
Write-Output 'PASS: three PowerShell ASTs'
$env:PYTHONDONTWRITEBYTECODE = '1'
& $Python -I -B (Join-Path $PSScriptRoot 'validate.py') $Node
if ($LASTEXITCODE -ne 0) { throw 'Source validation failed' }
Write-Output 'VALIDATION_PASSED'
