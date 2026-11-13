# Optional local engine smoke test, never an acceptance corpus.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$Output,
    [string]$VoiceName
)

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Run this with Windows PowerShell 5.1 on Windows.'
}
Add-Type -AssemblyName System.Speech

$target = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output)
if (Test-Path -LiteralPath $target) { throw 'Output directory already exists.' }
$sentence = 'Bonjour, le microphone est actif. Ceci est un test vocal fictif.'
$synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$audio = [System.IO.MemoryStream]::new()
try {
    $voices = @($synth.GetInstalledVoices() | Where-Object {
        $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'fr-FR' -and
        $_.VoiceInfo.Name -like 'Microsoft *' -and
        (-not $VoiceName -or $_.VoiceInfo.Name -eq $VoiceName)
    } | Sort-Object { $_.VoiceInfo.Name })
    if ($voices.Count -eq 0) { throw 'No matching installed Microsoft SAPI fr-FR voice. Skip this optional test.' }
    $synth.SelectVoice($voices[0].VoiceInfo.Name)
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
        16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    $synth.SetOutputToAudioStream($audio, $format)
    $synth.Speak($sentence)
    $synth.SetOutputToNull()
    $bytes = $audio.ToArray()
}
finally {
    $synth.Dispose()
    $audio.Dispose()
}

if ($bytes.Length -lt 32 -or $bytes.Length % 2 -ne 0) { throw 'Unexpected PCM data size.' }

New-Item -ItemType Directory -Path $target | Out-Null
$wav = [IO.File]::Open((Join-Path $target 'tts-smoke.wav'), [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
$writer = [IO.BinaryWriter]::new($wav)
try {
    # SetOutputToAudioStream returns raw PCM. Write the 44-byte RIFF/WAVE header.
    $ascii = [Text.Encoding]::ASCII
    $writer.Write([byte[]]($ascii.GetBytes('RIFF')))
    $writer.Write([uint32](36 + $bytes.Length))
    $writer.Write([byte[]]($ascii.GetBytes('WAVEfmt ')))
    $writer.Write([uint32]16)
    $writer.Write([uint16]1)
    $writer.Write([uint16]1)
    $writer.Write([uint32]16000)
    $writer.Write([uint32]32000)
    $writer.Write([uint16]2)
    $writer.Write([uint16]16)
    $writer.Write([byte[]]($ascii.GetBytes('data')))
    $writer.Write([uint32]$bytes.Length)
    $writer.Write([byte[]]$bytes)
} finally { $writer.Dispose() }
$index = [IO.File]::Open((Join-Path $target 'smoke.csv'), [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try {
    $encoding = [Text.UTF8Encoding]::new($false)
    $header = 'id,partition,kind,reference,speech_start_ms,speech_end_ms,voice_id,scenario'
    $row = 'tts-smoke,dev,speech,"{0}",,,tts-fr-fr,synthetic-smoke-only' -f $sentence
    $csv = $encoding.GetBytes("$header`n$row`n")
    $index.Write($csv, 0, $csv.Length)
} finally { $index.Dispose() }
Write-Output 'Synthetic smoke WAV created. Do not use its metrics for evaluation.'
