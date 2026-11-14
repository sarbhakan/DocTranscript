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
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'Run the external dictation recipe as a standard Windows user. The temporary-account path is hosted CI only.'
}
$work = Join-Path $env:PUBLIC ("notevive-interactive-" + [guid]::NewGuid().ToString('N'))
$created = $false
try {
    # Keep only program and script copies in this stage. The launcher grants
    # the single recipe account read/execute here and write in out only.
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @('S-1-5-18', 'S-1-5-32-544', [Security.Principal.WindowsIdentity]::GetCurrent().User.Value)) {
        $who = [Security.Principal.SecurityIdentifier]::new($sid)
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $who, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'
        )
        $acl.AddAccessRule($rule)
    }
    if (Test-Path -LiteralPath $work) { throw 'The isolated recipe directory already exists.' }
    # Apply the restricted ACL at creation. Calling .NET directly avoids
    # loading the Security module into a different PowerShell edition.
    if ($PSVersionTable.PSEdition -eq 'Desktop') {
        $null = [IO.Directory]::CreateDirectory($work, $acl)
    } else {
        $null = [IO.FileSystemAclExtensions]::CreateDirectory($acl, $work)
    }
    $created = $true
    $out = Join-Path $work 'out'
    New-Item -ItemType Directory -Path $out | Out-Null
    $stagedProbe = Join-Path $work 'external-target-test.exe'
    Copy-Item -LiteralPath $ProbeExe -Destination $stagedProbe
    if ($Case -eq 'Native') {
        & $ProbeExe --launch-standard $stagedProbe '--native-standard' $work
        $status = $LASTEXITCODE
        $diagnostics = Join-Path $out 'native.log'
        if (Test-Path -LiteralPath $diagnostics) { Get-Content -LiteralPath $diagnostics }
        if ($status) {
            $minimal = Join-Path (Split-Path -Parent $ProbeExe) 'external-user32-fixture.exe'
            if (Test-Path -LiteralPath $minimal -PathType Leaf) {
                Write-Output 'Native recipe failed. Checking minimal User32 process initialization on a fresh recipe desktop.'
                $stagedMinimal = Join-Path $work 'external-user32-fixture.exe'
                Copy-Item -LiteralPath $minimal -Destination $stagedMinimal
                $fixtureDiagnostics = Join-Path $out 'user32.log'
                & $ProbeExe --launch-standard $stagedMinimal '--diagnostic' $work
                $fixtureStatus = $LASTEXITCODE
                if (Test-Path -LiteralPath $fixtureDiagnostics) { Get-Content -LiteralPath $fixtureDiagnostics }
                Write-Output "Minimal User32 launcher status: $fixtureStatus"
            }
            throw 'The native recipe under the standard account failed; see Windows diagnostics.'
        }
        exit
    }
    Copy-Item -LiteralPath $scriptFile -Destination (Join-Path $work 'external_interactive_test.ps1')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'external_edge_test.ps1') -Destination $work
    $result = Join-Path $out 'result'
    $bootstrap = @'
$ErrorActionPreference = 'Stop'
try {
    $probe = Join-Path $PSScriptRoot 'external-target-test.exe'
    & (Join-Path $PSScriptRoot 'external_interactive_test.ps1') -ProbeExe $probe -Case Edge -ResultFile (Join-Path $PSScriptRoot 'out\result')
} catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'out\bootstrap.log')
    exit 1
}
'@
    Set-Content -LiteralPath (Join-Path $work 'edge-bootstrap.ps1') -Value $bootstrap
    $powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    & $ProbeExe --launch-standard $powerShell '-NoProfile -NonInteractive -File .\edge-bootstrap.ps1' $work
    $status = $LASTEXITCODE
    $bootstrapLog = Join-Path $out 'bootstrap.log'
    if (Test-Path -LiteralPath $bootstrapLog) { Get-Content -LiteralPath $bootstrapLog }
    if (Test-Path -LiteralPath "$result.log") { Get-Content -LiteralPath "$result.log" }
    if ($status -or -not (Test-Path -LiteralPath $result) -or (Get-Content -LiteralPath $result -Raw) -ne '0') {
        throw "$Case recipe failed or could not run under the ordinary desktop token."
    }
} finally {
    if ($created) { Remove-Item -LiteralPath $work -Recurse -Force }
}
