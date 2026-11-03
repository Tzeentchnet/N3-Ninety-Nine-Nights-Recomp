[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$')][string]$RunId,
    [ValidateRange(20,240)][int]$Seconds = 120,
    [ValidateSet(30,40,60)][int]$FrameRate = 30,
    [ValidatePattern('^(first|0x[0-9a-fA-F]{1,8})$')][string]$Actor = 'first',
    [ValidatePattern('^(all|[0-9]{1,4})$')][string]$Clip = 'all',
    [ValidateSet('actor','resource')][string]$Scope = 'actor',
    [string]$Executable,
    [switch]$Disabled,
    [switch]$NoInput,
    [switch]$ActivateWindow,
    [ValidateSet('default','dummy','directsound','wasapi')][string]$AudioBackend = 'default'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$runRoot = Join-Path $root "private\traces\runtime-instrumentation\$RunId"
if ($Executable) {
    $executable = [IO.Path]::GetFullPath($Executable, $root)
    $privateRoot = [IO.Path]::GetFullPath((Join-Path $root 'private')) + [IO.Path]::DirectorySeparatorChar
    if (!$executable.StartsWith($privateRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The alternate diagnostic executable must be beneath the ignored private directory.'
    }
} else {
    $executable = Join-Path $root 'out\build\win-amd64-relwithdebinfo\n3.exe'
}
$game = Join-Path $root 'private\game'
if (Test-Path -LiteralPath $runRoot) { throw 'The run identifier already exists.' }
for ($current = Split-Path $runRoot -Parent; $current; $current = Split-Path $current -Parent) {
    if ((Test-Path -LiteralPath $current) -and
        ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'The private run directory must not use a linked or reparse path.'
    }
}
if (!(Test-Path -LiteralPath $executable -PathType Leaf) -or
    !(Test-Path -LiteralPath (Join-Path $game 'default.xex') -PathType Leaf)) {
    throw 'Build the game and provide the verified local extraction first.'
}
if ($Clip -ne 'all' -and [int]$Clip -ge 4096) { throw 'Clip must be between 0 and 4095.' }
if ($Actor -ne 'first' -and [Convert]::ToUInt32($Actor.Substring(2), 16) -eq 0) {
    throw 'The explicit actor address must not be zero.'
}
if ($Scope -eq 'resource' -and $Actor -ne 'first') {
    throw 'Resource scope has no actor binding; explicit actor filters require actor scope.'
}
foreach ($directory in @($runRoot, (Join-Path $runRoot 'user'), (Join-Path $runRoot 'cache'))) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

if (!$NoInput) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class N3TraceInput {
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr window, uint message, UIntPtr key, IntPtr data);
  [DllImport("user32.dll")] public static extern uint MapVirtualKeyW(uint code, uint kind);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
}
'@
}

function Test-OwnedForeground([Diagnostics.Process]$Process) {
    $owner = [uint32]0
    $window = [N3TraceInput]::GetForegroundWindow()
    if ($window -eq [IntPtr]::Zero) { return $false }
    [void][N3TraceInput]::GetWindowThreadProcessId($window, [ref]$owner)
    return $owner -eq [uint32]$Process.Id
}

function Send-OwnedKey([Diagnostics.Process]$Process, [uint32]$Key) {
    $Process.Refresh()
    $window = $Process.MainWindowHandle
    if ($window -eq [IntPtr]::Zero -or $Process.HasExited) { return $false }
    $scan = [N3TraceInput]::MapVirtualKeyW($Key, 0)
    $down = [IntPtr]::new([long](1 -bor ($scan -shl 16)))
    $up = [IntPtr]::new([long](0xc0000001L -bor ($scan -shl 16)))
    $posted = [N3TraceInput]::PostMessageW($window, 0x100, [UIntPtr]::new($Key), $down)
    Start-Sleep -Milliseconds 180
    return [N3TraceInput]::PostMessageW($window, 0x101, [UIntPtr]::new($Key), $up) -and $posted
}

