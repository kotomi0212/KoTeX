param(
    [switch]$SkipLayout,
    [switch]$RunTests
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$projectRoot = $PSScriptRoot

$pythonCandidates = @(
    (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

$python = $null
foreach ($candidate in $pythonCandidates) {
    try {
        & $candidate -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $python = $candidate
            break
        }
    }
    catch {
        continue
    }
}

if (-not $python) {
    throw 'Python 3.10 or later was not found. Install Python and run this script again.'
}

Push-Location $projectRoot
try {
    $failed = $false

    if ($RunTests) {
        & $python -B -m unittest discover -s 'tools\tests' -p 'test_*.py'
        $failed = $failed -or ($LASTEXITCODE -ne 0)
        & $python -B -m unittest discover -s 'tools\layout_checks' -p 'test_*.py'
        $failed = $failed -or ($LASTEXITCODE -ne 0)
    }

    & $python -B 'tools\check_all.py' 'main.tex'
    $failed = $failed -or ($LASTEXITCODE -ne 0)

    if (-not $SkipLayout) {
        if ((Test-Path -LiteralPath 'main.pdf') -and (Test-Path -LiteralPath 'main.aux')) {
            & $python -B 'tools\layout_checks\check_float_placement.py' 'main.pdf' --aux 'main.aux' --tex 'main.tex'
            $failed = $failed -or ($LASTEXITCODE -ne 0)
        }
        else {
            Write-Warning 'main.pdf or main.aux is missing. Run .\build.ps1 first. Skipping the PDF layout check.'
        }
    }

    if ($failed) {
        exit 1
    }
}
finally {
    Pop-Location
}
