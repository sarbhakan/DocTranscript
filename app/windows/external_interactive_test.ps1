# Exercise real UI under the ordinary logon token, even when a build agent
# itself is elevated. Do not modify UAC, forge a token, or alter production.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ProbeExe,
    [ValidateSet('Native','Edge')][string]$Case = 'Native',
    [string]$ResultFile
)
$ErrorActionPreference = 'Stop'
$ProbeExe = (Resolve-Path -LiteralPath $ProbeExe).Path
$scriptFile = $PSCommandPath
function Invoke-Recipe {
    if ($Case -eq 'Native') {
        & $ProbeExe
        if ($LASTEXITCODE) { throw "Native external target probe exited with code $LASTEXITCODE." }
    } else {
        & (Join-Path $PSScriptRoot 'external_edge_test.ps1') -ProbeExe $ProbeExe
    }
}

# Parse only Windows machine-readable group SIDs, independent of UI language.
$groups = & "$env:SystemRoot\System32\whoami.exe" /groups /fo csv /nh
if ($LASTEXITCODE) { throw 'Unable to inspect the Windows test logon token.' }
$label = [regex]::Match(($groups -join "`n"), 'S-1-16-(\d+)')
if (-not $label.Success) { throw 'The Windows integrity level is not available.' }
$integrity = [int]$label.Groups[1].Value

if ($ResultFile) {
    # Re-entry runs the same script with no elevation requested.
    # Refuse if this desktop offers no ordinary user token.
    try {
        if ($integrity -lt 8192 -or $integrity -ge 12288) {
            & $ProbeExe --environment
            throw "Test process did not receive a standard interactive token (integrity $integrity)."
        }
        Invoke-Recipe *> "$ResultFile.log"
        [IO.File]::WriteAllText($ResultFile, '0')
    } catch {
        $_ | Out-String | Add-Content -LiteralPath "$ResultFile.log"
        [IO.File]::WriteAllText($ResultFile, '1')
    }
    exit
}
if ($integrity -lt 8192) { throw "Windows interactive user integrity is too low ($integrity)." }
if ($integrity -lt 12288) { Invoke-Recipe; exit }
& $ProbeExe --environment
$work = Join-Path ([IO.Path]::GetTempPath()) ("notevive-interactive-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
$result = Join-Path $work 'result'
try {
    $diagnostics = Join-Path $work 'child-output.log'
    if ($Case -eq 'Native') {
        & $ProbeExe --launch-restricted $ProbeExe '--native-restricted' $PSScriptRoot $diagnostics
        $status = $LASTEXITCODE
        if (Test-Path -LiteralPath $diagnostics) { Get-Content -LiteralPath $diagnostics }
        if ($status) {
            $minimal = Join-Path (Split-Path -Parent $ProbeExe) 'external-user32-fixture.exe'
            if (Test-Path -LiteralPath $minimal -PathType Leaf) {
                Write-Output 'Native recipe failed. Checking minimal User32 process initialization on a fresh recipe desktop.'
                $fixtureDiagnostics = Join-Path $work 'user32-output.log'
                & $ProbeExe --launch-restricted $minimal '--diagnostic' $PSScriptRoot $fixtureDiagnostics
                $fixtureStatus = $LASTEXITCODE
                if (Test-Path -LiteralPath $fixtureDiagnostics) { Get-Content -LiteralPath $fixtureDiagnostics }
                Write-Output "Minimal User32 launcher status: $fixtureStatus"
            }
            throw 'The restricted native recipe failed; see Windows diagnostics.'
        }
        exit
    }
    $powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    # Windows PowerShell 5.1 native arguments need explicitly escaped embedded
    # quotes. Put the command in an encoded script instead of shell-escaping.
    $quoted = { param($value) "'" + $value.Replace("'", "''") + "'" }
    $command = '& ' + (& $quoted $scriptFile) + ' -ProbeExe ' + (& $quoted $ProbeExe) +
               ' -Case ' + $Case + ' -ResultFile ' + (& $quoted $result)
    $encoding = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    & $ProbeExe --launch-restricted $powerShell "-NoProfile -NonInteractive -EncodedCommand $encoding" $PSScriptRoot $diagnostics
    $status = $LASTEXITCODE
    if (Test-Path -LiteralPath $diagnostics) { Get-Content -LiteralPath $diagnostics }
    if (Test-Path -LiteralPath "$result.log") { Get-Content -LiteralPath "$result.log" }
    if ($status -or -not (Test-Path -LiteralPath $result) -or (Get-Content -LiteralPath $result -Raw) -ne '0') {
        throw "$Case recipe failed or could not run under the ordinary desktop token."
    }
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
