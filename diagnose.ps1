# =============================================================================
# SUMO24 MCP Server - Windows diagnostic
# =============================================================================
# Checks the five things that typically stop Claude Desktop from seeing 'SUMO24MCPv2':
#   1. Python is findable and not the Microsoft Store stub
#   2. 'mcp' package is importable by that Python
#   3. server.py imports cleanly (no syntax / dependency errors)
#   4. claude_desktop_config.json exists at the right path and is valid JSON
#   5. The 'SUMO24MCPv2' entry points at files that actually exist
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\diagnose.ps1
# =============================================================================

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServerPy    = Join-Path $ProjectRoot "PY\server.py"
$StateXml    = Join-Path $ProjectRoot "state.xml"
$ModelDll    = Join-Path $ProjectRoot "sumoproject.dll"
$ClaudeDir   = Join-Path $env:APPDATA "Claude"
$ConfigPath  = Join-Path $ClaudeDir "claude_desktop_config.json"
$LogsDir     = Join-Path $ClaudeDir "logs"

$failures = @()

function Check($name, [scriptblock]$block) {
    Write-Host "-- $name" -ForegroundColor Cyan
    try {
        $ok = & $block
        if ($ok) { Write-Host "   OK" -ForegroundColor Green }
        else { Write-Host "   FAIL" -ForegroundColor Red; $script:failures += $name }
    } catch {
        Write-Host "   ERROR: $_" -ForegroundColor Red
        $script:failures += $name
    }
    Write-Host ""
}

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host "  SUMO24 MCP Server - Diagnostic" -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Project root : $ProjectRoot"
Write-Host "Config path  : $ConfigPath"
Write-Host ""

# --- 1. Python ---------------------------------------------------------------
$pyCmd = $null
Check "Python interpreter available" {
    foreach ($c in @(@("py","-3"), @("python"), @("python3"))) {
        try {
            $argsNoC = $c + @("-c", "import sys; print(sys.executable)")
            $exe = & $c[0] @($argsNoC[1..($argsNoC.Count-1)]) 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe -and $exe -notlike "*WindowsApps*") {
                $script:pyCmd = $c
                Write-Host "   Using: $($c -join ' ')  ->  $exe"
                return $true
            }
        } catch {}
    }
    Write-Host "   No working Python found. Install from https://www.python.org/downloads/"
    return $false
}

# --- 2. mcp package ----------------------------------------------------------
Check "'mcp' package installed" {
    if (-not $pyCmd) { return $false }
    $test = $pyCmd + @("-c", "import mcp, mcp.types; from mcp.server import Server; from mcp.server.stdio import stdio_server; print('ok')")
    $out = & $test[0] @($test[1..($test.Count-1)]) 2>&1
    if ($LASTEXITCODE -eq 0) { return $true }
    Write-Host "   $out"
    Write-Host "   Fix:  $($pyCmd -join ' ') -m pip install mcp"
    return $false
}

# --- 3. server.py imports ----------------------------------------------------
Check "server.py imports cleanly" {
    if (-not $pyCmd) { return $false }
    if (-not (Test-Path $ServerPy)) { Write-Host "   Missing: $ServerPy"; return $false }
    $script = @"
import sys, importlib.util, pathlib
sys.path.insert(0, r'$ProjectRoot')
spec = importlib.util.spec_from_file_location('s', r'$ServerPy')
m = importlib.util.module_from_spec(spec)
try: spec.loader.exec_module(m); print('ok')
except SystemExit: print('ok')
except Exception as e: print('FAIL:', type(e).__name__, e); sys.exit(2)
"@
    $test = $pyCmd + @("-c", $script)
    $out = & $test[0] @($test[1..($test.Count-1)]) 2>&1
    Write-Host "   $out"
    return ($LASTEXITCODE -eq 0)
}

# --- 4. Config file ----------------------------------------------------------
Check "claude_desktop_config.json exists and is valid JSON" {
    if (-not (Test-Path $ConfigPath)) {
        Write-Host "   Missing: $ConfigPath"
        Write-Host "   Fix:  run .\install.ps1"
        return $false
    }
    try {
        $cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    } catch {
        Write-Host "   Not valid JSON: $_"
        return $false
    }
    if (-not $cfg.mcpServers) { Write-Host "   No 'mcpServers' key"; return $false }
    if (-not $cfg.mcpServers.SUMO24MCPv2) { Write-Host "   No 'SUMO24MCPv2' entry under mcpServers"; return $false }
    $entry = $cfg.mcpServers.SUMO24MCPv2
    Write-Host ("   command: {0}" -f $entry.command)
    Write-Host ("   args   : {0}" -f ($entry.args -join ' '))
    return $true
}

# --- 5. Referenced files exist ----------------------------------------------
Check "Referenced files exist (server.py, state.xml, sumoproject.dll)" {
    $allOk = $true
    foreach ($p in @($ServerPy, $StateXml, $ModelDll)) {
        if (Test-Path $p) { Write-Host "   [OK]   $p" }
        else { Write-Host "   [MISS] $p" -ForegroundColor Yellow; $allOk = $false }
    }
    return $allOk
}

# --- MCP log tail ------------------------------------------------------------
Write-Host "-- Recent Claude MCP log output (if any)" -ForegroundColor Cyan
if (Test-Path $LogsDir) {
    $log = Get-ChildItem $LogsDir -Filter "mcp-server-SUMO24MCPv2*.log" -ErrorAction SilentlyContinue |
           Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($log) {
        Write-Host "   File: $($log.FullName)"
        Write-Host "   --- last 30 lines ---"
        Get-Content $log.FullName -Tail 30 | ForEach-Object { Write-Host "   $_" }
    } else {
        Write-Host "   No SUMO24MCPv2 log file yet. Start Claude Desktop at least once after install."
    }
} else {
    Write-Host "   $LogsDir does not exist yet - Claude Desktop hasn't created it."
}
Write-Host ""

# --- Summary -----------------------------------------------------------------
if ($failures.Count -eq 0) {
    Write-Host "All checks passed. Quit Claude Desktop via the tray icon and relaunch." -ForegroundColor Green
} else {
    Write-Host "Failed checks:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Try running: .\install.ps1"
}
Write-Host ""
