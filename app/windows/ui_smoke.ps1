# Requires an interactive Windows desktop and a dedicated, disposable user.
# The smoke does not open the microphone, replay audio, or modify real notes.
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Executable, [string]$PreviewPath)
$ErrorActionPreference = 'Stop'
if (-not [Environment]::UserInteractive) { throw 'An interactive Windows desktop is required.' }
$Executable = (Resolve-Path -LiteralPath $Executable).Path
# Check before launching; a mismatched binary must not open the other library.
# The dedicated binary alone contains this UTF-16 window property name. The
# running process must also expose the property before the script edits data.
$markerBytes = [Text.Encoding]::Unicode.GetBytes("NoteVive.VisualSmoke.FictionalOnly" + [char]0)
$binaryText = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($Executable))
$markerFound = $binaryText.Contains([Text.Encoding]::ASCII.GetString($markerBytes))
if ($markerFound -ne [bool]$PreviewPath) { throw 'PreviewPath and the selected NoteVive executable do not match.' }
Remove-Variable binaryText
if ($PreviewPath) {
    $PreviewPath = [IO.Path]::GetFullPath($PreviewPath)
    if ([IO.Path]::GetExtension($PreviewPath) -ine '.png') { throw 'PreviewPath must end in .png.' }
    if (Test-Path -LiteralPath $PreviewPath) { throw 'PreviewPath already exists; choose a fresh output file.' }
    Add-Type -AssemblyName System.Drawing
}
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class NvWindow {
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] struct Point { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] struct GuiThreadInfo {
        public int Size, Flags;
        public IntPtr Active, Focus, Capture, MenuOwner, MoveSize, Caret;
        public Rect CaretBounds;
    }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out Rect rect);
    [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr hwnd, out Rect rect);
    [DllImport("user32.dll")] static extern bool ClientToScreen(IntPtr hwnd, ref Point point);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int w, int h, uint flags);
    [DllImport("user32.dll")] static extern IntPtr GetNextDlgTabItem(IntPtr app, IntPtr start, bool previous);
    [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr GetProp(IntPtr hwnd, string name);
    [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr hwnd, IntPtr dc, uint flags);
    [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr hwnd, int id);
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr hwnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string className, string title);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
    [DllImport("user32.dll")] static extern bool GetGUIThreadInfo(uint thread, ref GuiThreadInfo info);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr hwnd, StringBuilder name, int max);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool OpenClipboard(IntPtr owner);
    [DllImport("user32.dll")] static extern bool CloseClipboard();
    [DllImport("user32.dll")] public static extern uint GetClipboardSequenceNumber();
    [DllImport("user32.dll")] static extern IntPtr GetClipboardOwner();
    [DllImport("user32.dll")] static extern bool IsClipboardFormatAvailable(uint format);
    [DllImport("user32.dll")] static extern IntPtr GetClipboardData(uint format);
    [DllImport("user32.dll")] static extern bool EmptyClipboard();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern uint RegisterClipboardFormat(string name);
    [DllImport("kernel32.dll")] static extern UIntPtr GlobalSize(IntPtr memory);
    [DllImport("kernel32.dll")] static extern IntPtr GlobalLock(IntPtr memory);
    [DllImport("kernel32.dll")] static extern bool GlobalUnlock(IntPtr memory);
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
    public static bool SelectFilter(IntPtr parent, int id, string expected) {
        IntPtr combo = GetDlgItem(parent, id);
        if (combo == IntPtr.Zero || !IsWindowEnabled(combo)) return false;
        UIntPtr result;
        // CB_FINDSTRINGEXACT reads a normally marshalled Unicode string.
        if (WriteBounded(combo, 0x0158, new IntPtr(-1), expected, 0x0002, 2000, out result) == IntPtr.Zero) return false;
        int index = unchecked((int)result.ToUInt64());
        if (index < 1 || Send(combo, 0x014e, new IntPtr(index), IntPtr.Zero) != index) return false; // CB_SETCURSEL
        return Post(parent, 0x0111, new IntPtr((1 << 16) | id), combo); // WM_COMMAND / CBN_SELCHANGE
    }
    public static bool CheckClipboard(IntPtr app, uint previous, string expected) {
        if (GetClipboardSequenceNumber() == previous || !OpenClipboard(IntPtr.Zero)) return false;
        try {
            if (GetClipboardOwner() != app) return false;
            const uint unicodeText = 13; // CF_UNICODETEXT
            uint exclusion = RegisterClipboardFormat("ExcludeClipboardContentFromMonitorProcessing");
            if (!IsClipboardFormatAvailable(unicodeText) || exclusion == 0 || !IsClipboardFormatAvailable(exclusion))
                return false;
            IntPtr data = GetClipboardData(unicodeText);
            if (data == IntPtr.Zero) return false;
            ulong bytes = GlobalSize(data).ToUInt64();
            if (bytes < (ulong)((expected.Length + 1) * 2)) return false;
            IntPtr text = GlobalLock(data);
            if (text == IntPtr.Zero) return false;
            bool matched = false;
            try {
                matched = Marshal.ReadInt16(text, expected.Length * 2) == 0 &&
                    string.Equals(Marshal.PtrToStringUni(text, expected.Length), expected, StringComparison.Ordinal);
            } finally { GlobalUnlock(data); }
            if (!matched) return false;
            // Only remove the just-verified fictitious payload and only while
            // we hold the clipboard, so no later owner can be overwritten.
            if (!EmptyClipboard()) throw new InvalidOperationException("Could not clear the fictitious clipboard payload.");
            return true;
        } finally { CloseClipboard(); }
    }
    public static Rect PreviewSize(IntPtr app, uint pid) {
        uint owner;
        Rect bounds;
        var klass = new StringBuilder(64);
        if (GetWindowThreadProcessId(app, out owner) == 0 || owner != pid || !IsWindowVisible(app) ||
            GetClassName(app, klass, klass.Capacity) == 0 || klass.ToString() != "NoteVivePrototypeWindow")
            throw new InvalidOperationException("Preview must target the launched NoteVive test window.");
        if (!IsVisualTestBuild(app))
            throw new InvalidOperationException("Use the dedicated NoteVive visual test build for PreviewPath.");
        if (!GetWindowRect(app, out bounds) || bounds.Right <= bounds.Left || bounds.Bottom <= bounds.Top)
            throw new InvalidOperationException("Cannot measure the NoteVive test window.");
        return bounds;
    }
    public static bool IsVisualTestBuild(IntPtr app) {
        return GetProp(app, "NoteVive.VisualSmoke.FictionalOnly") == new IntPtr(1);
    }
    public static bool CaptureWindow(IntPtr app, IntPtr dc, uint pid) {
        PreviewSize(app, pid);
        // The standard whole-window request asks NoteVive and its controls to paint.
        Send(app, 0, IntPtr.Zero, IntPtr.Zero); // WM_NULL responsiveness check.
        return PrintWindow(app, dc, 0);
    }
    public static bool VisibleClientControl(IntPtr app, int id, int min_width, int min_height) {
        IntPtr previous = SetThreadDpiAwarenessContext(new IntPtr(-4)); // PerMonitorV2.
        if (previous == IntPtr.Zero) return false;
        try {
            IntPtr child = GetDlgItem(app, id);
            Rect control, client;
            Point origin = new Point();
            if (child == IntPtr.Zero || !IsWindowVisible(child) ||
                !GetWindowRect(child, out control) || !GetClientRect(app, out client) ||
                !ClientToScreen(app, ref origin)) return false;
            uint dpi = GetDpiForWindow(app);
            return dpi != 0 && (control.Right - control.Left) * 96 >= min_width * dpi &&
                (control.Bottom - control.Top) * 96 >= min_height * dpi &&
                control.Left >= origin.X && control.Top >= origin.Y &&
                control.Right <= origin.X + client.Right && control.Bottom <= origin.Y + client.Bottom;
        } finally { SetThreadDpiAwarenessContext(previous); }
    }
    public static bool TabFollows(IntPtr app, int from, int to) {
        IntPtr start = GetDlgItem(app, from), next = GetDlgItem(app, to);
        return start != IntPtr.Zero && next != IntPtr.Zero && GetNextDlgTabItem(app, start, false) == next
            && GetNextDlgTabItem(app, next, true) == start;
    }
    public static IntPtr UiFocus(IntPtr app, uint pid) {
        uint owner;
        uint thread = GetWindowThreadProcessId(app, out owner);
        var info = new GuiThreadInfo { Size = Marshal.SizeOf(typeof(GuiThreadInfo)) };
        return thread != 0 && owner == pid && GetGUIThreadInfo(thread, ref info) ? info.Focus : IntPtr.Zero;
    }
    public static bool TabFrom(IntPtr app, uint pid, int id) {
        IntPtr from = GetDlgItem(app, id);
        return from != IntPtr.Zero && UiFocus(app, pid) == from && Post(from, 0x0100, new IntPtr(9), new IntPtr(0x000f0001));
    }
    public static bool CompactLayout(IntPtr app, uint pid) {
        uint owner;
        if (GetWindowThreadProcessId(app, out owner) == 0 || owner != pid) return false;
        IntPtr previous = SetThreadDpiAwarenessContext(new IntPtr(-4));
        if (previous == IntPtr.Zero) return false;
        try {
            Rect outer, client;
            uint dpi = GetDpiForWindow(app);
            if (dpi == 0 || !GetWindowRect(app, out outer) || !GetClientRect(app, out client)) return false;
            int w = outer.Right - outer.Left, h = outer.Bottom - outer.Top;
            const uint noMoveOrActivation = 0x0016; // NOMOVE|NOZORDER|NOACTIVATE
            int compactW = w - client.Right + (int)((650 * dpi + 48) / 96);
            int compactH = h - client.Bottom + (int)((490 * dpi + 48) / 96);
            try {
                if (!SetWindowPos(app, IntPtr.Zero, 0, 0, compactW, compactH, noMoveOrActivation)) return false;
                Send(app, 0, IntPtr.Zero, IntPtr.Zero);
                return VisibleClientControl(app, 106, 120, 65) && VisibleClientControl(app, 108, 200, 81)
                    && VisibleClientControl(app, 102, 120, 32) && VisibleClientControl(app, 123, 85, 32);
            } finally {
                if (!SetWindowPos(app, IntPtr.Zero, 0, 0, w, h, noMoveOrActivation))
                    throw new InvalidOperationException("Could not restore the preview window size.");
            }
        } finally { SetThreadDpiAwarenessContext(previous); }
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
    public static IntPtr PopupMenu(uint processId) { return NextPopup(processId, IntPtr.Zero); }
    static IntPtr NextPopup(uint processId, IntPtr popup) {
        do {
            popup = FindWindowEx(IntPtr.Zero, popup, "#32768", null);
            if (popup == IntPtr.Zero) return popup;
            uint owner;
            if (GetWindowThreadProcessId(popup, out owner) != 0 && owner == processId && IsWindowVisible(popup))
                return popup;
        } while (true);
    }
    [DllImport("user32.dll")] static extern int GetMenuItemCount(IntPtr menu);
    [DllImport("user32.dll", EntryPoint = "GetMenuStringW", ExactSpelling = true, CharSet = CharSet.Unicode)]
    static extern int GetMenuString(IntPtr menu, uint index, StringBuilder text, int max, uint flags);
    [DllImport("user32.dll")] static extern uint GetMenuState(IntPtr menu, uint index, uint flags);

    static char MenuMnemonic(string caption) {
        for (int i = 0; i + 1 < caption.Length; ++i) {
            if (caption[i] != '&') continue;
            if (caption[i + 1] != '&') return char.ToLowerInvariant(caption[i + 1]);
            ++i; // A doubled ampersand is literal text.
        }
        return '\0';
    }
    public static bool ChoosePopupItem(IntPtr ownerWindow, uint processId, string wantedCaption) {
        IntPtr popup = IntPtr.Zero;
        for (int i = 0; i < 3; ++i) {
            popup = NextPopup(processId, popup);
            if (popup == IntPtr.Zero) return false;
            if (ChoosePopupItemFrom(ownerWindow, popup, processId, wantedCaption)) return true;
        }
        return false;
    }
    static bool ChoosePopupItemFrom(IntPtr ownerWindow, IntPtr popup, uint processId, string wantedCaption) {
        // Read the native popup independently of the accessibility provider.
        // https://learn.microsoft.com/windows/win32/winmsg/mn-gethmenu
        uint ownerPid, popupPid;
        uint ownerThread = GetWindowThreadProcessId(ownerWindow, out ownerPid);
        uint popupThread = GetWindowThreadProcessId(popup, out popupPid);
        if (ownerThread == 0 || popupThread != ownerThread || ownerPid != processId || popupPid != processId) return false;
        var menu = new IntPtr(unchecked((long)SendRaw(popup, 0x01e1, IntPtr.Zero, IntPtr.Zero).ToUInt64())); // MN_GETHMENU
        if (menu == IntPtr.Zero) return false;
        int count = GetMenuItemCount(menu);
        if (count == -1) return false;
        if (count < 1 || count > 20) throw new InvalidOperationException("Unexpected size of the actions menu.");
        const uint byPosition = 0x0400; // MF_BYPOSITION
        char key = MenuMnemonic(wantedCaption);
        if (key == '\0') throw new ArgumentException("The requested folder action needs a keyboard mnemonic.");
        int selected = -1, sameMnemonic = 0;
        var caption = new StringBuilder(256);
        for (uint i = 0; i < (uint)count; ++i) {
            uint flags = GetMenuState(menu, i, byPosition);
            if (flags == uint.MaxValue) return false;
            if ((flags & 0x0800) != 0) continue; // MF_SEPARATOR
            caption.Clear();
            int length = GetMenuString(menu, i, caption, caption.Capacity, byPosition);
            if (length == 0) return false;
            if (length >= caption.Capacity - 1 || caption.Length != length)
                throw new InvalidOperationException("A native menu label exceeded the test buffer.");
            string label = caption.ToString().Split('\t')[0];
            if (MenuMnemonic(label) == key) ++sameMnemonic;
            if (string.Equals(label, wantedCaption, StringComparison.Ordinal)) selected = (int)i;
        }
        if (selected < 0) return false;
        uint state = GetMenuState(menu, (uint)selected, byPosition);
        if (sameMnemonic != 1 || state == uint.MaxValue || (state & 0x0003) != 0) // MF_GRAYED | MF_DISABLED
            throw new InvalidOperationException("The action is ambiguous or disabled.");
        if (!IsWindowVisible(popup)) return false;
        // Queue the mnemonic to the popup's own thread. TrackPopupMenu handles
        // WM_CHAR and returns the selected item, as during keyboard navigation.
        // https://learn.microsoft.com/windows/win32/inputdev/wm-char
        if (!Post(popup, 0x0102, new IntPtr(key), new IntPtr(0x10000001))) // WM_CHAR, active menu, repeat count 1
            throw new InvalidOperationException("Cannot send the mnemonic to the visible actions menu.");
        return true;
    }
}
'@
$root = [System.Windows.Automation.AutomationElement]::RootElement
$enumScope = [System.Windows.Automation.TreeScope]::Descendants
$idProperty = [System.Windows.Automation.AutomationElement]::AutomationIdProperty
$nameProperty = [System.Windows.Automation.AutomationElement]::NameProperty
$classProperty = [System.Windows.Automation.AutomationElement]::ClassNameProperty
$processProperty = [System.Windows.Automation.AutomationElement]::ProcessIdProperty
$prefix = "NVTEST-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$profileName = if ($PreviewPath) { 'NoteVive-VisualSmoke' } else { 'NoteVive-Pilote' }
$testProfile = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)) $profileName
$records = Join-Path $testProfile 'notes'
$testNote = "$prefix B"
$testOlder = "$prefix A"
$testFolder = "$prefix parent"
$testChild = "$prefix enfant"
$testChildRenamed = "$prefix sous-dossier"
$testRenamed = "$prefix classe"
$marker = "$prefix marqueur éphémère."
$savedMarker = "$marker Texte relu."
$captureNote = "Deuxième transcription fictive.`r`nEssai de dictée hors ligne : œdème à gauche, aucune douleur à droite."
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
    $labels = @('Toutes les notes') + $Path
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
    if ([NvWindow]::IsVisualTestBuild((Window-Handle $app)) -ne [bool]$PreviewPath) {
        throw 'PreviewPath and the selected NoteVive build do not match.'
    }
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

