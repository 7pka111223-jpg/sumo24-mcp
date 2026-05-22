# =============================================================================
# SUMO24 MCP Server - Windows installer
# =============================================================================
# What this does:
#   1. Finds a working Python interpreter (py -3, python, or known install paths)
#   2. Installs the 'mcp' package into that Python
#   3. Smoke-tests that server.py can be imported without crashing
#   4. Writes %APPDATA%\Claude\claude_desktop_config.json with an absolute Python path
#   5. Prints next steps (restart Claude Desktop, where to find logs)
#
# Usage (PowerShell):
#   cd <your-clone-of-sumo24-mcp>
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# Re-run safe: overwrites only the 'sumo24' entry in the Claude config; other
# MCP servers you had registered are preserved.
# =============================================================================

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServerPy    = Join-Path $ProjectRoot "server.py"
$StateXml    = Join-Path $ProjectRoot "state.xml"
$ModelDll    = Join-Path $ProjectRoot "sumoproject.dll"
$OutputDir   = Join-Path $ProjectRoot "outputs"
$ClaudeDir   = Join-Path $env:APPDATA "Claude"
$ConfigPath  = Join-Path $ClaudeDir "claude_desktop_config.json"

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host "  SUMO24 MCP Server - Windows Installer" -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Project root : $ProjectRoot"
Write-Host "Server.py    : $ServerPy"
Write-Host ""

# -----------------------------------------------------------------------------
# 1. Find Python
# -----------------------------------------------------------------------------
Write-Host "[1/5] Locating Python..." -ForegroundColor Yellow

function Test-PythonCommand {
    param([string]$Cmd, [string[]]$PreArgs)
    try {
        $args = @()
        if ($PreArgs) { $args += $PreArgs }
        $args += "-c"
        $args += "import sys; print(sys.executable); print(sys.version_info[:2])"
        $out = & $Cmd @args 2>&1
        if ($LASTEXITCODE -eq 0 -and $out) {
            $lines = $out -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
            if ($lines.Count -ge 2) {
                $exePath = $lines[0]
                # Reject Microsoft Store stub
                if ($exePath -like "*WindowsApps*") { return $null }
                if (-not (Test-Path $exePath)) { return $null }
                return [PSCustomObject]@{
                    Command  = $Cmd
                    PreArgs  = $PreArgs
                    ExePath  = $exePath
                    Version  = $lines[1]
                }
            }
        }
    } catch { return $null }
    return $null
}

$candidates = @(
    @{ Cmd = "py";     PreArgs = @("-3") }
    @{ Cmd = "python"; PreArgs = @() }
    @{ Cmd = "python3";PreArgs = @() }
)

$python = $null
foreach ($c in $candidates) {
    $r = Test-PythonCommand -Cmd $c.Cmd -PreArgs $c.PreArgs
    if ($r) { $python = $r; break }
}

# Last-ditch: probe common install locations
if (-not $python) {
    $probes = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
        "C:\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
        "C:\Python310\python.exe"
    )
    foreach ($p in $probes) {
        if (Test-Path $p) {
            $python = [PSCustomObject]@{
                Command = $p; PreArgs = @(); ExePath = $p; Version = "(probed)"
            }
            break
        }
    }
}

if (-not $python) {
    Write-Host ""
    Write-Host "ERROR: Could not find a working Python interpreter." -ForegroundColor Red
    Write-Host "Install Python 3.10+ from https://www.python.org/downloads/"
    Write-Host "During install, check:"
    Write-Host "   [x] Add python.exe to PATH"
    Write-Host "   [x] Install launcher for all users (py.exe)"
    exit 1
}

Write-Host "  Command : $($python.Command) $($python.PreArgs -join ' ')"
Write-Host "  Path    : $($python.ExePath)"
Write-Host "  Version : $($python.Version)"
Write-Host ""

# -----------------------------------------------------------------------------
# 2. Install mcp package
# -----------------------------------------------------------------------------
Write-Host "[2/5] Installing 'mcp' package into this Python..." -ForegroundColor Yellow

