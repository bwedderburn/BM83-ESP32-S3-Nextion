<#
.SYNOPSIS
    One-time, re-runnable Windows development setup for this repository.

.DESCRIPTION
    Creates .venv (uv when available, otherwise the py launcher), installs
    requirements-dev.txt, the repo-health MCP dependency and the editable package
    the way CI does, selects the CircuitPython board stubs, then installs the
    VS Code extensions recommended in .vscode\extensions.json.
    It never touches a board, a COM port or the CIRCUITPY drive.

.PARAMETER Python
    Python version for a new .venv. Default 3.13, the newest version CI tests.

.PARAMETER Board
    CircuitPython board id for the editor stubs. Default espressif_esp32s3_devkitc_1_n8r8.

.PARAMETER SkipExtensions
    Do not install VS Code extensions.

.PARAMETER Recreate
    Delete and rebuild .venv.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup-dev.ps1
#>
[CmdletBinding()]
param(
    [string]$Python = '3.13',
    [string]$Board = 'espressif_esp32s3_devkitc_1_n8r8',
    [switch]$SkipExtensions,
    [switch]$Recreate
)

$ErrorActionPreference = 'Stop'

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw ('"{0} {1}" failed with exit code {2}' -f $File, ($Arguments -join ' '), $LASTEXITCODE)
    }
}

$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$venv = Join-Path $root '.venv'
$py = Join-Path $venv 'Scripts\python.exe'
$uv = Get-Command uv -ErrorAction SilentlyContinue

if ($Recreate -and (Test-Path -LiteralPath $venv)) {
    Write-Host 'Removing existing .venv (-Recreate)'
    Remove-Item -LiteralPath $venv -Recurse -Force
}

if (-not (Test-Path -LiteralPath $py)) {
    Write-Host "Creating .venv with Python $Python"
    if ($uv) {
        Invoke-Checked $uv.Source @('venv', '--seed', '--python', $Python, $venv)
    } else {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if (-not $launcher) {
            throw 'Neither uv nor the py launcher was found. Install uv (winget install astral-sh.uv) and re-run.'
        }
        Invoke-Checked $launcher.Source @("-$Python", '-m', 'venv', $venv)
    }
} else {
    Write-Host 'Reusing existing .venv'
}

# Single quotes only inside the Python snippet: Windows PowerShell 5.1 does not
# escape embedded double quotes when it passes arguments to native programs.
$version = (& $py -c 'import sys; print(''%d.%d'' % sys.version_info[:2])').Trim()
Write-Host "Python $version at $py"
if (@('3.11', '3.12', '3.13') -notcontains $version) {
    Write-Host "Note: CI tests Python 3.11-3.13; run with -Recreate to rebuild .venv on Python $Python."
}

$requirements = @('-r', 'requirements-dev.txt', '-r', 'tools\mcp\repo_health\requirements.txt')
if ($uv) {
    Invoke-Checked $uv.Source (@('pip', 'install', '--python', $py) + $requirements)
    Invoke-Checked $uv.Source @('pip', 'install', '--python', $py, '-e', '.')
} else {
    Invoke-Checked $py @('-m', 'pip', 'install', '--upgrade', 'pip')
    Invoke-Checked $py (@('-m', 'pip', 'install') + $requirements)
    Invoke-Checked $py @('-m', 'pip', 'install', '-e', '.')
}

Invoke-Checked (Join-Path $venv 'Scripts\circuitpython_setboard.exe') @($Board)

if (-not $SkipExtensions) {
    $code = Get-Command code -ErrorAction SilentlyContinue
    if ($code) {
        $wanted = (Get-Content -Raw -LiteralPath '.vscode\extensions.json' | ConvertFrom-Json).recommendations
        $installed = @(& $code.Source --list-extensions) | ForEach-Object { $_.ToLowerInvariant() }
        foreach ($extension in $wanted) {
            if ($installed -contains $extension.ToLowerInvariant()) {
                Write-Host "  installed  $extension"
                continue
            }
            & $code.Source --install-extension $extension | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  added      $extension"
            } else {
                Write-Warning "Could not install $extension (it may be built into your VS Code)."
            }
        }
    } else {
        Write-Host "VS Code's 'code' command was not found; open the folder in VS Code and accept the"
        Write-Host 'recommended extensions instead (Extensions view > Recommended).'
    }
}

Write-Host ''
Write-Host 'Setup complete. In VS Code:'
Write-Host '  1. Command Palette > "Python: Select Interpreter" > .venv (if it is not already selected)'
Write-Host '  2. Terminal > Run Task > "BM83: host tests" (or "CI parity: lint gate, host tests, policy")'
