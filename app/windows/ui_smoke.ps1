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
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr hwnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string className, string title);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr hwnd, StringBuilder name, int max);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll", EntryPoint = "PostMessageW", ExactSpelling = true)] public static extern bool Post(IntPtr hwnd, uint msg, IntPtr wp, IntPtr lp);
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", ExactSpelling = true)]
    static extern IntPtr SendBounded(IntPtr hwnd, uint msg, IntPtr wp, IntPtr lp, uint flags, uint timeout, out UIntPtr result);
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", ExactSpelling = true, CharSet = CharSet.Unicode)]
    static extern IntPtr ReadBounded(IntPtr hwnd, uint msg, IntPtr wp, StringBuilder buf, uint flags, uint timeout, out UIntPtr result);
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", ExactSpelling = true, CharSet = CharSet.Unicode)]
    static extern IntPtr WriteBounded(IntPtr hwnd, uint msg, IntPtr wp, string text, uint flags, uint timeout, out UIntPtr result);
    static UIntPtr SendRaw(IntPtr hwnd, uint msg, IntPtr wp, IntPtr lp) {
        UIntPtr result;
        if (SendBounded(hwnd, msg, wp, lp, 0x0022, 2000, out result) == IntPtr.Zero)
            throw new TimeoutException("The NoteVive window did not answer the native smoke test.");
        return result;
    }
    static int Send(IntPtr hwnd, uint msg, IntPtr wp, IntPtr lp) {
        return unchecked((int)SendRaw(hwnd, msg, wp, lp).ToUInt64());
    }
    public static string Text(IntPtr hwnd) {
        int length = Send(hwnd, 0x000e, IntPtr.Zero, IntPtr.Zero); // WM_GETTEXTLENGTH
        StringBuilder text = new StringBuilder(length + 1);
        UIntPtr result;
        if (ReadBounded(hwnd, 0x000d, new IntPtr(length + 1), text, 0x0002, 2000, out result) == IntPtr.Zero)
            throw new TimeoutException("The NoteVive edit control did not answer the native smoke test.");
        return text.ToString();
    }
    public static void ReplaceEditText(IntPtr hwnd, string text) {
        Send(hwnd, 0x00b1, IntPtr.Zero, new IntPtr(-1)); // EM_SETSEL
        UIntPtr result;
        // EM_REPLACESEL sends EN_CHANGE for both single- and multiline edits.
        if (WriteBounded(hwnd, 0x00c2, new IntPtr(1), text, 0x0002, 2000, out result) == IntPtr.Zero)
            throw new TimeoutException("The NoteVive edit control did not accept the replacement message.");
    }
    public static bool ChooseSort(IntPtr parent, IntPtr combo, int index) {
        if (Send(combo, 0x014e, new IntPtr(index), IntPtr.Zero) != index) return false; // CB_SETCURSEL
        return Post(parent, 0x0111, new IntPtr((1 << 16) | 113), combo); // WM_COMMAND / CBN_SELCHANGE
    }
    static IntPtr ListControl(IntPtr parent, int controlId) {
        IntPtr list = GetDlgItem(parent, controlId);
        var klass = new StringBuilder(32);
        if (list == IntPtr.Zero || GetClassName(list, klass, klass.Capacity) == 0 ||
            !string.Equals(klass.ToString(), "ListBox", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("The native NoteVive list box was not found.");
        return list;
    }
    public static string[] ListLabels(IntPtr parent, int controlId) {
        var list = ListControl(parent, controlId);
        int count = Send(list, 0x018b, IntPtr.Zero, IntPtr.Zero); // LB_GETCOUNT
        if (count < 0 || count > 16) throw new InvalidOperationException("Unexpected size of the isolated test list.");
        var labels = new string[count];
        for (int i = 0; i < count; ++i) {
            var index = new IntPtr(i);
            int length = Send(list, 0x018a, index, IntPtr.Zero); // LB_GETTEXTLEN
            if (length < 0) return null; // A pending refresh replaced the list; poll again.
            // Supply room for a full breadcrumb if a pending refresh changes the row.
            var caption = new StringBuilder(4096);
            if (length >= caption.Capacity) throw new InvalidOperationException("A native list label exceeded the test buffer.");
            UIntPtr result;
            if (ReadBounded(list, 0x0189, index, caption, 0x0022, 2000, out result) == IntPtr.Zero) // LB_GETTEXT
                throw new TimeoutException("The native NoteVive list did not answer the test.");
            if (unchecked((int)result.ToUInt64()) != length || caption.Length != length) return null;
            labels[i] = caption.ToString();
        }
        return labels;
    }
    public static bool SelectListRow(IntPtr parent, int controlId, string sought, bool noteTitle) {
        var list = ListControl(parent, controlId);
        if (!IsWindowEnabled(list)) throw new InvalidOperationException("The native NoteVive list is disabled.");
        var labels = ListLabels(parent, controlId);
        if (labels == null) return false;
        int index = -1;
        for (int i = 0; i < labels.Length; ++i) {
            bool match = noteTitle ? labels[i].StartsWith(sought + " · ", StringComparison.Ordinal) :
                string.Equals(labels[i], sought, StringComparison.Ordinal);
            if (!match) continue;
            if (index != -1) throw new InvalidOperationException("The test label is ambiguous in the native list.");
            index = i;
        }
        if (index < 0 || Send(list, 0x0186, new IntPtr(index), IntPtr.Zero) != index || // LB_SETCURSEL
            Send(list, 0x0188, IntPtr.Zero, IntPtr.Zero) != index) return false; // LB_GETCURSEL
        // Unlike user input, LB_SETCURSEL does not send LBN_SELCHANGE itself.
        Send(parent, 0x0111, new IntPtr((1 << 16) | controlId), list); // WM_COMMAND / LBN_SELCHANGE
        return true;
    }
    public static int TreeCount(IntPtr tree) {
        return Send(tree, 0x1105, IntPtr.Zero, IntPtr.Zero); // TVM_GETCOUNT
    }
    [StructLayout(LayoutKind.Sequential)] struct TreeItem {
        public uint Mask;
        public IntPtr Handle;
        public uint State, StateMask;
        public IntPtr Text;
        public int TextMax, Image, SelectedImage, Children;
        public IntPtr Param;
    }
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll")] static extern bool IsWow64Process2(IntPtr process, out ushort processMachine, out ushort nativeMachine);
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr VirtualAllocEx(IntPtr process, IntPtr addr, UIntPtr size, uint how, uint protection);
    [DllImport("kernel32.dll")] static extern bool VirtualFreeEx(IntPtr process, IntPtr addr, UIntPtr size, uint how);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool WriteProcessMemory(IntPtr process, IntPtr addr, byte[] data, UIntPtr size, out UIntPtr written);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool ReadProcessMemory(IntPtr process, IntPtr addr, [Out] byte[] data, UIntPtr size, out UIntPtr read);

    static IntPtr TreeNext(IntPtr tree, int relation, IntPtr item) {
        return new IntPtr(unchecked((long)SendRaw(tree, 0x110a, new IntPtr(relation), item).ToUInt64())); // TVM_GETNEXTITEM
    }
    public static bool FindTreePath(IntPtr tree, uint pid, string[] path, bool select) {
        // TVM_GETITEMW is not marshaled across processes. Limit access to one
        // scratch page owned by the launched fictitious-test process/window.
        uint owner;
        var klass = new StringBuilder(64);
        int itemSize = Marshal.SizeOf(typeof(TreeItem));
        if (IntPtr.Size != 8 || itemSize != 56 ||
            GetWindowThreadProcessId(tree, out owner) == 0 || owner != pid ||
            GetClassName(tree, klass, klass.Capacity) == 0 ||
            !string.Equals(klass.ToString(), "SysTreeView32", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("The NoteVive x64 native folder tree was not found.");
        var process = OpenProcess(0x1038, false, pid); // QUERY_LIMITED_INFORMATION, VM_OPERATION, VM_READ, VM_WRITE
        if (process == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
        IntPtr scratch = IntPtr.Zero, local = IntPtr.Zero;
        bool canFree = true;
        try {
            ushort emulated, native;
            if (!IsWow64Process2(process, out emulated, out native) || (emulated == 0 ? native : emulated) != 0x8664)
                throw new InvalidOperationException("The folder test requires a native or emulated x64 NoteVive process.");
            var encoded = new byte[itemSize];
            var buffer = new byte[512]; // 256 UTF-16 units; app names are limited to 120.
            scratch = VirtualAllocEx(process, IntPtr.Zero, (UIntPtr)(itemSize + buffer.Length), 0x3000, 0x04);
            if (scratch == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
            local = Marshal.AllocHGlobal(itemSize);
            IntPtr found = IntPtr.Zero;
            int remaining = 32; // The isolated smoke only creates two folders.
            foreach (string expected in path) {
                IntPtr item = TreeNext(tree, found == IntPtr.Zero ? 0 : 4, found); // TVGN_ROOT or TVGN_CHILD
                found = IntPtr.Zero;
                while (item != IntPtr.Zero) {
                    if (--remaining < 0) throw new InvalidOperationException("Too many native folder items in the test profile.");
                    var spec = new TreeItem { Mask = 1, Handle = item, Text = IntPtr.Add(scratch, itemSize), TextMax = buffer.Length / 2 };
                    Marshal.StructureToPtr(spec, local, false);
                    Marshal.Copy(local, encoded, 0, encoded.Length);
                    UIntPtr moved;
                    if (!WriteProcessMemory(process, scratch, encoded, (UIntPtr)encoded.Length, out moved) || moved.ToUInt64() != (ulong)encoded.Length)
                        throw new System.ComponentModel.Win32Exception();
                    // A timed-out OS call might still be using the scratch page;
                    // let that test process release it at exit in that case.
                    canFree = false;
                    int ok = Send(tree, 0x113e, IntPtr.Zero, scratch); // TVM_GETITEMW
                    canFree = true;
                    if (ok == 0) return false; // An in-progress refresh may have replaced the item.
                    if (!ReadProcessMemory(process, spec.Text, buffer, (UIntPtr)buffer.Length, out moved) || moved.ToUInt64() != (ulong)buffer.Length)
                        throw new System.ComponentModel.Win32Exception();
                    string text = Encoding.Unicode.GetString(buffer);
                    int end = text.IndexOf('\0');
                    if (end < 0) throw new InvalidOperationException("A folder label exceeded the test buffer.");
                    if (string.Equals(text.Substring(0, end), expected, StringComparison.Ordinal)) { found = item; break; }
                    item = TreeNext(tree, 1, item); // TVGN_NEXT sibling
                }
                if (found == IntPtr.Zero) return false;
                var expanded = new IntPtr(0x20);
                if (TreeNext(tree, 4, found) != IntPtr.Zero && (Send(tree, 0x1127, found, expanded) & 0x20) == 0) {
                    Send(tree, 0x1102, new IntPtr(2), found); // TVM_EXPAND / TVE_EXPAND
                    if ((Send(tree, 0x1127, found, expanded) & 0x20) == 0) return false;
                }
            }
            if (select) {
                Send(tree, 0x110b, new IntPtr(9), found); // TVM_SELECTITEM / TVGN_CARET
                return TreeNext(tree, 9, IntPtr.Zero) == found;
            }
            return found != IntPtr.Zero;
        } finally {
            if (local != IntPtr.Zero) Marshal.FreeHGlobal(local);
            if (canFree && scratch != IntPtr.Zero) VirtualFreeEx(process, scratch, UIntPtr.Zero, 0x8000);
            CloseHandle(process);
        }
    }
    public static IntPtr PopupMenu(uint processId) {
        IntPtr popup = IntPtr.Zero;
        do {
            popup = FindWindowEx(IntPtr.Zero, popup, "#32768", null);
            if (popup == IntPtr.Zero) return popup;
            uint owner;
            if (GetWindowThreadProcessId(popup, out owner) != 0 && owner == processId && IsWindowVisible(popup))
                return popup;
        } while (true);
    }
}
'@
$root = [System.Windows.Automation.AutomationElement]::RootElement
$enumScope = [System.Windows.Automation.TreeScope]::Descendants
$idProperty = [System.Windows.Automation.AutomationElement]::AutomationIdProperty
$nameProperty = [System.Windows.Automation.AutomationElement]::NameProperty
$classProperty = [System.Windows.Automation.AutomationElement]::ClassNameProperty
$processProperty = [System.Windows.Automation.AutomationElement]::ProcessIdProperty
$invoke = [System.Windows.Automation.InvokePattern]::Pattern
$prefix = "NVTEST-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$testProfile = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)) 'NoteVive-Pilote'
$records = Join-Path $testProfile 'notes'
$testNote = "$prefix B"
$testOlder = "$prefix A"
$testFolder = "$prefix parent"
$testChild = "$prefix enfant"
$testChildRenamed = "$prefix sous-dossier"
$testRenamed = "$prefix classe"
$marker = "$prefix marqueur éphémère."
$savedMarker = "$marker Texte relu."
$process = $null
$stage = 'initialisation'

if (Get-Process -Name NoteVive -ErrorAction SilentlyContinue) { throw 'Close all NoteVive instances first.' }
if (Test-Path -LiteralPath $testProfile) {
    throw "Use a fresh test user. Existing NoteVive storage was not modified: $testProfile"
}

function Step([string]$Label) {
    $script:stage = $Label
    Write-Host "Windows UI smoke: $Label"
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

function Wait-TreePath([string[]]$Path, [switch]$Select) {
    $tree = [NvWindow]::GetDlgItem((Window-Handle $app), 110)
    $labels = @('Toutes les transcriptions') + $Path
    # Acquire item handles afresh on every attempt; a save rebuilds the tree.
    $null = Wait-For { [NvWindow]::FindTreePath($tree, $process.Id, [string[]]$labels, $Select.IsPresent) } "find native branch '$($Path -join ' / ')'"
}

function Saved-Count([string]$Pattern) {
    if (-not (Test-Path -LiteralPath $records)) { return 0 }
    return @(Get-ChildItem -LiteralPath $records -Filter $Pattern -File).Count
}

function Wait-Folders([int]$Expected) {
    $null = Wait-For { (Saved-Count '*.nvf') -eq $Expected } "write $Expected encrypted folder record(s)"
    $tree = [NvWindow]::GetDlgItem((Window-Handle $app), 110)
    if ($tree -eq [IntPtr]::Zero) { throw 'The native folder tree is missing.' }
    $null = Wait-For { [NvWindow]::TreeCount($tree) -eq ($Expected + 2) } "display $Expected folder(s) in Win32 tree"
}

function Test-NoteVisible([string]$Name) {
    foreach ($label in @(Sorted-Names)) {
        if (Note-HasTitle $label $Name) { return $true }
    }
    return $false
}

function Note-HasTitle([string]$Label, [string]$Title) {
    return $Label.StartsWith("$Title · ", [StringComparison]::Ordinal)
}

function Select-Note([string]$Name) {
    $handle = Window-Handle $app
    $null = Wait-For { [NvWindow]::SelectListRow($handle, 106, $Name, $true) } "select the saved note '$Name'"
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
    $handle = Window-Handle $Element
    if ($handle -eq [IntPtr]::Zero) { throw 'The edit control has no native window.' }
    # Send edit messages to this HWND; another window can keep the desktop focus.
    [NvWindow]::ReplaceEditText($handle, $Text)
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
    $handle = Window-Handle $Dialog
    if ($handle -eq [IntPtr]::Zero -or [NvWindow]::GetDlgItem($handle, 1) -ne (Window-Handle $accept)) {
        throw 'Confirmation did not resolve to the native dialog button.'
    }
    # Send BN_CLICKED to the dialog: unlike BM_CLICK it works without foreground activation.
    if (-not [NvWindow]::Post($handle, 0x0111, [IntPtr]1, (Window-Handle $accept))) {
        throw 'Cannot confirm the action.'
    }
    $null = Wait-For { -not [NvWindow]::IsWindow($handle) -and [NvWindow]::IsWindowEnabled((Window-Handle $app)) } 'close the confirmed dialog'
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

function Rename-SelectedFolder([string]$Name) {
    Step 'open the folder actions menu'
    Click (ById 115)
    $item = Wait-For {
        # TrackPopupMenu creates a separate top-level HWND, outside the main UIA tree.
        $popup = [NvWindow]::PopupMenu($process.Id)
        if ($popup -ne [IntPtr]::Zero) {
            $menu = [System.Windows.Automation.AutomationElement]::FromHandle($popup)
            $menu.FindFirst($enumScope, (Condition $nameProperty 'Renommer le dossier'))
        }
    } 'find Renommer le dossier in the folder menu'
    Step 'invoke Rename from the folder actions menu'
    if (-not $item.Current.IsEnabled) { throw 'The visible Rename menu item is disabled.' }
    $item.GetCurrentPattern($invoke).Invoke()
    Step 'confirm the new folder name'
    Folder-Dialog 'Renommer le dossier' $Name
}

function Move-Note([string]$Destination) {
    Click (ById 116)
    $dialog = Find-Dialog 'Classer la transcription'
    $handle = Window-Handle $dialog
    $null = Wait-For { [NvWindow]::GetDlgItem($handle, 100) -ne [IntPtr]::Zero } 'find the native destination list'
    $null = Wait-For { [NvWindow]::SelectListRow($handle, 100, $Destination, $false) } "select the destination '$Destination'"
    Confirm-Dialog $dialog
    $null = Wait-For { (Editor-Folder) -ceq $Destination } "move note to '$Destination'"
}

function Sorted-Names {
    $labels = [NvWindow]::ListLabels((Window-Handle $app), 106)
    if ($null -ne $labels) { return @($labels) }
}

try {
    Step 'open the editor and find the notes sidebar'
    Begin-App
    $null = ById 110 # Dossiers tree sidebar.
    $null = ById 111 # Search.
    Step 'create the parent folder'
    Click (ById 114) # New top-level folder.
    Folder-Dialog 'Nouveau dossier' $testFolder
    Wait-Folders 1
    Wait-TreePath @($testFolder) -Select
    Step 'create the child folder'
    Click (ById 114) # Child of selected folder.
    Folder-Dialog 'Nouveau dossier' $testChild
    Wait-Folders 2
    Wait-TreePath @($testFolder, $testChild) -Select

    # Type a title first, allow autosave, then verify title and body survive.
    Step 'create the first note in the child folder and wait for autosave'
    Click (ById 101)
    $null = Wait-For {
        # The empty title alone is already true while the posted click is pending.
        $inChild = (Editor-Folder) -ceq "$testFolder / $testChild"
        $inChild -and ([NvWindow]::Text((Window-Handle (ById 107))) -ceq '')
    } 'new editor in the child folder'
    Input-Text (ById 107) $testOlder
    Input-Text (ById 108) $marker
    $null = Wait-For { Test-NoteVisible $testOlder } 'first note autosaved under child folder'
    Step 'create and save the second note'
    Click (ById 101)
    $null = Wait-For { [NvWindow]::Text((Window-Handle (ById 107))) -eq '' } 'second editor clear'
    Input-Text (ById 107) $testNote
    Input-Text (ById 108) 'Deuxième transcription fictive.'
    Click (ById 103)
    $null = Wait-For { Test-NoteVisible $testNote } 'second note saved'
    Step 'verify independent modification, creation and title ordering'
    # Give the first note a later revision, so modification and creation sort
    # in opposite directions. Wait for autosave before changing the sort.
    Select-Note $testOlder
    $null = Wait-For { [NvWindow]::Text((Window-Handle (ById 108))) -ceq $marker } 'open the older note before editing'
    Input-Text (ById 108) $savedMarker
    $null = Wait-For {
        $names = @(Sorted-Names)
        $names.Count -eq 2 -and (Note-HasTitle $names[0] $testOlder) -and (Note-HasTitle $names[1] $testNote)
    } 'newest modification first after editing the oldest note'
    $sort = Window-Handle (ById 113)
    if (-not [NvWindow]::ChooseSort((Window-Handle $app), $sort, 1)) { throw 'Cannot select creation date.' }
    $null = Wait-For {
        $names = @(Sorted-Names)
        $names.Count -eq 2 -and (Note-HasTitle $names[0] $testNote) -and (Note-HasTitle $names[1] $testOlder)
    } 'newest creation first'
    if (-not [NvWindow]::ChooseSort((Window-Handle $app), $sort, 2)) { throw 'Cannot select title order.' }
    $null = Wait-For {
        $names = @(Sorted-Names)
        $names.Count -eq 2 -and (Note-HasTitle $names[0] $testOlder) -and (Note-HasTitle $names[1] $testNote)
    } 'French title order'

    # Verify closing flushes edits, then reopen and find the saved note by body only.
    Step 'rename the note, close and reopen NoteVive'
    Select-Note $testNote
    $null = Wait-For {
        [NvWindow]::Text((Window-Handle (ById 108))) -ceq 'Deuxième transcription fictive.'
    } 'open the second note before renaming'
    Input-Text (ById 107) $testRenamed
    End-App
    Begin-App
    Wait-Folders 2
    Wait-TreePath @($testFolder, $testChild)
    Step 'search and open the saved note by its body'
    Input-Text (ById 111) 'marqueur ephemere'
    $null = Wait-For {
        $names = @(Sorted-Names)
        $names.Count -eq 1 -and (Note-HasTitle $names[0] $testOlder)
    } 'accent-insensitive query of saved body'
    Select-Note $testOlder
    $null = Wait-For { [NvWindow]::Text((Window-Handle (ById 108))) -ceq $savedMarker } 'open saved body'
    Step 'select the renamed note and its child folder'
    Input-Text (ById 111) ''
    Select-Note $testRenamed
    $null = Wait-For {
        $where = [NvWindow]::GetDlgItem((Window-Handle $app), 120)
        [NvWindow]::Text($where).Contains("$testFolder / $testChild")
    } 'persisted note links to the nested folder'
    Wait-TreePath @($testFolder, $testChild) -Select
    Rename-SelectedFolder $testChildRenamed
    Wait-TreePath @($testFolder, $testChildRenamed)
    $null = Wait-For { (Editor-Folder) -ceq "$testFolder / $testChildRenamed" } 'note remains in the renamed folder'
    Step 'move the note out of its folder'
    Move-Note 'Sans dossier'
    Step 'move the note to the parent folder'
    Move-Note $testFolder
    Step 'reopen NoteVive and verify the renamed folder and moved note'
    End-App
    Begin-App
    Wait-Folders 2
    Wait-TreePath @($testFolder, $testChildRenamed)
    Select-Note $testRenamed
    $null = Wait-For {
        (Editor-Folder) -ceq $testFolder -and [NvWindow]::Text((Window-Handle (ById 108))) -ceq 'Deuxième transcription fictive.'
    } 'new folder and note body persisted after moving'
    End-App
    Step 'count the saved notes and folders'
    $savedCount = @(Get-ChildItem -LiteralPath $records -Filter '*.nvn' -File).Count
    $folderCount = @(Get-ChildItem -LiteralPath $records -Filter '*.nvf' -File).Count
    if ($savedCount -ne 2 -or $folderCount -ne 2) { throw "Expected exactly two notes and folders, found $savedCount / $folderCount." }
    Write-Output 'Windows UI, nested folders, renaming, moving notes, sort, body search, autosave and close/reopen verified with fictitious text.'
} catch {
    $failure = $_
    [Console]::Error.WriteLine("Windows UI smoke failed at '$stage': $($_.Exception.GetType().FullName): $($_.Exception.Message)")
    [Console]::Error.WriteLine($_.InvocationInfo.PositionMessage)
    [Console]::Error.WriteLine($_.ScriptStackTrace)
    try {
        $details = "folder_files=$(Saved-Count '*.nvf'), note_files=$(Saved-Count '*.nvn')"
        if ($app -and $process -and -not $process.HasExited) {
            $handle = Window-Handle $app
            $tree = [NvWindow]::GetDlgItem($handle, 110)
            $details += ", native_tree_items=$([NvWindow]::TreeCount($tree)), main_enabled=$([NvWindow]::IsWindowEnabled($handle))"
            [Console]::Error.WriteLine($details)
            [Console]::Error.WriteLine("Native note list rows: $(@(Sorted-Names).Count)")
            [Console]::Error.WriteLine("Native folder popup visible: $([NvWindow]::PopupMenu($process.Id) -ne [IntPtr]::Zero)")
        } else { [Console]::Error.WriteLine($details) }
    } catch {
        [Console]::Error.WriteLine("Additional UI diagnostics unavailable: $($_.Exception.GetType().FullName)")
    }
    throw $failure
} finally {
    if ($process -and -not $process.HasExited) {
        $process.CloseMainWindow() | Out-Null
        if (-not $process.WaitForExit(4000)) { $process.Kill(); $process.WaitForExit() }
    }
    # This profile did not exist before the smoke. Keep records on failure for inspection.
}
