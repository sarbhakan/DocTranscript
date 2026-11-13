# Read-only P0 inventory. Output does not contain host names, usernames or serials.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows only.' }

if (-not ('NoteVive.P0.ProcessorFeatures' -as [type])) {
    Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
namespace NoteVive.P0 {
    public static class ProcessorFeatures {
        [DllImport("kernel32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool IsProcessorFeaturePresent(uint feature);
    }
}
'@
}

$os = Get-CimInstance -ClassName Win32_OperatingSystem
$computer = Get-CimInstance -ClassName Win32_ComputerSystem
$registry = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -Name DisplayVersion, UBR
$processors = @(
    Get-CimInstance -ClassName Win32_Processor | ForEach-Object {
        [ordered]@{
            model = $_.Name.Trim()
            architecture_code = [int]$_.Architecture
            physical_cores = [int]$_.NumberOfCores
            logical_cores = [int]$_.NumberOfLogicalProcessors
        }
    }
)
$graphics = @(Get-CimInstance -ClassName Win32_VideoController | ForEach-Object { $_.Name })

# Avoid outputting a potentially identifying custom power-plan name or GUID.
$plan = powercfg.exe /GETACTIVESCHEME
if ($LASTEXITCODE -ne 0) { throw 'Could not read the active power plan.' }
$planKind = switch -Regex ($plan -join ' ') {
    '381b4222-f694-41f0-9685-ff5bb260df2e' { 'balanced'; break }
    '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c' { 'high_performance'; break }
    'a1841308-3541-4fab-bc81-f71556f20b4a' { 'power_saver'; break }
    default { 'other' }
}

[ordered]@{
    schema_version = 1
    os_caption = $os.Caption
    os_edition = [int]$os.OperatingSystemSKU
    os_release = $registry.DisplayVersion
    os_build = ('{0}.{1}' -f $os.BuildNumber, $registry.UBR)
    os_architecture = $os.OSArchitecture
    process_bits = [IntPtr]::Size * 8
    cpu = $processors
    avx2_available_to_windows = [NoteVive.P0.ProcessorFeatures]::IsProcessorFeaturePresent(40)
    memory_total_bytes = [uint64]$computer.TotalPhysicalMemory
    memory_free_bytes_at_inventory = [uint64]$os.FreePhysicalMemory * 1024
    graphics_models = $graphics
    power_plan_kind = $planKind
} | ConvertTo-Json -Depth 5
