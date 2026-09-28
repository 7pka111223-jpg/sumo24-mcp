# Install the server and bundled DynaSand into an existing licensed SUMO24 installation.
[CmdletBinding()]
param([string]$SumoDir, [string]$ProjectDir, [string]$ConfigPath, [string]$DataDir,
      [string]$PythonExe, [switch]$NonInteractive, [switch]$SkipDependencies)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
try {
    if (-not $PythonExe) {
        foreach ($candidate in @('py', 'python', 'python3')) {
            if (Get-Command $candidate -ErrorAction SilentlyContinue) {
                $probeArgs = @('-c', 'import sys; assert sys.version_info >= (3,11); print(sys.executable)')
                if ($candidate -eq 'py') { $probeArgs = @('-3') + $probeArgs }
                $found = & $candidate @probeArgs 2>$null
                if ($LASTEXITCODE -eq 0 -and $found -and (Test-Path -LiteralPath ([string]$found))) {
                    $PythonExe = [string]$found
                    break
                }
            }
        }
    }
    if (-not $PythonExe) { throw 'Python 3.11+ was not found. Install Python and rerun install.ps1.' }
    if (-not $SkipDependencies) {
        $venv = Join-Path $ProjectRoot '.venv'
        & $PythonExe -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Creating the Python environment failed.' }
        $PythonExe = Join-Path $venv 'Scripts\python.exe'
        & $PythonExe -m pip install "${ProjectRoot}[gui,reports,excel]"
        if ($LASTEXITCODE -ne 0) { throw 'Installing dependencies failed. Check the pip error and retry.' }
    }
    $setupArgs = @('-X', 'utf8', (Join-Path $ProjectRoot 'PY\install_server.py'))
    if ($SumoDir) { $setupArgs += @('--sumo-dir', $SumoDir) }
    if ($ProjectDir) { $setupArgs += @('--project-dir', $ProjectDir) }
    if ($ConfigPath) { $setupArgs += @('--config', $ConfigPath) }
    if ($DataDir) { $setupArgs += @('--data-dir', $DataDir) }
    if ($NonInteractive) { $setupArgs += '--non-interactive' }
    & $PythonExe @setupArgs
    exit $LASTEXITCODE
} catch {
    Write-Host "Installation failed: $_" -ForegroundColor Red
    exit 1
}
