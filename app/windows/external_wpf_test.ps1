# Test the production UI Automation + SendInput lane against synthetic WPF
# controls. This is not an Edge, Word, microphone or clipboard test.
[CmdletBinding(DefaultParameterSetName = 'Test')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Test')][string]$ProbeExe,
    [Parameter(Mandatory, ParameterSetName = 'Fixture')][switch]$Fixture
)
$ErrorActionPreference = 'Stop'

function Assert-Wpf([bool]$Condition, [string]$Failure) {
    if (-not $Condition) { throw $Failure }
}

if ($Fixture) {
    Assert-Wpf ([Threading.Thread]::CurrentThread.GetApartmentState() -eq 'STA') 'The WPF fixture needs an STA process.'
    Add-Type -AssemblyName PresentationFramework
    $window = [Windows.Window]::new()
    $window.Title = 'NoteVive test - synthetic WPF input'
    $window.Width = 490
    $window.Height = 280
    $window.WindowStartupLocation = 'CenterScreen'
    $panel = [Windows.Controls.StackPanel]::new()
    $panel.Margin = [Windows.Thickness]::new(18)
    $window.Content = $panel

    $controls = @{}
    $initialText = @{a = 'ab'; b = 'cd'; readonly = 'locked'}
    foreach ($name in @('a', 'b', 'readonly', 'password')) {
        $label = [Windows.Controls.TextBlock]::new()
        $label.Text = $name
        $null = $panel.Children.Add($label)
        if ($name -eq 'password') {
            $field = [Windows.Controls.PasswordBox]::new()
            $field.Password = 'fictitious'
        } else {
            $field = [Windows.Controls.TextBox]::new()
            $field.Text = $initialText[$name]
            $field.IsReadOnly = $name -eq 'readonly'
        }
        $field.Margin = [Windows.Thickness]::new(0, 0, 0, 8)
        $controls[$name] = $field
        $null = $panel.Children.Add($field)
    }

    # Console.In may wrap synchronous reads. Read the redirected stream
    # directly and only collect a completed task on the UI dispatcher.
    $reader = [IO.StreamReader]::new([Console]::OpenStandardInput(), [Text.Encoding]::UTF8)
    $state = @{ Read = $reader.ReadLineAsync(); Field = $null; Selected = $false; Since = $null; Stable = 0; Failed = $false }
    $timer = [Windows.Threading.DispatcherTimer]::new()
    $timer.Interval = [TimeSpan]::FromMilliseconds(25)
    $window.Add_Closed({
        $timer.Stop()
        $window.Dispatcher.BeginInvokeShutdown([Windows.Threading.DispatcherPriority]::Normal)
    })
    $timer.Add_Tick({
        try {
            if ($state.Field) {
                if ($window.IsActive -and $state.Field.IsKeyboardFocused) { ++$state.Stable } else { $state.Stable = 0 }
                if ($state.Stable -ge 2) {
                    if ($state.Field -is [Windows.Controls.TextBox]) {
                        $start = if ($state.Selected) { 0 } else { 1 }
                        $length = if ($state.Selected) { 1 } else { 0 }
                        Assert-Wpf ($state.Field.SelectionStart -eq $start -and $state.Field.SelectionLength -eq $length) 'Fixture caret or selection differed.'
                    }
                    $state.Field = $null
                    [Console]::WriteLine('focused')
                    $state.Read = $reader.ReadLineAsync()
                } elseif ($state.Since.ElapsedMilliseconds -ge 2500) {
                    throw 'The synthetic WPF field did not receive foreground keyboard focus.'
                }
                return
            }
            if (-not $state.Read.IsCompleted) { return }
            $command = $state.Read.GetAwaiter().GetResult()
            if ($null -eq $command -or $command -ceq 'quit') {
                $window.Close()
                return
            }
            if ($command -ceq 'snapshot') {
                $record = @{
                    a = $controls['a'].Text; b = $controls['b'].Text; readonly = $controls['readonly'].Text
                    passwordUnchanged = $controls['password'].Password -ceq 'fictitious'
                } | ConvertTo-Json -Compress
                [Console]::WriteLine([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($record)))
                $state.Read = $reader.ReadLineAsync()
                return
            }
            if ($command -cnotmatch '^focus-(a|b|selected|readonly|password)$') { throw 'Unknown WPF fixture command.' }
            $name = $command.Substring(6)
            $state.Selected = $name -eq 'selected'
            $state.Field = if ($state.Selected) { $controls['a'] } else { $controls[$name] }
            $state.Stable = 0
            $state.Since = [Diagnostics.Stopwatch]::StartNew()
            if (-not $window.IsActive) { $null = $window.Activate() }
            $null = [Windows.Input.Keyboard]::Focus($state.Field)
            if ($state.Field -is [Windows.Controls.TextBox]) {
                if ($state.Selected) { $state.Field.Select(0, 1) } else { $state.Field.Select(1, 0) }
            }
        } catch {
            $state.Failed = $true
            [Console]::Error.WriteLine($_.Exception.Message)
            $window.Close()
        }
    })
    $window.Show()
    $timer.Start()
    [Console]::WriteLine('WPF')
    [Windows.Threading.Dispatcher]::Run()
    $reader.Dispose()
    if ($state.Failed) { exit 1 }
    exit 0
}