$info = [Diagnostics.ProcessStartInfo]::new()
$info.FileName = $executable
$info.WorkingDirectory = $root
$info.UseShellExecute = $false
foreach ($name in @('N3_ANIM_TRACE', 'N3_ANIM_TRACE_ACTOR', 'N3_ANIM_TRACE_CLIP', 'N3_ANIM_TRACE_SCOPE', 'SDL_AUDIO_DRIVER')) {
    [void]$info.Environment.Remove($name)
}
if (!$Disabled) {
    $info.Environment['N3_ANIM_TRACE'] = '1'
    $info.Environment['N3_ANIM_TRACE_ACTOR'] = $Actor.ToLowerInvariant()
    $info.Environment['N3_ANIM_TRACE_CLIP'] = $Clip
    $info.Environment['N3_ANIM_TRACE_SCOPE'] = $Scope
}
if ($AudioBackend -ne 'default') { $info.Environment['SDL_AUDIO_DRIVER'] = $AudioBackend }
foreach ($argument in @(
    '--no-fullscreen', '--window_width', '1280', '--window_height', '720',
    '--game_data_root', $game, '--user_data_root', (Join-Path $runRoot 'user'),
    '--cache_root', (Join-Path $runRoot 'cache'), '--n3_frame_rate', "$FrameRate",
    '--mnk_mode', '--log_file', (Join-Path $runRoot 'host.log'),
    '--log_level', 'info', '--log_flush_interval', '1'
)) { $info.ArgumentList.Add($argument) }

$process = $null
$clock = [Diagnostics.Stopwatch]::StartNew()
$closeRequested = $false
$forced = $false
$inputPairs = 0
$foregroundObserved = $false
$foregroundRequests = 0
$windowObserved = $false
$inputIdleObserved = $false
try {
    $process = [Diagnostics.Process]::Start($info)
    if (!$process) { throw 'The game process did not start.' }
    Write-Output ("Started isolated N3 process PID {0}" -f $process.Id)
    $nextInput = 10.0
    while (!$process.HasExited -and $clock.Elapsed.TotalSeconds -lt ($Seconds - 7)) {
        if (!$inputIdleObserved) {
            $process.Refresh()
            if ($process.MainWindowHandle -ne [IntPtr]::Zero) {
                $windowObserved = $true
                try { $inputIdleObserved = $process.WaitForInputIdle(100) } catch {}
            }
        }
        if (!$NoInput -and $clock.Elapsed.TotalSeconds -ge $nextInput) {
            $process.Refresh()
            $foreground = Test-OwnedForeground $process
            if (!$foreground -and $ActivateWindow -and $process.MainWindowHandle -ne [IntPtr]::Zero) {
                $foregroundRequests++
                [void][N3TraceInput]::SetForegroundWindow($process.MainWindowHandle)
                Start-Sleep -Milliseconds 100
                $foreground = Test-OwnedForeground $process
            }
            if ($foreground) {
                $foregroundObserved = $true
                # Start and A: skip introductory prompts, then attempt the opening route.
                if ((Send-OwnedKey $process 0x0d) -and (Send-OwnedKey $process 0x20)) { $inputPairs++ }
            }
            $nextInput += 5.0
        }
        Start-Sleep -Milliseconds 200
    }
    if (!$process.HasExited) {
        $process.Refresh()
        $closeRequested = $process.CloseMainWindow()
        $remaining = [Math]::Max(0, [int](($Seconds - $clock.Elapsed.TotalSeconds) * 1000))
        if (!$process.WaitForExit($remaining)) {
            $forced = $true
            $process.Kill()
            $process.WaitForExit()
        }
    }
    $capture = Join-Path $runRoot 'user\animation-trace-v2.json'
    $result = [ordered]@{
        schema = 'n3.runtime-animation-route'
        version = 3
        process_id = $process.Id
        enabled = !$Disabled
        trace_scope = $Scope
        frame_rate_target = $FrameRate
        audio_backend = $AudioBackend
        maximum_seconds = $Seconds
        elapsed_seconds = [Math]::Round($clock.Elapsed.TotalSeconds, 3)
        input_pairs_posted = $inputPairs
        foreground_observed = $foregroundObserved
        foreground_requests = $foregroundRequests
        window_observed = $windowObserved
        input_idle_observed = $inputIdleObserved
        close_requested = $closeRequested
        forced_stop = $forced
        exit_code = $process.ExitCode
        capture_exists = (Test-Path -LiteralPath $capture -PathType Leaf)
    }
    $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runRoot 'route.json') -Encoding utf8
    $result | ConvertTo-Json -Compress
} finally {
    if ($process) {
        if (!$process.HasExited) { $process.Kill(); $process.WaitForExit() }
        $process.Dispose()
    }
}