$pipArgs = @()
if ($python.PreArgs) { $pipArgs += $python.PreArgs }
$pipArgs += "-m"; $pipArgs += "pip"; $pipArgs += "install"; $pipArgs += "--upgrade"; $pipArgs += "mcp"

& $python.Command @pipArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pip install mcp failed." -ForegroundColor Red
    exit 1
}
Write-Host ""

# -----------------------------------------------------------------------------
# 3. Smoke-test server.py imports
# -----------------------------------------------------------------------------
Write-Host "[3/5] Smoke-testing server.py imports..." -ForegroundColor Yellow

$smokeArgs = @()
if ($python.PreArgs) { $smokeArgs += $python.PreArgs }
$smokeArgs += "-c"
$smokeArgs += @"
import sys, importlib.util, pathlib
root = pathlib.Path(r'$ProjectRoot')
sys.path.insert(0, str(root))
spec = importlib.util.spec_from_file_location('server_check', r'$ServerPy')
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    print('server.py imports OK')
except SystemExit:
    print('server.py imports OK (exited cleanly)')
except Exception as e:
    print('IMPORT ERROR:', type(e).__name__, e)
    sys.exit(2)
"@

& $python.Command @smokeArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "WARNING: server.py had an import problem above." -ForegroundColor Red
    Write-Host "Continuing anyway; if 'dynamita' is missing that's only a warning."
}
Write-Host ""

# -----------------------------------------------------------------------------
# 4. Write claude_desktop_config.json
# -----------------------------------------------------------------------------
Write-Host "[4/5] Writing Claude Desktop config..." -ForegroundColor Yellow

New-Item -ItemType Directory -Force -Path $ClaudeDir | Out-Null
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

# Use absolute path to python.exe so Claude Desktop never hits the Store stub.
$PyExe = $python.ExePath

# Normalise paths for JSON (forward slashes, no escaping headaches)
$ServerPyJson = $ServerPy.Replace("\", "/")
$ModelDllJson = $ModelDll.Replace("\", "/")
$StateXmlJson = $StateXml.Replace("\", "/")
$OutputDirJson = $OutputDir.Replace("\", "/")
$PyExeJson    = $PyExe.Replace("\", "/")

$sumoEntry = [ordered]@{
    command = $PyExe
    args    = @($ServerPy)
    env     = [ordered]@{
        SUMO_DLL    = $ModelDll
        SUMO_STATE  = $StateXml
        SUMO_OUTPUT = $OutputDir
        PYTHONPATH  = $ProjectRoot
    }
}

# Merge into existing config if present
if (Test-Path $ConfigPath) {
    try {
        $existing = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    } catch {
        Write-Host "  Existing config is not valid JSON; backing up to .bak" -ForegroundColor Yellow
        Copy-Item $ConfigPath "$ConfigPath.bak" -Force
        $existing = $null
    }
} else {
    $existing = $null
}

if (-not $existing) {
    $existing = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
}
if (-not $existing.mcpServers) {
    $existing | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([PSCustomObject]@{}) -Force
}

# Convert sumo entry into a proper PSCustomObject
$sumoObj = [PSCustomObject]$sumoEntry
$existing.mcpServers | Add-Member -NotePropertyName "sumo24" -NotePropertyValue $sumoObj -Force

$json = $existing | ConvertTo-Json -Depth 10
$json | Set-Content -Path $ConfigPath -Encoding UTF8

Write-Host "  Config written: $ConfigPath"
Write-Host ""

# -----------------------------------------------------------------------------
# 5. Done
# -----------------------------------------------------------------------------
Write-Host "[5/5] All done." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Fully quit Claude Desktop (right-click tray icon -> Quit)."
Write-Host "  2. Start Claude Desktop again."
Write-Host "  3. Open a chat - you should see 'sumo24' in the tools list."
Write-Host ""
Write-Host "If 'sumo24' still doesn't appear, check the MCP logs at:"
Write-Host "  $env:APPDATA\Claude\logs\"
Write-Host "Look for files starting with 'mcp-server-sumo24'."
Write-Host ""
Write-Host "To re-diagnose, run:  .\diagnose.ps1" -ForegroundColor Cyan
Write-Host ""
