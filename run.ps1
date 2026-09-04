# Requires: Python 3.11+
# Usage: .\run.ps1
# Optional: .\run.ps1 -Port 5001

param(
    [int]$Port = 5000
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Resolve-Python {
    foreach ($command in @(
        @{ File = "py"; Args = @("-3.11") },
        @{ File = "py"; Args = @("-3") },
        @{ File = "python"; Args = @() }
    )) {
        try {
            & $command.File @($command.Args + "--version") *> $null
            if ($LASTEXITCODE -eq 0) {
                return $command
            }
        } catch {
            continue
        }
    }
    return $null
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $python = Resolve-Python
    if (-not $python) {
        throw "Python 3.11+ was not found. Install Python and retry."
    }
    Write-Host "Creating virtual environment..."
    & $python.File @($python.Args + "-m" + "venv" + ".venv")
}

& $venvPython -c "import flask, skyfield" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing project dependencies..."
    & $venvPython -m pip install -e ".[dev]"
}

Write-Host "Starting Station Manager on http://127.0.0.1:$Port"
& $venvPython -m flask --app mgm8.api.app run --debug --port $Port
