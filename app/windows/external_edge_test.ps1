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
function Connect-DevTools([Uri]$Address, [string]$Channel) {
    $client = [Net.WebSockets.ClientWebSocket]::new()
    $client.Options.Proxy = $null
    $deadline = [Threading.CancellationTokenSource]::new(6500)
    try {
        $null = $client.ConnectAsync($Address, $deadline.Token).GetAwaiter().GetResult()
        return $client
    } catch {
        $client.Dispose()
        throw "Edge DevTools $Channel connection failed: $($_.Exception.GetBaseException().Message)"
    } finally { $deadline.Dispose() }
}
function CDP([string]$Method, [hashtable]$Arguments = @{}, [int]$Timeout = 6500, [string]$Phase = $Method) {
    $script:cdpSequence++
    $id = [long]$script:cdpSequence
    $request = @{ id = $id; method = $Method; params = $Arguments } | ConvertTo-Json -Compress -Depth 4
    $bytes = [Text.Encoding]::UTF8.GetBytes($request)
    $token = [Threading.CancellationTokenSource]::new($Timeout)
    $scratch = [byte[]]::new(8192)
    $stream = [IO.MemoryStream]::new()
    $operation = 'send'
    $received = 0
    try {
        $null = $ws.SendAsync([ArraySegment[byte]]::new($bytes), [Net.WebSockets.WebSocketMessageType]::Text,
                      $true, $token.Token).GetAwaiter().GetResult()
        $operation = 'receive'
        while ($received -lt 128) {
            $stream.SetLength(0)
            do {
                $part = $ws.ReceiveAsync([ArraySegment[byte]]::new($scratch), $token.Token).GetAwaiter().GetResult()
                if ($part.MessageType -ne [Net.WebSockets.WebSocketMessageType]::Text) { throw 'DevTools closed early.' }
                $stream.Write($scratch, 0, $part.Count)
                if ($stream.Length -gt 65536) { throw 'Unexpected DevTools message length.' }
            } while (-not $part.EndOfMessage)
            $received++
            $message = [Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
            if (-not $message.PSObject.Properties['id']) { continue } # Events have no reply id.
            if ($message.id -ne $id) { throw "Unexpected response id $($message.id)." }
            if ($message.error) { throw "DevTools returned error code $($message.error.code)." }
            return $message.result
        }
        throw 'Too many DevTools events before the response.'
    } catch {
        throw "Edge DevTools $Phase ($Method id $id; $operation; $received complete messages): $($_.Exception.GetBaseException().Message)"
    } finally {
        $stream.Dispose()
        $token.Dispose()
    }
}
function Eval([string]$Expression, [string]$Phase = 'synthetic DOM check') {
    $outcome = CDP 'Runtime.evaluate' @{expression = $Expression; returnByValue = $true} -Phase $Phase
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

function Log-LaunchHistograms {
    # Browser-side CDP remains available even without a working renderer.
    # Log only names and numeric buckets from the fresh synthetic profile.
    foreach ($query in @('BrowserRenderProcessHost.ChildLaunch', 'ChildProcess.LaunchFailed', 'Process.Sandbox.Launch')) {
        try {
            $snapshot = CDP 'Browser.getHistograms' @{query = $query} -Timeout 2000 -Phase 'child startup telemetry'
            $histograms = @($snapshot.histograms | Where-Object {
                $_.name -match '^(ChildProcess\.LaunchFailed|Process\.Sandbox\.Launch)(\.[A-Za-z0-9_.]{1,80})?$' -or
                $_.name -eq 'BrowserRenderProcessHost.ChildLaunchFailureCodes'
            } | Sort-Object @{Expression={ if ($_.name -match 'Error|Result|Fail') {0} else {1} }} |
                Select-Object -First 12)
            Write-Output "Edge startup histogram query $query : $($histograms.Count) matches."
            foreach ($histogram in $histograms) {
                $buckets = @($histogram.buckets | Where-Object { $_.count -gt 0 } | Select-Object -First 8 |
                    ForEach-Object { '[{0},{1})x{2}' -f [long]$_.low, [long]$_.high, [long]$_.count })
                Write-Output "Edge startup histogram $($histogram.name) count=$([long]$histogram.count) buckets=$($buckets -join ',')."
            }
        } catch { Write-Output $_.Exception.Message }
    }
}

function Trace-SyntheticLowBox {
    # The hosted SDK may have CDB. Trace only a new NoteVive probe process
    # under this same ordinary account. Do not attach to Edge or the runner.
    $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\Debuggers\x64\cdb.exe'
    if (-not (Test-Path -LiteralPath $kits -PathType Leaf)) {
        Write-Output 'Synthetic LowBox trace: x64 SDK debugger absent.'
        return
    }
    $symbols = Join-Path $work 'local-symbols-only'
    $null = [IO.Directory]::CreateDirectory($symbols)
    $rawLog = Join-Path $work 'private-lowbox-debugger.log'
    # CDB is x64. For directory open/create, RCX is the output handle
    # pointer, EDX is ACCESS_MASK, R8 is OBJECT_ATTRIBUTES.
    # The debugger keeps all object names in the disposable profile.
    $directoryEntry = @'
.printf "NV_DIR_WANT=%08x\n", @edx
.if (@r8 != 0) { .printf "NV_DIR_ROOT=%p flags=%08x\n", poi(@r8+8), dwo(@r8+0x18); .if (poi(@r8+0x10) != 0) { .printf "NV_DIR_NAME=%msu\n", poi(@r8+0x10) } }
.if (@r8 != 0) { .if (poi(@r8+8) != 0) { r @$t2=poi(@r8+8); !handle @$t2 4 } }
bp /1 poi(@rsp) "$$><nv-directory-return.txt"
gc
'@
    $statusEntry = @'
bp /1 poi(@rsp) "$$><nv-directory-return.txt"
gc
'@
    $directoryCalls = @('NtOpenDirectoryObject', 'NtCreateDirectoryObject', 'NtCreateDirectoryObjectEx')
    $statusCalls = @('NtQuerySecurityObject', 'NtSetSecurityObject', 'NtCreateLowBoxToken')
    foreach ($call in ($directoryCalls + $statusCalls)) {
        # For calls without a directory OBJECT_ATTRIBUTES, record only their
        # allowlisted name and return status, never their arguments.
        $entry = if ($directoryCalls -contains $call) { $directoryEntry } else { $statusEntry }
        ".echo NV_NT_CALL=$call`r`n$entry" | Set-Content -LiteralPath (Join-Path $work "nv-$call.txt") -Encoding Ascii
    }
    @'
.printf "NV_DIR_STATUS=%08x\n", @eax
gc
'@ | Set-Content -LiteralPath (Join-Path $work 'nv-directory-return.txt') -Encoding Ascii
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $kits
    $start.Arguments = '-G -sins -nosqm -noshell -netsyms:no -y "{0}" -logo "{1}" -c "bu kernelbase!CreateAppContainerToken;g" "{2}" --edge-lowbox-trace' -f $symbols, $rawLog, $ProbeExe
    $start.WorkingDirectory = $work
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $debugger = $null
    try {
        $debugger = [Diagnostics.Process]::Start($start)
        $stdout = $debugger.StandardOutput.ReadToEndAsync()
        $stderr = $debugger.StandardError.ReadToEndAsync()
        # Install the NT breakpoint only after stopping at the exported
        # factory and quit as soon as that one factory call returns.
        $debugger.StandardInput.WriteLine('bc *')
        $debugger.StandardInput.WriteLine('bp /1 poi(@rsp) ".echo NV_FACTORY_RETURN; q"')
        foreach ($call in ($directoryCalls + $statusCalls)) {
            $debugger.StandardInput.WriteLine(('bu ntdll!{0} "$$><nv-{0}.txt"' -f $call))
        }
        $debugger.StandardInput.WriteLine('g')
        $debugger.StandardInput.Flush()
        if (-not $debugger.WaitForExit(18000)) {
            Write-Output 'Synthetic LowBox trace: debugger deadline reached.'
            $debugger.Kill()
            $null = $debugger.WaitForExit(1000)
        }
        if (-not $stdout.Wait(1500) -or -not $stderr.Wait(1500)) {
            Write-Output 'Synthetic LowBox trace: debugger stream did not close.'
            return
        }
        function Classify-ObjectName([string]$Name) {
            switch -Regex ($Name.Trim()) {
                '^\\Sessions\\\d+\\BaseNamedObjects\\AppContainerNamedObjects\\?$' { return 'session-base-alias' }
                '^\\Sessions\\\d+\\AppContainerNamedObjects\\?$' { return 'session-app-root' }
                '^\\Sessions\\\d+\\AppContainerNamedObjects\\.+' { return 'session-app-child' }
                '^\\Sessions\\\d+\\BaseNamedObjects\\?$' { return 'session-base-root' }
                '^\\?AppContainerNamedObjects\\?$' { return 'root-or-relative-app' }
                '^\\?AppContainerNamedObjects\\.+' { return 'root-or-relative-app-child' }
                '(?:^|\\)S-1-5-5-\d+-\d+(?:\\|$)' { return 'logon-component' }
                '^$|^<none>$' { return 'absent' }
                '^\\' { return 'other-absolute' }
                default { return 'other-relative' }
            }
        }
        $raw = if (Test-Path -LiteralPath $rawLog -PathType Leaf) { Get-Content -LiteralPath $rawLog -Raw } else { $stdout.Result }
        $pending = $null
        $kept = 0
        foreach ($line in ($raw -split "`r?`n")) {
            if ($line -match '^\s*NV_NT_CALL=(?<call>Nt(?:OpenDirectoryObject|CreateDirectoryObject(?:Ex)?|CreateLowBoxToken|QuerySecurityObject|SetSecurityObject))\s*$') {
                $pending = @{call=$Matches.call; mask='none'; root='unknown'; root_name='unknown'; flags='unknown'; name='absent'}
            } elseif ($pending -and $line -match '^\s*NV_DIR_WANT=(?<mask>[0-9a-f]{8})\s*$') {
                $pending.mask = '0x' + $Matches.mask
            } elseif ($pending -and $line -match '^\s*NV_DIR_ROOT=(?<root>[0-9a-f`]+) flags=(?<flags>[0-9a-f]{8})\s*$') {
                $rootHandle = $Matches.root
                $pending.flags = $Matches.flags
                $pending.root = if ($rootHandle -match '^0+`?0*$') { 'null' } else { 'handle' }
            } elseif ($pending -and $line -match '^\s*NV_DIR_NAME=(?<name>.*)$') {
                $pending.name = Classify-ObjectName $Matches.name
            } elseif ($pending -and $line -match '^\s+Name\s+(?<name>.*)$') {
                $pending.root_name = Classify-ObjectName $Matches.name
            } elseif ($pending -and $line -match '^\s*NV_DIR_STATUS=(?<status>[0-9a-f]{8})\s*$') {
                $status = $Matches.status
                $kept++
                if ($kept -le 32) {
                    Write-Output "Synthetic LowBox $($pending.call): mask=$($pending.mask) root=$($pending.root) root_kind=$($pending.root_name) flags=$($pending.flags) name_kind=$($pending.name) ntstatus=0x$status"
                }
                $pending = $null
            }
        }
        Write-Output "Synthetic LowBox trace: captured_calls=$kept; factory_return=$($raw -match '(?m)^\s*NV_FACTORY_RETURN\s*$'); debugger_exited=$($debugger.HasExited)."
        if (-not $kept) {
            $diagnosis = $raw + $stderr.Result
            Write-Output "Synthetic LowBox trace state: factory_symbol=$($diagnosis -match 'kernelbase!CreateAppContainerToken'); entry_command=$($diagnosis -match 'nv-NtOpenDirectoryObject'); command_error=$($diagnosis -match '(?i)syntax error|unknown option|unable to|could not|couldn.t|error code')."
        }
    } catch {
        # Do not print raw debugger command lines/paths.
        Write-Output "Synthetic LowBox trace: debugger failed ($($_.Exception.GetBaseException().GetType().Name))."
    } finally {
        if ($debugger) {
            if (-not $debugger.HasExited) { $debugger.Kill() }
            $debugger.Dispose()
        }
    }
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
    foreach ($debug in @($launchLog, (Join-Path $profile 'chrome_debug.log'), (Join-Path $profile 'msedge_debug.log'))) {
        if (Test-Path -LiteralPath $debug -PathType Leaf) {
            $tail = @(Get-Content -LiteralPath $debug -Tail 160 -ErrorAction SilentlyContinue)
            $relevant = @($tail | Where-Object {
                $_ -match '\b(sandbox|broker|renderer|create_process|child_process_launcher|win32k|access.+denied)\b'
            } | Select-Object -Last 12)
            if (-not $relevant.Count) { $relevant = @($tail | Select-Object -Last 4) }
            foreach ($line in $relevant) {
                Write-Output ('Edge startup log: ' + $line.Substring(0, [Math]::Min($line.Length, 400)))
            }
        }
    }
    if ($browserConnection -and $browserConnection.State -eq [Net.WebSockets.WebSocketState]::Open) {
        # Query the disposable browser only, excluding unrelated processes,
        # file paths and command lines.
        $ws = $browserConnection
        try {
            $processes = CDP 'SystemInfo.getProcessInfo' -Timeout 2500 -Phase 'browser process diagnosis'
            $processes.processInfo | Group-Object -Property type | ForEach-Object {
                if ($_.Name -match '^[A-Za-z0-9 _-]{1,32}$') { Write-Output "Edge profile process role $($_.Name): $($_.Count)" }
            }
        } catch { Write-Output $_.Exception.Message }
        if ($browserConnection.State -eq [Net.WebSockets.WebSocketState]::Open) { Log-LaunchHistograms }
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
$launchLog = Join-Path $work 'edge-startup.log'
$edge = $null; $probe = $null; $ws = $null; $browserConnection = $null
$script:cdpSequence = 0
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
        '--enable-logging', "--log-file=`"$launchLog`"",
        '--vmodule=child_process_launcher_helper*=1,sandbox_win=1,broker_services=1,render_process_host_impl=1',
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
    if ($HostedRecipe) {
        & $ProbeExe --edge-startup-preflight
        $preflight = $LASTEXITCODE
        if ($preflight -eq 2) {
            Write-Output 'Synthetic AppContainer creation failed; the actual Edge recipe will still run with its sandbox.'
            try { Trace-SyntheticLowBox } catch { Write-Output 'Synthetic LowBox trace could not prepare its private scratch files.' }
        } elseif ($preflight -ne 0) {
            throw 'The ordinary-user browser preflight did not verify the account, job or local mutex.'
        }
    }
    $edge = [Diagnostics.Process]::Start($browserStart)
    Wait-Until {
        if ($edge.HasExited) { throw 'The isolated Edge process exited during startup.' }
        if (-not (Test-Path -LiteralPath $portFile -PathType Leaf)) { return $false }
        try {
            $lines = @(Get-Content -LiteralPath $portFile -TotalCount 2)
            return $lines.Count -eq 2 -and $lines[0] -match '^\d+$' -and
                $lines[1] -match '^/devtools/browser/[0-9a-fA-F-]{36}$'
        } catch { return $false }
    } 'Disposable Edge profile did not start DevTools.' 25000
    $lines = @(Get-Content -LiteralPath $portFile -TotalCount 2)
    $port = [int]$lines[0]
    Require ($port -gt 0 -and $port -lt 65536) 'Bad loopback port.'
    $browserConnection = Connect-DevTools ([Uri]"ws://127.0.0.1:$port$($lines[1])") 'browser'
    $ws = $browserConnection
    $browserInfo = CDP 'Browser.getVersion' -Timeout 12000 -Phase 'browser channel readiness'
    Require ($null -ne $browserInfo.protocolVersion) 'The isolated browser did not identify its CDP protocol.'
    Write-Output 'Edge browser DevTools channel ready.'
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
    Require ($socket.Scheme -eq 'ws' -and $socket.IsLoopback -and $socket.Port -eq $port -and
        $socket.AbsolutePath -match '^/devtools/page/[0-9a-fA-F]+$') 'Not a loopback DevTools page target.'
    $ws = Connect-DevTools $socket 'page'
    $null = CDP 'Page.bringToFront' -Timeout 22000 -Phase 'activate synthetic page'
    Wait-Until { Eval 'document.readyState === "complete" && document.hasFocus()' 'wait for focused renderer' } 'The disposable Edge window did not become active.' 20000
    Write-Output 'Edge synthetic page is active; starting external input checks.'

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
    if ($ws -and $ws -ne $browserConnection) { $ws.Dispose() }
    if ($browserConnection) { $browserConnection.Dispose() }
    if ($edge) {
        # Keep process cleanup bound to the instance handle. In hosted CI
        # the launcher separately verifies the disposable SID's process list.
        if (-not $edge.HasExited) { $edge.Kill() }
        $edge.Dispose()
    }
    Remove-Item -LiteralPath $work -Force -Recurse -ErrorAction SilentlyContinue
}
