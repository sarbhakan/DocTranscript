# Requires an interactive Windows desktop and a dedicated, disposable user.
# The smoke does not open the microphone, replay audio, or modify real notes.
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Executable)
$ErrorActionPreference = 'Stop'
if (-not [Environment]::UserInteractive) { throw 'An interactive Windows desktop is required.' }
$Executable = (Resolve-Path -LiteralPath $Executable).Path
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class NvWindow {
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out Rect rect);
    [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr hwnd, int id);
    [DllImport("user32.dll", EntryPoint = "PostMessageW", ExactSpelling = true)] public static extern bool Post(IntPtr hwnd, uint msg, IntPtr wp, IntPtr lp);
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", ExactSpelling = true)]
    static extern IntPtr SendBounded(IntPtr hwnd, uint msg, IntPtr wp, IntPtr lp, uint flags, uint timeout, out UIntPtr result);
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", ExactSpelling = true, CharSet = CharSet.Unicode)]
    static extern IntPtr ReadBounded(IntPtr hwnd, uint msg, IntPtr wp, StringBuilder buf, uint flags, uint timeout, out UIntPtr result);
    static int Send(IntPtr hwnd, uint msg, IntPtr wp, IntPtr lp) {
        UIntPtr result;
        if (SendBounded(hwnd, msg, wp, lp, 0x0002, 2000, out result) == IntPtr.Zero)
            throw new TimeoutException("The NoteVive window did not answer the native smoke test.");
        return unchecked((int)result.ToUInt64());
    }
    public static string Text(IntPtr hwnd) {
        int length = Send(hwnd, 0x000e, IntPtr.Zero, IntPtr.Zero); // WM_GETTEXTLENGTH
        StringBuilder text = new StringBuilder(length + 1);
        UIntPtr result;
        if (ReadBounded(hwnd, 0x000d, new IntPtr(length + 1), text, 0x0002, 2000, out result) == IntPtr.Zero)
            throw new TimeoutException("The NoteVive edit control did not answer the native smoke test.");
        return text.ToString();
    }
    public static void Type(IntPtr hwnd, string text) {
        Send(hwnd, 0x00b1, IntPtr.Zero, new IntPtr(-1)); // EM_SETSEL
        Send(hwnd, 0x0102, new IntPtr(8), new IntPtr(1)); // WM_CHAR: delete selection
        foreach (char ch in text) Send(hwnd, 0x0102, new IntPtr(ch), new IntPtr(1));
    }
    public static bool ChooseSort(IntPtr parent, IntPtr combo, int index) {
        if (Send(combo, 0x014e, new IntPtr(index), IntPtr.Zero) != index) return false; // CB_SETCURSEL
        return Post(parent, 0x0111, new IntPtr((1 << 16) | 113), combo); // WM_COMMAND / CBN_SELCHANGE
    }
}
'@
$root = [System.Windows.Automation.AutomationElement]::RootElement
$enumScope = [System.Windows.Automation.TreeScope]::Descendants
$idProperty = [System.Windows.Automation.AutomationElement]::AutomationIdProperty
$nameProperty = [System.Windows.Automation.AutomationElement]::NameProperty
$classProperty = [System.Windows.Automation.AutomationElement]::ClassNameProperty
$processProperty = [System.Windows.Automation.AutomationElement]::ProcessIdProperty
$typeProperty = [System.Windows.Automation.AutomationElement]::ControlTypeProperty
$listItemType = [System.Windows.Automation.ControlType]::ListItem
$selection = [System.Windows.Automation.SelectionItemPattern]::Pattern
$expand = [System.Windows.Automation.ExpandCollapsePattern]::Pattern
$prefix = "NVTEST-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$testProfile = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)) 'NoteVive-Pilote'
$records = Join-Path $testProfile 'notes'
$testNote = "$prefix B"
$testOlder = "$prefix A"
$testFolder = "$prefix parent"
$testChild = "$prefix enfant"
$testRenamed = "$prefix classe"
$marker = "$prefix marqueur éphémère."
$process = $null

if (Get-Process -Name NoteVive -ErrorAction SilentlyContinue) { throw 'Close all NoteVive instances first.' }
if (Test-Path -LiteralPath $testProfile) {
    throw "Use a fresh test user. Existing NoteVive storage was not modified: $testProfile"
}

function Wait-For([scriptblock]$Predicate, [string]$Description) {
    $timeout = [Diagnostics.Stopwatch]::StartNew()
    do {
        try { $found = & $Predicate } catch [System.Windows.Automation.ElementNotAvailableException] { $found = $null }
        if ($found) { return $found }
        Start-Sleep -Milliseconds 75
    } while ($timeout.Elapsed.TotalSeconds -lt 12)
    throw "Timed out: $Description"
}