function Invoke-NoteAction([string]$Caption, [string]$Group) {
    Click (ById 123)
    if ($Group) {
        $null = Wait-For { [NvWindow]::ChoosePopupItem((Window-Handle $app), $process.Id, $Group) } "open the native '$Group' submenu"
    }
    $null = Wait-For { [NvWindow]::ChoosePopupItem((Window-Handle $app), $process.Id, $Caption) } "invoke '$Caption' through the native Actions menu"
    $null = Wait-For { [NvWindow]::PopupMenu($process.Id) -eq [IntPtr]::Zero } 'close the native Actions menu'
}

function Rename-SelectedFolder([string]$Name) {
    Step 'open the folder actions menu'
    Invoke-NoteAction '&Renommer le dossier…' '&Dossiers'
    Step 'confirm the new folder name'
    Folder-Dialog 'Renommer le dossier' $Name
}

function Move-Note([string]$Destination) {
    Invoke-NoteAction '&Classer la note…'
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

function Probe-Catalogue {
    $handle = Window-Handle $app
    $previous = [NvWindow]::UiFocus($handle, $process.Id)
    if ($previous -eq [IntPtr]::Zero) { throw 'The main window has no focused control before vocabulary.' }
    Invoke-NoteAction '&Vocabulaire médical…'
    $popup = Find-Dialog 'Vocabulaire médical · NoteVive'
    $popupHandle = Window-Handle $popup
    $query = Wait-For { $popup.FindFirst($enumScope, (Condition $idProperty '4101')) } 'find the glossary search input'
    if ([NvWindow]::UiFocus($handle, $process.Id) -ne (Window-Handle $query) -or
            [NvWindow]::GetDlgItem($popupHandle, 4105) -eq [IntPtr]::Zero -or
            [NvWindow]::GetDlgItem($popupHandle, 4106) -eq [IntPtr]::Zero) {
        throw 'Glossary filters or initial search focus are missing.'
    }
    Input-Text $query 'hémoglobine'
    Click ($popup.FindFirst($enumScope, (Condition $idProperty '4102')))
    $null = Wait-For {
        $result = [NvWindow]::Text([NvWindow]::GetDlgItem($popupHandle, 4103))
        $result -match '(?im)^.*hémoglobine.*\r?\n[^\r\n]+ · [^\r\n]+ · [^\r\n]+\r?$'
    } 'return a matching haemoglobin term with its source, edition and code'
    if (-not [NvWindow]::SelectFilter($popupHandle, 4106, 'Dispositifs')) { throw 'The device vocabulary filter is missing.' }
    $null = Wait-For {
        $result = [NvWindow]::Text([NvWindow]::GetDlgItem($popupHandle, 4103))
        $result -match '(?im)^HÉMOGLOBINE \(HB\)\r?\nEuropean Medical Device Nomenclature[^\r\n]+ · [^\r\n]+ · W0103010601\r?$' -and
        $result -notmatch '(?i)Orphanet'
    } 'filter devices and display the exact EMDN record, excluding Orphanet disorders'
    if (-not [NvWindow]::SelectFilter($popupHandle, 4106, 'Maladies')) { throw 'The disorder vocabulary filter is missing.' }
    $null = Wait-For {
        $result = [NvWindow]::Text([NvWindow]::GetDlgItem($popupHandle, 4103))
        $result -match '(?im)^Drépanocytose-hémoglobine C\r?\nOrphanet[^\r\n]+ · [^\r\n]+ · 251365\r?$' -and
        $result -notmatch '(?i)European Medical Device Nomenclature'
    } 'filter disorders and display the exact Orphanet record, excluding EMDN devices'
    Click ($popup.FindFirst($enumScope, (Condition $idProperty '4104')))
    $null = Wait-For { -not [NvWindow]::IsWindow($popupHandle) -and [NvWindow]::UiFocus($handle, $process.Id) -eq $previous } 'close vocabulary and return to the previous control'
}

function Save-Preview([string]$Path) {
    $handle = Window-Handle $app
    # Match PerMonitorV2 without changing system settings or display scaling.
    $previousDpi = [NvWindow]::SetThreadDpiAwarenessContext([IntPtr](-4))
    if ($previousDpi -eq [IntPtr]::Zero) { throw 'Cannot request physical window coordinates for preview.' }
    try {
        $bounds = [NvWindow]::PreviewSize($handle, $process.Id)
        $width = $bounds.Right - $bounds.Left
        $height = $bounds.Bottom - $bounds.Top
        if ($width -lt 450 -or $height -lt 380 -or $width -gt 4800 -or $height -gt 2800) {
            throw "Unexpected preview dimensions: ${width}x${height}."
        }
        $bitmap = [Drawing.Bitmap]::new($width, $height, [Drawing.Imaging.PixelFormat]::Format24bppRgb)
        try {
            $graphics = [Drawing.Graphics]::FromImage($bitmap)
            try {
                $dc = $graphics.GetHdc()
                try {
                    if (-not [NvWindow]::CaptureWindow($handle, $dc, $process.Id)) { throw 'PrintWindow did not render NoteVive.' }
                } finally { $graphics.ReleaseHdc($dc) }
            } finally { $graphics.Dispose() }
            $colors = New-Object 'System.Collections.Generic.HashSet[int]'
            $canvas = 0
            $paper = 0
            for ($y = 32; $y -lt $height - 16; $y += 5) {
                for ($x = 16; $x -lt $width - 16; $x += 5) {
                    $rgb = $bitmap.GetPixel($x, $y)
                    $null = $colors.Add($rgb.ToArgb())
                    if ($rgb.R -eq 242 -and $rgb.G -eq 247 -and $rgb.B -eq 246) { $canvas += 1 }
                    if ($rgb.R -eq 255 -and $rgb.G -eq 255 -and $rgb.B -eq 255) { $paper += 1 }
                }
            }
            if ($colors.Count -lt 12 -or $canvas -lt 30 -or $paper -lt 50) {
                throw 'The window preview is empty or missing the expected light theme surfaces (use standard contrast).'
            }
            $null = [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path))
            $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try { $bitmap.Save($stream, [Drawing.Imaging.ImageFormat]::Png) } finally { $stream.Dispose() }
        } finally { $bitmap.Dispose() }
        Write-Output "NoteVive window preview: ${width}x${height}, $([NvWindow]::GetDpiForWindow($handle)) DPI, $Path"
    } finally { $null = [NvWindow]::SetThreadDpiAwarenessContext($previousDpi) }
}

