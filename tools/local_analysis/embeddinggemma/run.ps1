$ErrorActionPreference='Stop'
$root=$PSScriptRoot
'PIP_PREFIX','PIP_TARGET','PYTHONPATH','VIRTUAL_ENV' | ForEach-Object { Remove-Item "Env:$_" -ErrorAction SilentlyContinue }
$env:TEMP=Join-Path $root 'tmp'
$env:TMP=$env:TEMP
$env:HF_HOME=Join-Path $root 'hf-cache'
$env:TORCH_HOME=Join-Path $root 'torch-cache'
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
& (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $root 'smoke.py')
exit $LASTEXITCODE
