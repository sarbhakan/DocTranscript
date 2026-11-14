# An interactive Windows desktop and disposable test user are required.
# Test-only loopback DevTools channel; never attach to an existing user profile.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ProbeExe,
    [string]$EdgeExe,
    [switch]$HostedRecipe
)
$ErrorActionPreference = 'Stop'
if (-not [Environment]::UserInteractive) { throw 'An interactive desktop is required for the Edge smoke test.' }
$ProbeExe = (Resolve-Path -LiteralPath $ProbeExe).Path
if (-not $EdgeExe) {
    $candidates = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
                    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe")
    $EdgeExe = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $EdgeExe) { throw 'Edge is not installed on this Windows host.' }
$EdgeExe = (Resolve-Path -LiteralPath $EdgeExe).Path

# Edge's UserDataDir policy takes precedence over --user-data-dir. Refuse
# before launch so this probe can never reach a profile selected by policy.
# Check both registry views without reading or printing the configured path.
foreach ($hive in @([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryHive]::CurrentUser)) {
    foreach ($view in @([Microsoft.Win32.RegistryView]::Registry64, [Microsoft.Win32.RegistryView]::Registry32)) {
        $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
        try {
            $policy = $base.OpenSubKey('SOFTWARE\Policies\Microsoft\Edge', $false)
            if ($policy) {
                try {
                    if ($policy.GetValueNames() -contains 'UserDataDir') {
                        throw 'Edge sets a profile directory by policy; the isolated recipe refuses to launch.'
                    }
                } finally { $policy.Dispose() }
            }
        } finally { $base.Dispose() }
    }
}

