[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$')][string]$RunId,
    [ValidateRange(20,240)][int]$Seconds = 120,
    [ValidateSet('Original','0','30','40','60')][string]$FrameRate = '30',
    [ValidatePattern('^(first|0x[0-9a-fA-F]{1,8})$')][string]$Actor = 'first',
    [ValidatePattern('^(all|[0-9]{1,4})$')][string]$Clip = 'all',
    [ValidateSet('actor','resource')][string]$Scope = 'actor',
    [ValidateSet('debug','release','relwithdebinfo')][string]$BuildConfiguration = 'relwithdebinfo',
    [string]$Executable,
    [switch]$Disabled,
    [switch]$NoInput,
    [switch]$ActivateWindow,
    [switch]$QuaternionProbe,
    [switch]$SignalProbe,
    [switch]$AttachmentProbe,
    [ValidateSet('candidate','alternate-weapon-control','second-character')]
    [string]$AttachmentAttempt = 'candidate',
    [switch]$ValidateOnly,
    [ValidateSet('default','dummy','directsound','wasapi')][string]$AudioBackend = 'default'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$rate = if ($FrameRate -in @('Original', '0')) { 0 } else { [int]$FrameRate }
$clockMode = if ($rate -eq 0) { 'original' } else { 'presentation_target' }
if ($Clip -ne 'all' -and [int]$Clip -ge 4096) { throw 'Clip must be between 0 and 4095.' }
if ($Actor -ne 'first' -and [Convert]::ToUInt32($Actor.Substring(2), 16) -eq 0) {
    throw 'The explicit actor address must not be zero.'
}
if ($Scope -eq 'resource' -and $Actor -ne 'first') {
    throw 'Resource scope has no actor binding; explicit actor filters require actor scope.'
}
if ($QuaternionProbe -and $Disabled) { throw 'The quaternion probe requires tracing.' }
if ($SignalProbe -and $Disabled) { throw 'The signal probe requires tracing.' }
if ($AttachmentProbe -and $Disabled) { throw 'The attachment probe requires tracing.' }
if (!$AttachmentProbe -and $AttachmentAttempt -ne 'candidate') {
    throw 'Attachment navigation attempts require the attachment probe.'
}
if ($ValidateOnly) {
    $validated = [ordered]@{
        frame_rate_target = $rate
        clock_mode = $clockMode
        trace_scope = $Scope
        enabled = !$Disabled
    }
    if ($QuaternionProbe) { $validated['quaternion_probe'] = $true }
    if ($SignalProbe) { $validated['signal_probe'] = $true }
    if ($AttachmentProbe) {
        $validated['attachment_probe'] = $true
        $validated['attachment_attempt'] = $AttachmentAttempt
    }
    $validated | ConvertTo-Json -Compress
    return
}
$runRoot = Join-Path $root "private\traces\runtime-instrumentation\$RunId"
if ($Executable) {
    $executable = [IO.Path]::GetFullPath($Executable, $root)
    $privateRoot = [IO.Path]::GetFullPath((Join-Path $root 'private')) + [IO.Path]::DirectorySeparatorChar
    if (!$executable.StartsWith($privateRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The alternate diagnostic executable must be beneath the ignored private directory.'
    }
} else {
    $executable = Join-Path $root "out\build\win-amd64-$BuildConfiguration\n3.exe"
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
$python = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$provenanceScript = 'import json,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from tools.animation_trace_manifest import binary_provenance; print(json.dumps(binary_provenance(Path(sys.argv[2])),sort_keys=True,separators=(",",":")))'
function Get-TraceBinaryProvenance {
    $value = & $python -B -c $provenanceScript $root $executable 2>$null
    if ($LASTEXITCODE -ne 0 -or !$value -or $value -is [array]) {
        throw 'The executable and matching runtime/GPU binary provenance could not be verified.'
    }
    return $value
}
$binaryProvenance = Get-TraceBinaryProvenance
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
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint source, uint target, bool attach);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  public static bool ActivateWindow(IntPtr window) {
    if (SetForegroundWindow(window)) return true;
    IntPtr foreground = GetForegroundWindow();
    uint owner;
    uint foregroundThread = foreground == IntPtr.Zero ? 0 : GetWindowThreadProcessId(foreground, out owner);
    uint currentThread = GetCurrentThreadId();
    bool attached = foregroundThread != 0 && foregroundThread != currentThread &&
                    AttachThreadInput(currentThread, foregroundThread, true);
    try { return attached && SetForegroundWindow(window); }
    finally { if (attached) AttachThreadInput(currentThread, foregroundThread, false); }
  }
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
    if ($window -eq [IntPtr]::Zero -or $Process.HasExited -or !(Test-OwnedForeground $Process)) {
        return $false
    }
    $scan = [N3TraceInput]::MapVirtualKeyW($Key, 0)
    $down = [IntPtr]::new([long](1 -bor ($scan -shl 16)))
    $up = [IntPtr]::new([long](0xc0000001L -bor ($scan -shl 16)))
    $posted = [N3TraceInput]::PostMessageW($window, 0x100, [UIntPtr]::new($Key), $down)
    Start-Sleep -Milliseconds 180
    $released = [N3TraceInput]::PostMessageW($window, 0x101, [UIntPtr]::new($Key), $up)
    return $posted -and $released -and (Test-OwnedForeground $Process)
}

$info = [Diagnostics.ProcessStartInfo]::new()
$info.FileName = $executable
$info.WorkingDirectory = $root
$info.UseShellExecute = $false
foreach ($name in @('N3_ANIM_TRACE', 'N3_ANIM_TRACE_ACTOR', 'N3_ANIM_TRACE_CLIP', 'N3_ANIM_TRACE_SCOPE', 'N3_ANIM_TRACE_QUATERNION', 'N3_ANIM_TRACE_SIGNAL', 'N3_ANIM_TRACE_ATTACHMENT', 'SDL_AUDIO_DRIVER')) {
    [void]$info.Environment.Remove($name)
}
if (!$Disabled) {
    $info.Environment['N3_ANIM_TRACE'] = '1'
    $info.Environment['N3_ANIM_TRACE_ACTOR'] = $Actor.ToLowerInvariant()
    $info.Environment['N3_ANIM_TRACE_CLIP'] = $Clip
    $info.Environment['N3_ANIM_TRACE_SCOPE'] = $Scope
    if ($QuaternionProbe) { $info.Environment['N3_ANIM_TRACE_QUATERNION'] = '1' }
    if ($SignalProbe) { $info.Environment['N3_ANIM_TRACE_SIGNAL'] = '1' }
    if ($AttachmentProbe) { $info.Environment['N3_ANIM_TRACE_ATTACHMENT'] = '1' }
}
if ($AudioBackend -ne 'default') { $info.Environment['SDL_AUDIO_DRIVER'] = $AudioBackend }
foreach ($argument in @(
    '--no-ui.fullscreen', '--ui.window_width', '1280', '--ui.window_height', '720',
    '--gpu.driver', 'd3d12', '--title.game_root', $game,
    '--app.user_root', (Join-Path $runRoot 'user'),
    '--app.cache_root', (Join-Path $runRoot 'cache'),
    '--app.log_root', $runRoot, '--log.file_name', 'host.log',
    '--n3.frame_rate', "$rate", '--hid.mnk_mode',
    '--log.level', 'info', '--log.flush_interval', '1'
)) { $info.ArgumentList.Add($argument) }

$process = $null
$clock = [Diagnostics.Stopwatch]::StartNew()
$closeRequested = $false
$forced = $false
$inputPairs = 0
$directionalKeys = 0
$directionAttempted = $false
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
                [void][N3TraceInput]::ActivateWindow($process.MainWindowHandle)
                Start-Sleep -Milliseconds 100
                $foreground = Test-OwnedForeground $process
            }
            if ($foreground) {
                $foregroundObserved = $true
                # Start and A: skip introductory prompts, then attempt the opening route.
                if ((Send-OwnedKey $process 0x0d) -and (Send-OwnedKey $process 0x20)) { $inputPairs++ }
                if ($AttachmentProbe -and !$directionAttempted -and
                    $AttachmentAttempt -ne 'candidate' -and $clock.Elapsed.TotalSeconds -ge 25) {
                    $directionAttempted = $true
                    $key = if ($AttachmentAttempt -eq 'alternate-weapon-control') { 0x25 } else { 0x27 }
                    if (Send-OwnedKey $process $key) { $directionalKeys++ }
                }
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
    if ((Get-TraceBinaryProvenance) -cne $binaryProvenance) {
        throw 'The executable or runtime/GPU binary changed during the run.'
    }
    $capture = Join-Path $runRoot 'user\animation-trace-v3.json'
    $result = [ordered]@{
        schema = 'n3.runtime-animation-route'
        version = 4
        process_id = $process.Id
        enabled = !$Disabled
        trace_scope = $Scope
        frame_rate_target = $rate
        clock_mode = $clockMode
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
        binary_provenance = ($binaryProvenance | ConvertFrom-Json)
    }
    if ($QuaternionProbe) { $result['quaternion_probe'] = $true }
    if ($SignalProbe) { $result['signal_probe'] = $true }
    if ($AttachmentProbe) {
        $result['attachment_probe'] = $true
        $result['attachment_attempt'] = $AttachmentAttempt
        $result['directional_keys_posted'] = $directionalKeys
        $result['attachment_capture_exists'] =
            (Test-Path -LiteralPath (Join-Path $runRoot 'user\attachment-probe-v1.json') -PathType Leaf)
    }
    $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runRoot 'route.json') -Encoding utf8
    $result | ConvertTo-Json -Compress
} finally {
    if ($process) {
        if (!$process.HasExited) { $process.Kill(); $process.WaitForExit() }
        $process.Dispose()
    }
}