function Condition($Property, $Expected) {
    return [System.Windows.Automation.PropertyCondition]::new($Property, $Expected)
}

function In-Window($Property, $Expected) {
    $app.FindFirst($enumScope, (Condition $Property $Expected))
}

function ById([int]$Control) {
    Wait-For { In-Window $idProperty ([string]$Control) } "find control $Control"
}

function ByName($Parent, [string]$Name) {
    Wait-For { $Parent.FindFirst($enumScope, (Condition $nameProperty $Name)) } "find '$Name'"
}

function Test-NoteVisible([string]$Name) {
    $noteList = ById 106
    $items = $noteList.FindAll($enumScope, (Condition $typeProperty $listItemType))
    foreach ($item in $items) {
        if ($item.Current.Name.StartsWith("$Name · ", [StringComparison]::Ordinal)) { return $item }
    }
    return $null
}

function Window-Handle($Element) { return [IntPtr]$Element.Current.NativeWindowHandle }

function Click($Element) {
    if (-not $Element.Current.IsEnabled) { throw "Button is disabled: $($Element.Current.Name)" }
    if (-not [NvWindow]::Post((Window-Handle $Element), 0x00f5, [IntPtr]::Zero, [IntPtr]::Zero)) { # BM_CLICK
        throw "Cannot click: $($Element.Current.Name)"
    }
}

function Input-Text($Element, [string]$Text) {
    if (-not $Element.Current.IsEnabled) { throw 'Edit control is disabled.' }
    $Element.SetFocus()
    $handle = Window-Handle $Element
    [NvWindow]::Type($handle, $Text)
    if ([NvWindow]::Text($handle) -cne $Text) { throw 'The edit control did not accept the fictitious text.' }
}

function Begin-App {
    $script:process = Start-Process -FilePath $Executable -WorkingDirectory (Split-Path $Executable) -PassThru
    $script:app = Wait-For {
        if ($process.HasExited) { throw "NoteVive exited ($($process.ExitCode))." }
        $match = [System.Windows.Automation.AndCondition]::new([System.Windows.Automation.Condition[]]@(
            (Condition $processProperty $process.Id),
            (Condition $classProperty 'NoteVivePrototypeWindow')))
        $candidate = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $match)
        if ($candidate -and -not $candidate.Current.IsOffscreen) { $candidate }
    } 'visible NoteVive window'
    $bounds = New-Object NvWindow+Rect
    if (-not [NvWindow]::GetWindowRect([IntPtr]$app.Current.NativeWindowHandle, [ref]$bounds) -or
        ($bounds.Right - $bounds.Left) -lt 450 -or ($bounds.Bottom - $bounds.Top) -lt 380 -or
        $app.Current.IsOffscreen) {
        throw 'The NoteVive main window is too small or off-screen.'
    }
}

function End-App {
    if (-not [NvWindow]::Post((Window-Handle $app), 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)) { throw 'Cannot close NoteVive.' }
    if (-not $process.WaitForExit(12000)) { throw 'NoteVive did not close cleanly.' }
    if ($process.ExitCode -ne 0) { throw "NoteVive shutdown failed ($($process.ExitCode))." }
}

function Find-Dialog([string]$Caption) {
    $match = [System.Windows.Automation.AndCondition]::new([System.Windows.Automation.Condition[]]@(
        (Condition $processProperty $process.Id), (Condition $nameProperty $Caption)))
    Wait-For {
        $window = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $match)
        if (-not $window) { $window = $app.FindFirst($enumScope, $match) }
        $window
    } "open '$Caption' dialog"
}

function Confirm-Dialog($Dialog) {
    $accept = $Dialog.FindFirst($enumScope, (Condition $idProperty '1'))
    if (-not $accept -or -not $accept.Current.IsEnabled) { throw 'Cannot find the confirmation button.' }
    # Send BN_CLICKED to the dialog: unlike BM_CLICK it works without foreground activation.
    if (-not [NvWindow]::Post((Window-Handle $Dialog), 0x0111, [IntPtr]1, (Window-Handle $accept))) {
        throw 'Cannot confirm the action.'
    }
}

function Folder-Dialog([string]$Caption, [string]$Text) {
    $dialog = Find-Dialog $Caption
    $edit = Wait-For { $dialog.FindFirst($enumScope, (Condition $idProperty '100')) } "find '$Caption' text field"
    Input-Text $edit $Text
    Confirm-Dialog $dialog
}

function Editor-Folder {
    return [NvWindow]::Text([NvWindow]::GetDlgItem((Window-Handle $app), 120))
}