try {
    Step 'open the editor and find the notes sidebar'
    Begin-App
    $null = ById 110 # Dossiers tree sidebar.
    $null = ById 111 # Search.
    $handle = Window-Handle $app
    Step 'verify initial control bounds'
    $null = Wait-For {
        [NvWindow]::VisibleClientControl($handle, 101, 120, 32) -and
        [NvWindow]::VisibleClientControl($handle, 102, 120, 32) -and
        [NvWindow]::VisibleClientControl($handle, 106, 120, 65) -and
        [NvWindow]::VisibleClientControl($handle, 108, 200, 60) -and
        [NvWindow]::VisibleClientControl($handle, 121, 75, 24) -and
        [NvWindow]::VisibleClientControl($handle, 123, 85, 32)
    } 'show the library, note editor, dictation controls and menu at the current DPI'
    if ([NvWindow]::IsWindowVisible([NvWindow]::GetDlgItem($handle, 109))) { throw 'The empty provisional pane should be hidden.' }
    foreach ($removed in @(103, 104, 105, 112, 113, 114, 115, 116, 122)) {
        if ([NvWindow]::GetDlgItem($handle, $removed) -ne [IntPtr]::Zero) { throw "Action $removed occupies a persistent control." }
    }
    Step 'verify compact layout and native tab ordering'
    if (-not [NvWindow]::CompactLayout($handle, $process.Id)) { throw 'The compact editor or navigation is clipped.' }
    $tabChain = @(101, 111, 110, 106, 107, 108)
    for ($i = 1; $i -lt $tabChain.Count; ++$i) {
        if (-not [NvWindow]::TabFollows($handle, $tabChain[$i - 1], $tabChain[$i])) { throw 'Unexpected bidirectional keyboard navigation order.' }
    }
    $nextTab = if ([NvWindow]::IsWindowEnabled([NvWindow]::GetDlgItem($handle, 102))) { 102 } else { 123 }
    if (-not [NvWindow]::TabFollows($handle, 108, $nextTab)) { throw 'The editor tab order does not skip unavailable actions.' }
    Step 'establish keyboard focus in the editor'
    $editor = ById 108
    $editorHandle = Window-Handle $editor
    if ([NvWindow]::UiFocus($handle, $process.Id) -ne $editorHandle) { $editor.SetFocus() }
    $null = Wait-For { [NvWindow]::UiFocus($handle, $process.Id) -eq $editorHandle } 'start with focus in the editor'
    $editorText = [NvWindow]::Text($editorHandle)
    Step 'verify actual Tab routing from the editor'
    if (-not [NvWindow]::TabFrom($handle, $process.Id, 108)) { throw 'Could not queue Tab in the focused editor.' }
    $null = Wait-For { [NvWindow]::UiFocus($handle, $process.Id) -eq [NvWindow]::GetDlgItem($handle, $nextTab) } 'move focus to the next visible action with Tab'
    if ([NvWindow]::Text($editorHandle) -cne $editorText) { throw 'Tab altered the text of the note.' }
    $copyHandle = [NvWindow]::GetDlgItem($handle, 121)
    if ($copyHandle -eq [IntPtr]::Zero -or [NvWindow]::IsWindowEnabled($copyHandle)) {
        throw 'Copy must be disabled in the initial empty editor.'
    }
    Step 'create the parent folder'
    Invoke-NoteAction '&Nouveau dossier…' '&Dossiers'
    Folder-Dialog 'Nouveau dossier' $testFolder
    Wait-Folders 1
    Wait-TreePath @($testFolder) -Select
    Step 'create the child folder'
    Invoke-NoteAction '&Nouveau dossier…' '&Dossiers'
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
    $null = Wait-For {
        [NvWindow]::Text((Window-Handle (ById 107))) -ceq '' -and
        [NvWindow]::Text((Window-Handle (ById 108))) -ceq '' -and
        -not [NvWindow]::IsWindowEnabled($copyHandle)
    } 'second editor clear and Copy disabled'
    Input-Text (ById 107) $testNote
    Input-Text (ById 108) $captureNote
    Invoke-NoteAction '&Enregistrer maintenant'
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
    Invoke-NoteAction 'Date de cré&ation' '&Trier les notes'
    $null = Wait-For {
        $names = @(Sorted-Names)
        $names.Count -eq 2 -and (Note-HasTitle $names[0] $testNote) -and (Note-HasTitle $names[1] $testOlder)
    } 'newest creation first'
    Invoke-NoteAction 'Titre (A à &Z)' '&Trier les notes'
    $null = Wait-For {
        $names = @(Sorted-Names)
        $names.Count -eq 2 -and (Note-HasTitle $names[0] $testOlder) -and (Note-HasTitle $names[1] $testNote)
    } 'French title order'

    # Verify closing flushes edits, then reopen and find the saved note by body only.
    Step 'rename the note, close and reopen NoteVive'
    Select-Note $testNote
    $null = Wait-For {
        [NvWindow]::Text((Window-Handle (ById 108))) -ceq $captureNote
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
    Step 'verify folder scope and opt-in cross-folder search'
    $null = Wait-For { Test-NoteVisible $testOlder } 'display the note that remains in the selected child folder'
    Input-Text (ById 111) $testRenamed
    $null = Wait-For { @(Sorted-Names).Count -eq 0 } 'exclude the sibling result outside the selected search folder'
    Invoke-NoteAction 'Chercher dan&s tous les dossiers'
    $null = Wait-For { Test-NoteVisible $testRenamed } 'find the moved note when cross-folder search is enabled'
    Step 'reopen NoteVive and verify the renamed folder and moved note'
    End-App
    Begin-App
    Wait-Folders 2
    Wait-TreePath @($testFolder, $testChildRenamed)
    Select-Note $testRenamed
    $null = Wait-For {
        (Editor-Folder) -ceq $testFolder -and [NvWindow]::Text((Window-Handle (ById 108))) -ceq $captureNote
    } 'new folder and note body persisted after moving'
    Step 'mask and restore through the Actions menu without changing the saved note'
    $handle = Window-Handle $app
    Invoke-NoteAction 'Mas&quer la note'
    $null = Wait-For {
        -not [NvWindow]::IsWindowVisible([NvWindow]::GetDlgItem($handle, 108)) -and
        -not [NvWindow]::IsWindowVisible([NvWindow]::GetDlgItem($handle, 106)) -and
        -not [NvWindow]::IsWindowVisible([NvWindow]::GetDlgItem($handle, 121))
    } 'hide the editor, note list and copy button'
    Invoke-NoteAction '&Réafficher la note'
    $null = Wait-For {
        [NvWindow]::IsWindowVisible([NvWindow]::GetDlgItem($handle, 108)) -and
        [NvWindow]::Text((Window-Handle (ById 108))) -ceq $captureNote
    } 'restore the same saved note'
    if (-not $PreviewPath) {
        Step 'open the packaged vocabulary, find a sourced term, and restore keyboard focus'
        Probe-Catalogue
    }
    Step 'copy the whole fictitious note as exact Unicode text'
    $copy = ById 121
    $copyHandle = Window-Handle $copy
    if ([NvWindow]::Text($copyHandle).Replace('&', '') -cne 'Copier') { throw 'Unexpected copy button caption.' }
    $null = Wait-For { [NvWindow]::IsWindowEnabled($copyHandle) } 'enable Copy when the saved note reopens'
    $beforeClipboard = [NvWindow]::GetClipboardSequenceNumber()
    Click $copy
    $handle = Window-Handle $app
    $null = Wait-For { [NvWindow]::CheckClipboard($handle, $beforeClipboard, $captureNote) } 'copy the note to CF_UNICODETEXT without its title and with the Windows clipboard exclusion'
    if ($PreviewPath) {
        Step 'capture only the populated NoteVive visual test window'
        Save-Preview $PreviewPath
    }
    End-App
    Step 'count the saved notes and folders'
    $savedCount = @(Get-ChildItem -LiteralPath $records -Filter '*.nvn' -File).Count
    $folderCount = @(Get-ChildItem -LiteralPath $records -Filter '*.nvf' -File).Count
    if ($savedCount -ne 2 -or $folderCount -ne 2) { throw "Expected exactly two notes and folders, found $savedCount / $folderCount." }
    Write-Output 'Windows UI, keyboard navigation, compact layout, mask, nested folders, rename, move, sort, scoped search, autosave, reopen and Unicode copy verified with fictitious text.'
} catch {
    $failure = $_
    $annotation = ("$stage : $($_.Exception.Message)").Replace('%', '%25').Replace([string][char]13, '%0D').Replace([string][char]10, '%0A')
    Write-Output "::error title=NoteVive UI recipe::$annotation"
    [Console]::Error.WriteLine("Windows UI smoke failed at '$stage': $($_.Exception.GetType().FullName): $($_.Exception.Message)")
    [Console]::Error.WriteLine($_.InvocationInfo.PositionMessage)
    [Console]::Error.WriteLine($_.ScriptStackTrace)
    try {
        $details = "folder_files=$(Saved-Count '*.nvf'), note_files=$(Saved-Count '*.nvn')"
        if ($app -and $process -and -not $process.HasExited) {
            $handle = Window-Handle $app
            $tree = [NvWindow]::GetDlgItem($handle, 110)
            $details += ", focus=$([NvWindow]::UiFocus($handle, $process.Id)), editor=$([NvWindow]::GetDlgItem($handle, 108)), native_tree_items=$([NvWindow]::TreeCount($tree)), main_enabled=$([NvWindow]::IsWindowEnabled($handle))"
            [Console]::Error.WriteLine($details)
            Write-Output ("::notice title=NoteVive isolated UI state::" + $details.Replace('%', '%25').Replace([string][char]13, '%0D').Replace([string][char]10, '%0A'))
            [Console]::Error.WriteLine("Native note list rows: $(@(Sorted-Names).Count)")
            [Console]::Error.WriteLine("Native Actions popup visible: $([NvWindow]::PopupMenu($process.Id) -ne [IntPtr]::Zero)")
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
