# Local-only JARVIS analysis bridge. Never installs software or calls a paid API.
[CmdletBinding()]
param(
  [Parameter(Mandatory)][ValidateSet('briefing','doctor','providers','inspect','function','mcp','embedding-smoke','embedding-search')][string]$Mode,
  [string]$ToolsRoot = $env:JARVIS_LOCAL_TOOLS_ROOT,
  [string]$Target,
  [string]$Procedure,
  [string]$Query,
  [string]$Documents,
  [ValidateSet(768,256)][int]$Dimension = 256,
  [switch]$CodeQuery,
  [switch]$AuthorizedTarget
)
$ErrorActionPreference = 'Stop'
if ($Mode -eq 'briefing') {
  $briefPath = Join-Path $PSScriptRoot '../data/agents/rea_document_handoff.json'
  Get-Content -LiteralPath $briefPath -Raw -Encoding utf8
  exit 0
}
if ([string]::IsNullOrWhiteSpace($ToolsRoot)) { throw 'Set JARVIS_LOCAL_TOOLS_ROOT to the verified persistent local installation.' }
$configPath = Join-Path $ToolsRoot 'config.local.json'
if (!(Test-Path -LiteralPath $configPath -PathType Leaf)) { throw 'Verified local tool config missing. Hosted Actions do not have desktop tools.' }
$config = Get-Content -LiteralPath $configPath -Raw -Encoding utf8 | ConvertFrom-Json
if ($Mode -in @('inspect','function')) {
  if (!$AuthorizedTarget) { throw 'Explicit -AuthorizedTarget is required for an owned or authorized local binary.' }
  if ([string]::IsNullOrWhiteSpace($Target) -or !(Test-Path -LiteralPath $Target -PathType Leaf)) { throw 'Select one existing authorized target file.' }
  $Target = (Resolve-Path -LiteralPath $Target).Path
}
if ($Mode -eq 'embedding-smoke') {
  & (Join-Path $ToolsRoot 'embeddinggemma\run.ps1')
  exit $LASTEXITCODE
}
if ($Mode -eq 'embedding-search') {
  if ([string]::IsNullOrWhiteSpace($Query) -or [string]::IsNullOrWhiteSpace($Documents) -or !(Test-Path -LiteralPath $Documents -PathType Leaf)) { throw 'Supply -Query and one explicitly selected -Documents JSON file.' }
  $embeddingRoot = Join-Path $ToolsRoot 'embeddinggemma'
  foreach ($variable in @('PIP_PREFIX','PIP_TARGET','PYTHONPATH','VIRTUAL_ENV')) { Remove-Item "Env:$variable" -ErrorAction SilentlyContinue }
  $env:TEMP = $config.temp; $env:TMP = $config.temp
  $searchArguments = @((Join-Path $embeddingRoot 'search.py'),'--query',$Query,'--documents-json',(Resolve-Path -LiteralPath $Documents).Path,'--dimension',$Dimension)
  if ($CodeQuery) { $searchArguments += '--code' }
  & (Join-Path $embeddingRoot '.venv\Scripts\python.exe') @searchArguments
  exit $LASTEXITCODE
}
foreach ($file in @($config.node, $config.rea_entry)) {
  if (!(Test-Path -LiteralPath $file -PathType Leaf)) { throw "Installed runtime missing: $file" }
}
$env:GHIDRA_INSTALL_DIR = $config.ghidra
$env:JAVA_HOME = $config.java_home
$env:REA_ANALYSIS_PROVIDER = 'ghidra'
$env:GHIDRA_HEADLESS_MAXMEM = '512M'
$env:TEMP = $config.temp
$env:TMP = $config.temp
$env:REA_MCP_INPUT_SCHEMA_PROFILE = 'compact'
switch ($Mode) {
  'doctor'   { $reaArguments = @('doctor','--provider','ghidra','--format','json') }
  'providers'{ $reaArguments = @('providers','--format','json') }
  'inspect'  { $reaArguments = @('inspect',$Target,'--provider','ghidra','--format','json') }
  'function' {
    if ([string]::IsNullOrWhiteSpace($Procedure)) { throw 'Supply -Procedure.' }
    $reaArguments = @('function',$Target,$Procedure,'--provider','ghidra','--format','json')
  }
  'mcp' { $reaArguments = @('mcp') }
}
& $config.node $config.rea_entry @reaArguments
exit $LASTEXITCODE