function Require([bool]$Ok, [string]$Message) { if (-not $Ok) { throw $Message } }
function Wait-Until([scriptblock]$Condition, [string]$Failure, [int]$Milliseconds = 7000) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    do {
        if (& $Condition) { return }
        Start-Sleep -Milliseconds 80
    } while ($timer.ElapsedMilliseconds -lt $Milliseconds)
    throw $Failure
}
function CDP([string]$Method, [hashtable]$Arguments = @{}) {
    $script:sequence++
    $request = @{ id = $script:sequence; method = $Method; params = $Arguments } | ConvertTo-Json -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($request)
    $token = [Threading.CancellationTokenSource]::new(4000)
    $scratch = [byte[]]::new(8192)
    $stream = [IO.MemoryStream]::new()
    try {
        $null = $ws.SendAsync([ArraySegment[byte]]::new($bytes), [Net.WebSockets.WebSocketMessageType]::Text,
                      $true, $token.Token).GetAwaiter().GetResult()
        do {
            $stream.SetLength(0)
            do {
                $part = $ws.ReceiveAsync([ArraySegment[byte]]::new($scratch), $token.Token).GetAwaiter().GetResult()
                if ($part.MessageType -ne [Net.WebSockets.WebSocketMessageType]::Text) { throw 'DevTools closed early.' }
                $stream.Write($scratch, 0, $part.Count)
                if ($stream.Length -gt 65536) { throw 'Unexpected DevTools message length.' }
            } while (-not $part.EndOfMessage)
            $message = [Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
        } until ($message.id -eq $script:sequence)
        if ($message.error) { throw "DevTools command failed: $Method" }
        return $message.result
    } finally {
        $stream.Dispose()
        $token.Dispose()
    }
}
function Eval([string]$Expression) {
    $outcome = CDP 'Runtime.evaluate' @{expression = $Expression; returnByValue = $true}
    if ($outcome.exceptionDetails) { throw 'The synthetic test page could not execute its check.' }
    return $outcome.result.value
}
function Probe-Read {
    $line = $probe.StandardOutput.ReadLineAsync()
    if (-not $line.Wait(6000) -or $null -eq $line.Result) { throw 'External target probe did not reply.' }
    return $line.Result
}
function Probe([string]$Command, [string]$Expected) {
    $probe.StandardInput.WriteLine($Command)
    $probe.StandardInput.Flush()
    $actual = Probe-Read
    Require ($actual -eq $Expected) "Probe $Command : expected $Expected; received $actual."
}
function Select-A([bool]$Selected = $false) {
    $start = if ($Selected) { 0 } else { 1 }
    Require (Eval "(() => { a.focus(); a.setSelectionRange($start,1); return document.hasFocus() && document.activeElement === a; })()") 'Edge textarea did not receive focus.'
}
function Select-Editable {
    Require (Eval '(() => { rich.focus(); const r=document.createRange(); r.setStart(rich.firstChild,1); r.collapse(true); const s=getSelection(); s.removeAllRanges(); s.addRange(r); return document.hasFocus() && document.activeElement===rich; })()') 'Edge contenteditable did not receive focus.'
}

function Log-EdgeStartupEnvironment([string]$phase, [string]$dll) {
    Write-Output "Edge recipe environment: $phase."
    & $ProbeExe --edge-startup-diagnostic $dll
    if ($LASTEXITCODE -ne 0) { Write-Output "Edge startup diagnostic exited with $LASTEXITCODE." }
}

function Log-EdgeFailure {
    if ($edge) {
        $state = if ($edge.HasExited) { 'exited 0x{0:X8}' -f $edge.ExitCode } else { 'still running' }
        Write-Output "Edge startup: $state; version=$([Diagnostics.FileVersionInfo]::GetVersionInfo($EdgeExe).FileVersion); profileExists=$(Test-Path -LiteralPath $profile -PathType Container); profileState=$(Test-Path -LiteralPath (Join-Path $profile 'Local State') -PathType Leaf); portFile=$(Test-Path -LiteralPath $portFile -PathType Leaf)."
    }
    foreach ($scope in @('HKLM', 'HKCU')) {
        $key = "${scope}:\Software\Policies\Microsoft\Edge"
        foreach ($policy in @('RemoteDebuggingAllowed', 'DeveloperToolsAvailability')) {
            $value = (Get-ItemProperty -LiteralPath $key -Name $policy -ErrorAction SilentlyContinue).$policy
            if ($null -ne $value) { Write-Output "Edge policy ${scope}.$policy=$value" }
        }
    }
    # Only logs from the new synthetic profile. Bound the amount printed and
    # never inspect any existing profile or browsing data.
    foreach ($debug in @((Join-Path $profile 'chrome_debug.log'), (Join-Path $profile 'msedge_debug.log'))) {
        if (Test-Path -LiteralPath $debug -PathType Leaf) {
            Get-Content -LiteralPath $debug -Tail 6 -ErrorAction SilentlyContinue |
                ForEach-Object { Write-Output ("Edge startup log: " + $_.Substring(0, [Math]::Min($_.Length, 300))) }
        }
    }
    if ($HostedRecipe) {
        $installation = Split-Path -Parent $EdgeExe
        $version = [regex]::Match([Diagnostics.FileVersionInfo]::GetVersionInfo($EdgeExe).FileVersion, '^\d+\.\d+\.\d+\.\d+')
        $dll = Join-Path $installation 'msedge.dll'
        if ($version.Success -and -not (Test-Path -LiteralPath $dll -PathType Leaf)) {
            $dll = Join-Path (Join-Path $installation $version.Value) 'msedge.dll'
        }
        if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { $dll = '-' }
        Log-EdgeStartupEnvironment 'after the browser failure' $dll
    }
}

$scratch = [IO.Path]::GetTempPath()
if ($HostedRecipe) {
    # Use the account's loaded Windows profile and its inherited NTFS ACL.
    # The shared stage is only for scripts and logs, not the browser profile.
    $homeDirectory = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
    $account = [Security.Principal.WindowsIdentity]::GetCurrent().Name.Split('\')[-1]
    $scratch = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData,
        [Environment+SpecialFolderOption]::Create)
    if (-not $homeDirectory -or -not $scratch -or $account -notmatch '^nvrecipe-[0-9a-f]{10}$' -or
        (Split-Path -Leaf $homeDirectory) -ine $account -or
        -not $scratch.StartsWith($homeDirectory.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Windows did not provide LocalAppData for the disposable Edge account.'
    }
}
$work = Join-Path $scratch ("notevive-edge-" + [guid]::NewGuid().ToString('N'))
$profile = Join-Path $work 'profile'
$portFile = Join-Path $profile 'DevToolsActivePort'
$edge = $null; $probe = $null; $ws = $null
$script:sequence = 0
New-Item -ItemType Directory -Path $work | Out-Null
try {
    # Chromium's ProcessSingleton opens a profile lock with DeleteOnClose.
    # Prove that exact file operation under the browser's identity beforehand.
    [void][IO.Directory]::CreateDirectory($profile)
    $lockProbe = Join-Path $profile '.notevive-lock-test'
    $test = [IO.FileStream]::new($lockProbe, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write,
        [IO.FileShare]::Read, 4096, [IO.FileOptions]::DeleteOnClose)
    $test.Dispose()
    Require (-not (Test-Path -LiteralPath $lockProbe)) 'The temporary profile cannot delete a lock after closing it.'
    Write-Output 'Edge profile lock preflight passed.'
    $html = Join-Path $work 'note-test.html'
    @'
<!doctype html>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>NoteVive synthetic input probe</title>
<style>label, [contenteditable] { display:block; margin:1rem; } [contenteditable] { border:1px solid; width:16rem; }</style>
<label>First <textarea id="a" spellcheck="false">ab</textarea></label>
<label>Second <textarea id="b" spellcheck="false">cd</textarea></label>
<label>Password <input id="password" type="password" autocomplete="off"></label>
<div id="rich" contenteditable="true" role="textbox" aria-label="Rich editor" aria-multiline="true" spellcheck="false">xy</div>
'@ | Set-Content -LiteralPath $html -Encoding UTF8
    $url = [Uri]::new($html).AbsoluteUri
    # A unique directory prevents profile reuse. On Windows a debugging port
    # of 0 is assigned by Edge; DevToolsActivePort identifies that listener.
    $flags = @("--user-data-dir=`"$profile`"", '--remote-debugging-port=0',
        '--remote-debugging-address=127.0.0.1', '--no-first-run', '--no-default-browser-check',
        '--enable-logging',
        '--disable-background-networking', '--disable-sync', '--disable-component-update',
        '--disable-default-apps', '--disable-extensions', '--no-proxy-server',
        '--host-resolver-rules="MAP * ~NOTFOUND, EXCLUDE localhost"',
        '--new-window', $url)
    # The hosted desktop has no GPU requirement. Leave the rendering path
    # unchanged for a local smoke test from a normal Windows account.
    if ($HostedRecipe) { $flags += '--disable-gpu' }
    $browserStart = [Diagnostics.ProcessStartInfo]::new()
    $browserStart.FileName = $EdgeExe
    $browserStart.Arguments = $flags -join ' '
    $browserStart.WorkingDirectory = $work
    $browserStart.UseShellExecute = $false
    $browserStart.EnvironmentVariables['TEMP'] = $work
    $browserStart.EnvironmentVariables['TMP'] = $work
    if ($HostedRecipe) { Log-EdgeStartupEnvironment 'before browser startup' '-' }
    $edge = [Diagnostics.Process]::Start($browserStart)
    Wait-Until {
        if ($edge.HasExited) { throw 'The isolated Edge process exited during startup.' }
        if (-not (Test-Path -LiteralPath $portFile -PathType Leaf)) { return $false }
        try { return (Get-Content -LiteralPath $portFile -TotalCount 1) -match '^\d+$' } catch { return $false }
    } 'Disposable Edge profile did not start DevTools.' 25000
    $port = [int](Get-Content -LiteralPath $portFile -TotalCount 1)
    Require ($port -gt 0 -and $port -lt 65536) 'Bad loopback port.'
    $page = $null
    $discovery = [Diagnostics.Stopwatch]::StartNew()
    while (-not $page -and $discovery.ElapsedMilliseconds -lt 12000) {
        try {
            $targets = Invoke-RestMethod -UseBasicParsing -Uri "http://127.0.0.1:$port/json/list" -TimeoutSec 2
            $page = $targets | Where-Object { $_.type -eq 'page' -and $_.url -eq $url } | Select-Object -First 1
        } catch { Start-Sleep -Milliseconds 80 }
        if (-not $page) { Start-Sleep -Milliseconds 80 }
    }
    Require ($null -ne $page) 'Synthetic page was not exposed on loopback.'
    $socket = [Uri]$page.webSocketDebuggerUrl
    Require ($socket.Scheme -eq 'ws' -and $socket.IsLoopback -and $socket.Port -eq $port) 'Not a loopback DevTools target.'
    $ws = [Net.WebSockets.ClientWebSocket]::new()
    $ws.Options.Proxy = $null
    $deadline = [Threading.CancellationTokenSource]::new(4000)
    try { $null = $ws.ConnectAsync($socket, $deadline.Token).GetAwaiter().GetResult() } finally { $deadline.Dispose() }
    $null = CDP 'Page.bringToFront'
    Wait-Until { Eval 'document.readyState === "complete" && document.hasFocus()' } 'The disposable Edge window did not become active.'

    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $ProbeExe
    $info.Arguments = "--edge-probe $($edge.Id)"
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $probe = [Diagnostics.Process]::Start($info)
    Require ((Probe-Read) -eq 'OK') 'Edge probe did not initialize.'
    $expected = 'a' + [char]0xe9 + ' ' + [char]0xbd + 'b'
    Select-A
    Probe 'capture' 'ready'
    Probe 'send' 'submitted'
    Wait-Until { (Eval 'a.value') -ceq $expected } 'Textarea did not receive the expected Unicode text.'
    Require ((Eval 'b.value') -ceq 'cd') 'An unrelated textarea was modified.'

    Require (Eval '(() => { b.focus(); b.setSelectionRange(1,1); return document.activeElement===b; })()') 'Second textarea was not focused.'
    Probe 'check-change' 'target_changed'
    Select-A
    Probe 'send' 'target_changed'
    Require ((Eval 'a.value') -ceq $expected -and (Eval 'b.value') -ceq 'cd') 'A previous target reopened after a DOM focus change.'
    Probe 'reset' 'inactive'

    Select-A $true
    Probe 'capture' 'unsupported'
    Require ((Eval 'a.value') -ceq $expected) 'A selected textarea was modified.'
    Probe 'reset' 'inactive'

    Require (Eval '(() => { password.focus(); return document.activeElement===password; })()') 'Password field was not focused.'
    Probe 'capture' 'protected_field'
    Require ((Eval 'password.value') -ceq '') 'Password field was modified.'
    Probe 'reset' 'inactive'

    Select-Editable
    Probe 'capture' 'ready'
    Probe 'send' 'submitted'
    $expectedRich = 'x' + [char]0xe9 + ' ' + [char]0xbd + 'y'
    Wait-Until { (Eval 'rich.textContent') -ceq $expectedRich } 'Contenteditable did not receive the expected Unicode text.'
    Require ((Eval 'a.value') -ceq $expected -and (Eval 'b.value') -ceq 'cd') 'Other fields changed during contenteditable insertion.'
    $probe.StandardInput.WriteLine('quit')
    if (-not $probe.WaitForExit(4000) -or $probe.ExitCode -ne 0) { throw 'Edge probe did not shut down cleanly.' }
    Write-Output 'Edge local input probe: textarea, contenteditable, focus and protected fields passed.'
} catch {
    Log-EdgeFailure
    throw
} finally {
    if ($probe) {
        if (-not $probe.HasExited) { $probe.Kill() }
        $probe.Dispose()
    }
    if ($ws) { $ws.Dispose() }
    if ($edge) {
        # Terminate only the instance created with the disposable profile.
        if (-not $edge.HasExited) { & taskkill.exe /PID $edge.Id /T /F 2>$null | Out-Null }
        $edge.Dispose()
    }
    Remove-Item -LiteralPath $work -Force -Recurse -ErrorAction SilentlyContinue
}
