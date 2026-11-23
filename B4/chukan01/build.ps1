$ErrorActionPreference = 'Stop'

$projectRoot = $PSScriptRoot

Push-Location $projectRoot
try {
    & latexmk -lualatex @args main.tex
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