Assert-Wpf ([Environment]::UserInteractive) 'Run the WPF recipe on an interactive Windows desktop.'
$sidLines = & "$env:SystemRoot\System32\whoami.exe" /groups /fo csv /nh
Assert-Wpf ($LASTEXITCODE -eq 0) 'Unable to inspect the Windows test identity.'
$integrity = [regex]::Match(($sidLines -join "`n"), 'S-1-16-(\d+)')
Assert-Wpf ($integrity.Success -and [int]$integrity.Groups[1].Value -eq 8192) 'Run the WPF recipe with an ordinary Medium Windows token.'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
try {
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    Assert-Wpf (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'The WPF recipe must not run elevated.'
} finally { $identity.Dispose() }

$ProbeExe = (Resolve-Path -LiteralPath $ProbeExe).Path
$clock = [Diagnostics.Stopwatch]::StartNew()
function Start-WpfChild([string]$File, [string]$Arguments) {
    $info = [Diagnostics.ProcessStartInfo]::new($File, $Arguments)
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardInput = $true
    return [Diagnostics.Process]::Start($info)
}
function Remaining-WpfTime([int]$Cap) { return [Math]::Max(0, [Math]::Min($Cap, 65000 - [int]$clock.ElapsedMilliseconds)) }
function Read-WpfReply([Diagnostics.Process]$Child, [string]$Step) {
    $task = $Child.StandardOutput.ReadLineAsync()
    Assert-Wpf ($task.Wait((Remaining-WpfTime 9000)) -and $null -ne $task.Result) "No WPF-recipe reply for $Step."
    return $task.Result
}
function Send-WpfCommand([Diagnostics.Process]$Child, [string]$Command) {
    $Child.StandardInput.WriteLine($Command)
    $Child.StandardInput.Flush()
}
function Require-WpfReply([Diagnostics.Process]$Child, [string]$Command, [string]$Expected) {
    if ($Command) { Send-WpfCommand $Child $Command }
    $actual = Read-WpfReply $Child $(if ($Command) { $Command } else { 'startup' })
    Assert-Wpf ($actual -ceq $Expected) "WPF-recipe command '$Command': expected '$Expected'; received '$actual'."
}
function Assert-WpfText([string]$First, [string]$Second, [string]$Step, [switch]$WaitForText) {
    $wait = [Diagnostics.Stopwatch]::StartNew()
    do {
        Send-WpfCommand $fixtureProcess 'snapshot'
        $response = Read-WpfReply $fixtureProcess 'snapshot'
        $record = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($response)) | ConvertFrom-Json
        Assert-Wpf ($record.readonly -ceq 'locked' -and $record.passwordUnchanged -eq $true) "A protected WPF field changed at $Step."
        if ($record.a -ceq $First -and $record.b -ceq $Second) { return }
        if ($WaitForText) { Start-Sleep -Milliseconds 30 }
    } while ($WaitForText -and $wait.ElapsedMilliseconds -lt 2500)
    throw "The fictitious WPF text was incorrect at $Step."
}
function Stop-WpfChild([Diagnostics.Process]$Child) {
    if (-not $Child) { return }
    try {
        if (-not $Child.HasExited) {
            $Child.Kill()
            Assert-Wpf ($Child.WaitForExit(1500)) 'A WPF recipe child did not stop at cleanup.'
        }
    } finally { $Child.Dispose() }
}

$fixtureProcess = $null
$probe = $null
try {
    $powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $fixtureProcess = Start-WpfChild $powerShell ('-NoProfile -NonInteractive -STA -File "{0}" -Fixture' -f $PSCommandPath)
    Require-WpfReply $fixtureProcess '' 'WPF'
    $probe = Start-WpfChild $ProbeExe "--edge-probe $($fixtureProcess.Id)"
    Require-WpfReply $probe '' 'OK'
    Assert-WpfText 'ab' 'cd' 'start'
    $unicode = [string][char]0xe9 + ' ' + [char]0xbd
    $first = 'a' + $unicode + 'b'
    $second = 'c' + $unicode + 'd'

    Require-WpfReply $fixtureProcess 'focus-a' 'focused'
    Require-WpfReply $probe 'capture' 'ready'
    Require-WpfReply $probe 'send' 'submitted'
    Assert-WpfText $first 'cd' 'first Unicode insertion' -WaitForText
    Require-WpfReply $fixtureProcess 'focus-b' 'focused'
    Require-WpfReply $probe 'check-change' 'target_changed'
    Require-WpfReply $fixtureProcess 'focus-a' 'focused'
    Require-WpfReply $probe 'send' 'target_changed'
    Assert-WpfText $first 'cd' 'invalidated target'
    Require-WpfReply $probe 'reset' 'inactive'

    foreach ($case in @(@('focus-selected', 'unsupported'), @('focus-readonly', 'unsupported'), @('focus-password', 'protected_field'))) {
        Require-WpfReply $fixtureProcess $case[0] 'focused'
        Require-WpfReply $probe 'capture' $case[1]
        Assert-WpfText $first 'cd' $case[0]
        Require-WpfReply $probe 'reset' 'inactive'
    }

    Require-WpfReply $fixtureProcess 'focus-b' 'focused'
    Require-WpfReply $probe 'capture' 'ready'
    Require-WpfReply $probe 'send' 'submitted'
    Assert-WpfText $first $second 'fresh capture in the second field' -WaitForText
    Send-WpfCommand $probe 'quit'
    Assert-Wpf ($probe.WaitForExit((Remaining-WpfTime 4000)) -and $probe.ExitCode -eq 0) 'The production-path probe did not shut down cleanly.'
    Send-WpfCommand $fixtureProcess 'quit'
    Assert-Wpf ($fixtureProcess.WaitForExit((Remaining-WpfTime 4000)) -and $fixtureProcess.ExitCode -eq 0) 'The WPF fixture did not shut down cleanly.'
    Write-Output 'WPF UI Automation / SendInput: exact Unicode, unrelated fields, focus invalidation, selection and protected fields passed.'
} finally {
    try { Stop-WpfChild $probe } finally { Stop-WpfChild $fixtureProcess }
}
