[CmdletBinding()]
param(
    [ValidateSet('Debug','Release','RelWithDebInfo')][string]$Configuration = 'RelWithDebInfo',
    [ValidateRange(320,7680)][int]$Width = 1280,
    [ValidateRange(240,4320)][int]$Height = 720,
    [ValidateSet('Configured','Original','30','40','60')][string]$FrameRate = 'Configured',
    [ValidateSet('Configured','English','German','French','Spanish','Italian')][string]$TextLanguage = 'Configured',
    [string]$VoiceDirectory
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$preset = 'win-amd64-' + $Configuration.ToLowerInvariant()
$executable = Join-Path $root "out/build/$preset/n3.exe"
if (!(Test-Path $executable)) { throw 'Build n3.exe first with tools/build.ps1.' }
New-Item -ItemType Directory -Force (Join-Path $root 'logs'), (Join-Path $root 'private/user') | Out-Null
Push-Location $root
try {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $executable
    $info.WorkingDirectory = $root
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    if ($FrameRate -ne 'Configured') {
        $info.ArgumentList.Add('--n3_frame_rate')
        $info.ArgumentList.Add($(if ($FrameRate -eq 'Original') { '0' } else { $FrameRate }))
    }
    if ($TextLanguage -ne 'Configured') {
        $info.ArgumentList.Add('--n3_text_language')
        $info.ArgumentList.Add($TextLanguage.ToLowerInvariant())
    }
    if ($VoiceDirectory) {
        $voicePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($VoiceDirectory)
        if (!(Test-Path -LiteralPath $voicePath -PathType Container)) {
            throw "VoiceDirectory is not a directory: $voicePath"
        }
        $info.ArgumentList.Add('--n3_voice_directory')
        $info.ArgumentList.Add($voicePath)
    }
    if ($PSBoundParameters.ContainsKey('Width') -or $PSBoundParameters.ContainsKey('Height')) {
        foreach ($a in @('--window_width', "$Width", '--window_height', "$Height")) { $info.ArgumentList.Add($a) }
    }
    foreach ($argument in @('--no-fullscreen',
        '--game_data_root', (Join-Path $root 'private/game'), '--user_data_root', (Join-Path $root 'private/user'),
        '--cache_root', (Join-Path $root 'private/cache'), '--log_file', (Join-Path $root 'logs/runtime-windowed.log'))) {
        $info.ArgumentList.Add($argument)
    }
    $process = [Diagnostics.Process]::Start($info)
    $process.WaitForExit()
    $code = $process.ExitCode
    $process.Dispose()
    if ($code) { throw "n3.exe exited with code $code. See logs/runtime-windowed.log." }
} finally { Pop-Location }
