param([switch]$Full)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw '请先按 README 创建虚拟环境并安装 requirements-lock.txt。' }
Push-Location $PSScriptRoot
try {
    & $python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw '单元测试失败。' }
    if ($Full) {
        & $python experiment.py --full --sensitivity --position-sensitivity --output outputs/full
        if ($LASTEXITCODE -ne 0) { throw '完整实验失败。' }
        & $python verify_results.py outputs/full
    } else {
        & $python experiment.py --limit 2 --output outputs/smoke
        if ($LASTEXITCODE -ne 0) { throw '冒烟实验失败。' }
        & $python verify_results.py outputs/smoke
    }
    if ($LASTEXITCODE -ne 0) { throw '结果核验失败。' }
} finally { Pop-Location }