function Move-Note([string]$Destination) {
    Click (ById 116)
    $dialog = Find-Dialog 'Classer la transcription'
    (ByName $dialog $Destination).GetCurrentPattern($selection).Select()
    Confirm-Dialog $dialog
    $null = Wait-For { (Editor-Folder) -ceq $Destination } "move note to '$Destination'"
}

function Sorted-Names {
    $list = (ById 106).FindAll($enumScope, (Condition $typeProperty $listItemType))
    return @($list | Where-Object { $_.Current.Name.StartsWith($prefix, [StringComparison]::Ordinal) } |
        ForEach-Object { $_.Current.Name })
}

try {
    Begin-App
    $null = ById 110 # Dossiers tree sidebar.
    $null = ById 111 # Search.
    Click (ById 114) # New top-level folder.
    Folder-Dialog 'Nouveau dossier' $testFolder
    $parent = ByName (ById 110) $testFolder
    $parent.GetCurrentPattern($selection).Select()
    Click (ById 114) # Child of selected folder.
    Folder-Dialog 'Nouveau dossier' $testChild
    $null = ByName (ById 110) $testChild

    # Type a title first, allow autosave, then verify title and body survive.
    Click (ById 101)
    $null = Wait-For { [NvWindow]::Text((Window-Handle (ById 107))) -eq '' } 'new editor clear'
    Input-Text (ById 107) $testOlder
    Input-Text (ById 108) $marker
    $null = Wait-For { Test-NoteVisible $testOlder } 'first note autosaved under child folder'
    Click (ById 101)
    $null = Wait-For { [NvWindow]::Text((Window-Handle (ById 107))) -eq '' } 'second editor clear'
    Input-Text (ById 107) $testNote
    Input-Text (ById 108) 'Deuxième transcription fictive.'
    Click (ById 103)
    $null = Wait-For { Test-NoteVisible $testNote } 'second note saved'
    $sort = Window-Handle (ById 113)
    if (-not [NvWindow]::ChooseSort((Window-Handle $app), $sort, 1)) { throw 'Cannot select creation date.' }
    $null = Wait-For { $names = @(Sorted-Names); $names.Count -eq 2 -and $names[0].StartsWith("$testNote · ") } 'newest creation first'
    if (-not [NvWindow]::ChooseSort((Window-Handle $app), $sort, 2)) { throw 'Cannot select title order.' }
    $null = Wait-For { $names = @(Sorted-Names); $names.Count -eq 2 -and $names[0].StartsWith("$testOlder · ") } 'French title order'

    # Verify closing flushes edits, then reopen and find the saved note by body only.
    Input-Text (ById 107) $testRenamed
    End-App
    Begin-App
    $parent = ByName (ById 110) $testFolder
    $parent.GetCurrentPattern($expand).Expand()
    $null = ByName $parent $testChild
    Input-Text (ById 111) 'marqueur ephemere'
    $note = Wait-For {
        $names = @(Sorted-Names)
        if ($names.Count -eq 1 -and $names[0].StartsWith("$testOlder · ")) { Test-NoteVisible $testOlder }
    } 'accent-insensitive query of saved body'
    $note.GetCurrentPattern($selection).Select()
    $null = Wait-For { [NvWindow]::Text((Window-Handle (ById 108))) -eq $marker } 'open saved body'
    Input-Text (ById 111) ''
    $renamed = Wait-For { Test-NoteVisible $testRenamed } 'renamed note persisted on close'
    $renamed.GetCurrentPattern($selection).Select()
    $null = Wait-For {
        $where = [NvWindow]::GetDlgItem((Window-Handle $app), 120)
        [NvWindow]::Text($where).Contains("$testFolder / $testChild")
    } 'persisted note links to the nested folder'
    Move-Note 'Sans dossier'
    Move-Note "$testFolder / $testChild"
    End-App
    $savedCount = @(Get-ChildItem -LiteralPath $records -Filter '*.nvn' -File).Count
    $folderCount = @(Get-ChildItem -LiteralPath $records -Filter '*.nvf' -File).Count
    if ($savedCount -ne 2 -or $folderCount -ne 2) { throw "Expected exactly two notes and folders, found $savedCount / $folderCount." }
    Write-Output 'Windows UI, nested folders, moving notes, sort, body search, autosave and close/reopen verified with fictitious text.'
} finally {
    if ($process -and -not $process.HasExited) {
        $process.CloseMainWindow() | Out-Null
        if (-not $process.WaitForExit(4000)) { $process.Kill(); $process.WaitForExit() }
    }
    # This profile did not exist before the smoke. Keep records on failure for inspection.
}
