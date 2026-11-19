<#
.SYNOPSIS
Launches a development build with isolated profiles, graphics overrides, setup,
or staged mods.

.EXAMPLE
pwsh -NoProfile -File tools/launch.ps1

.EXAMPLE
pwsh -NoProfile -File tools/launch.ps1 -Profile testing -WindowMode Borderless -FrameRate 40

.EXAMPLE
pwsh -NoProfile -File tools/launch.ps1 -ListMods

.EXAMPLE
pwsh -NoProfile -File tools/launch.ps1 -Mod author.texture,author.model
#>
[CmdletBinding()]
param(
    [ValidateSet('Debug','Release','RelWithDebInfo')][string]$Configuration = 'RelWithDebInfo',
    [ValidateSet('Configured','Windowed','Borderless','Exclusive')][string]$WindowMode = 'Windowed',
    [ValidateRange(320,7680)][int]$Width = 1280,
    [ValidateRange(240,4320)][int]$Height = 720,
    [ValidateRange(0,16)][int]$Monitor = 0,
    [ValidateSet('Configured','Uncapped','Original','30','40','60')][string]$FrameRate = '60',
    [ValidateSet('Configured','English','German','French','Spanish','Italian')][string]$TextLanguage = 'Configured',
    [ValidateSet('Configured','DiscDefault','English','German','French','Spanish','Italian')][string]$VoiceLanguage = 'Configured',
    [ValidateSet('Configured','1','2','4','8','16')][string]$Anisotropic = 'Configured',
    [ValidateSet('Configured','720','1080','1440','2160')][string]$DisplayResolution = 'Configured',
    [ValidateSet('Configured','720','1440','2160')][string]$RenderResolution = 'Configured',
    [ValidateSet('D3D12','Vulkan','Configured')][string]$Renderer = 'D3D12',
    [ValidateSet('Configured','On','Off')][string]$VSync = 'Configured',
    [string]$VoiceDirectory,
    [string]$GameDirectory,
    [switch]$Setup,
    [switch]$ResetGameSelection,
    [string]$Profile,
    [string]$UserDirectory,
    [string]$CacheDirectory,
    [string]$LogDirectory,
    [string]$LogFile,
    [switch]$ListMods,
    [switch]$UseEnabledMods,
    [string]$Mod = '',
    [string]$ModsDirectory,
    [string]$ModOrder,
    [switch]$CopyModBase,
    [switch]$StageOnly,
    [string]$Python = 'python',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$voiceLanguageCodes = [ordered]@{
    'English' = 'ENG'
    'German' = 'GER'
    'French' = 'FRA'
    'Spanish' = 'SPA'
    'Italian' = 'ITA'
}

function Resolve-AbsolutePath([string]$Path) {
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
}

function Test-ReparsePoint([System.IO.FileSystemInfo]$Item) {
    return [bool]($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
}

function Assert-SafePathChain([string]$Path, [string]$Label) {
    $current = [System.IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (Test-ReparsePoint $item) {
                throw "$Label must not use a linked or reparse path: $current"
            }
        }
        $parent = [System.IO.Directory]::GetParent($current)
        if ($null -eq $parent -or $parent.FullName -eq $current) { break }
        $current = $parent.FullName
    }
}

function Resolve-ReadDirectory([string]$Path, [string]$Label) {
    $resolved = Resolve-AbsolutePath $Path
    Assert-SafePathChain $resolved $Label
    if (!(Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "$Label is not a directory: $resolved"
    }
    return $resolved
}

function Resolve-WritableDirectory([string]$Path, [string]$Label, [bool]$Create) {
    $resolved = Resolve-AbsolutePath $Path
    Assert-SafePathChain $resolved $Label
    if (Test-Path -LiteralPath $resolved) {
        if (!(Test-Path -LiteralPath $resolved -PathType Container)) {
            throw "$Label is not a directory: $resolved"
        }
    } elseif ($Create) {
        New-Item -ItemType Directory -Path $resolved -Force | Out-Null
    }
    return $resolved
}

function Resolve-ReadFile([string]$Path, [string]$Label) {
    $resolved = Resolve-AbsolutePath $Path
    Assert-SafePathChain $resolved $Label
    if (!(Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "$Label is not a file: $resolved"
    }
    return $resolved
}

function Get-DiscVoiceBanks([string]$GamePath) {
    $soundPath = Join-Path $GamePath 'data\Sound'
    if (!(Test-Path -LiteralPath $soundPath -PathType Container)) {
        return @()
    }
    $banks = [System.Collections.Generic.List[object]]::new()
    foreach ($languageDirectory in Get-ChildItem -LiteralPath $soundPath -Directory) {
        $soundRes = Join-Path $languageDirectory.FullName 'SoundRes'
        if (!(Test-Path -LiteralPath $soundRes -PathType Container)) {
            continue
        }
        $resolved = Resolve-ReadDirectory $soundRes 'Disc voice directory'
        $displayName = $languageDirectory.Name
        foreach ($entry in $voiceLanguageCodes.GetEnumerator()) {
            if ($entry.Value -ieq $languageDirectory.Name) {
                $displayName = $entry.Key
                break
            }
        }
        $banks.Add([pscustomobject]@{
            name = $displayName
            code = $languageDirectory.Name.ToUpperInvariant()
            directory = $resolved
        })
    }
    return @($banks | Sort-Object code)
}

function Resolve-WritableFile([string]$Path, [string]$Label, [bool]$CreateParent) {
    $resolved = Resolve-AbsolutePath $Path
    Assert-SafePathChain $resolved $Label
    if (Test-Path -LiteralPath $resolved) {
        if (!(Test-Path -LiteralPath $resolved -PathType Leaf)) {
            throw "$Label is not a regular file: $resolved"
        }
    }
    $parent = Split-Path $resolved -Parent
    [void](Resolve-WritableDirectory $parent "$Label parent" $CreateParent)
    return $resolved
}

function Resolve-PythonExecutable {
    $command = Get-Command $Python -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
    return $command.Source
}

function Assert-ProfileName([string]$Name) {
    if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' -or
        $Name -match '^(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)') {
        throw "Invalid profile name '$Name'; use a safe ASCII identifier"
    }
}

$selectedMods = @()
if ($Mod) {
    $seenMods = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($value in $Mod.Split(',')) {
        $modId = $value.Trim()
        if ($modId -notmatch '^[a-z0-9][a-z0-9._-]{0,63}$') {
            throw "Invalid mod ID '$modId'"
        }
        if (!$seenMods.Add($modId)) {
            throw "Duplicate mod ID '$modId'"
        }
        $selectedMods += $modId
    }
}

$stageMods = [bool]$UseEnabledMods -or $selectedMods.Count -gt 0
if ($UseEnabledMods -and $selectedMods.Count) {
    throw '-UseEnabledMods and -Mod are mutually exclusive'
}
if ($ListMods -and ($stageMods -or $CopyModBase -or $StageOnly)) {
    throw '-ListMods cannot be combined with mod staging options'
}
if ($Setup -and $PSBoundParameters.ContainsKey('GameDirectory')) {
    throw '-Setup and -GameDirectory are mutually exclusive'
}
if ($ResetGameSelection -and !$Setup) {
    throw '-ResetGameSelection requires -Setup'
}
if ($Setup -and $stageMods) {
    throw 'Mod staging requires an explicit or default extracted game directory, not -Setup'
}
if ($CopyModBase -and !$stageMods) {
    throw '-CopyModBase requires -UseEnabledMods or -Mod'
}
if ($StageOnly -and !$stageMods) {
    throw '-StageOnly requires -UseEnabledMods or -Mod'
}
if ($PSBoundParameters.ContainsKey('ModOrder') -and !$UseEnabledMods) {
    throw '-ModOrder requires -UseEnabledMods'
}
if ($DisplayResolution -ne 'Configured' -and
    ($PSBoundParameters.ContainsKey('Width') -or $PSBoundParameters.ContainsKey('Height'))) {
    throw '-DisplayResolution cannot be combined with -Width or -Height'
}
if ($VoiceLanguage -ne 'Configured' -and $VoiceDirectory) {
    throw '-VoiceLanguage and -VoiceDirectory are mutually exclusive'
}
if ($Setup -and $VoiceLanguage -ne 'Configured') {
    throw '-VoiceLanguage requires an extracted game directory and cannot be combined with -Setup'
}

$modsPath = if ($ModsDirectory) {
    Resolve-ReadDirectory $ModsDirectory 'ModsDirectory'
} else {
    Resolve-ReadDirectory (Join-Path $root 'mods') 'ModsDirectory'
}

if ($ListMods) {
    $pythonExecutable = Resolve-PythonExecutable
    & $pythonExecutable (Join-Path $PSScriptRoot 'mods.py') list --mods $modsPath
    if ($LASTEXITCODE) { throw "Mod discovery failed ($LASTEXITCODE)" }
    return
}

if ($Profile) {
    Assert-ProfileName $Profile
}
$profileRoot = if ($Profile) {
    Join-Path $root "private/profiles/$Profile"
} else {
    $null
}
$defaultUser = if ($profileRoot) { $profileRoot } else { Join-Path $root 'private/user' }
$defaultCache = if ($profileRoot) { Join-Path $profileRoot 'cache' } else { Join-Path $root 'private/cache' }
$defaultLogDirectory = if ($profileRoot) { Join-Path $profileRoot 'logs' } else { Join-Path $root 'logs' }
$createPaths = !$DryRun
$userPath = Resolve-WritableDirectory $(if ($UserDirectory) { $UserDirectory } else { $defaultUser }) 'UserDirectory' $createPaths
$cachePath = Resolve-WritableDirectory $(if ($CacheDirectory) { $CacheDirectory } else { $defaultCache }) 'CacheDirectory' $createPaths
if ($LogDirectory -and $LogFile) {
    throw '-LogDirectory and the legacy -LogFile option are mutually exclusive'
}
$logRoot = if ($LogFile) {
    Split-Path (Resolve-WritableFile $LogFile 'LogFile' $createPaths) -Parent
} else {
    Resolve-WritableDirectory $(if ($LogDirectory) { $LogDirectory } else { $defaultLogDirectory }) 'LogDirectory' $createPaths
}
$logPath = Join-Path $logRoot 'n3.log'

if ($ResetGameSelection -and !$DryRun) {
    $rememberedPath = Join-Path $userPath 'game-path.txt'
    if (Test-Path -LiteralPath $rememberedPath) {
        Assert-SafePathChain $rememberedPath 'Remembered game selection'
        if (!(Test-Path -LiteralPath $rememberedPath -PathType Leaf)) {
            throw "Remembered game selection is not a regular file: $rememberedPath"
        }
        Remove-Item -LiteralPath $rememberedPath -Force
    }
}

$baseGamePath = $null
if (!$Setup) {
    $requestedGame = if ($GameDirectory) { $GameDirectory } else { Join-Path $root 'private/game' }
    $baseGamePath = Resolve-ReadDirectory $requestedGame 'GameDirectory'
}
$voiceBanks = if ($baseGamePath) { @(Get-DiscVoiceBanks $baseGamePath) } else { @() }
$voicePath = $null
if ($VoiceLanguage -ne 'Configured') {
    $voiceCode = if ($VoiceLanguage -eq 'DiscDefault') {
        'ENG'
    } else {
        $voiceLanguageCodes[$VoiceLanguage]
    }
    $selectedVoice = $voiceBanks | Where-Object code -IEQ $voiceCode | Select-Object -First 1
    if (!$selectedVoice) {
        $available = if ($voiceBanks.Count) {
            ($voiceBanks | ForEach-Object { "$($_.name) ($($_.code))" }) -join ', '
        } else {
            'none'
        }
        throw "Voice language '$VoiceLanguage' is not present in the selected game data. Available disc voice languages: $available"
    }
    $voicePath = $selectedVoice.directory
} elseif ($VoiceDirectory) {
    $voicePath = Resolve-ReadDirectory $VoiceDirectory 'VoiceDirectory'
}

$gamePath = $baseGamePath
$orderPath = $null
$generatedOrder = $null
if ($stageMods) {
    if ($UseEnabledMods) {
        $requestedOrder = if ($ModOrder) { $ModOrder } else { Join-Path $modsPath 'enabled.txt' }
        $orderPath = Resolve-ReadFile $requestedOrder 'ModOrder'
    } elseif (!$DryRun) {
        $orderRoot = Resolve-WritableDirectory (Join-Path $root 'out/launcher') 'Launcher order directory' $true
        $generatedOrder = Join-Path $orderRoot ('.enabled-' + [guid]::NewGuid().ToString('N') + '.txt')
        [System.IO.File]::WriteAllText(
            $generatedOrder,
            ($selectedMods -join "`n") + "`n",
            [System.Text.UTF8Encoding]::new($false)
        )
        $orderPath = $generatedOrder
    } else {
        $orderPath = '<generated-from-Mod>'
    }

    $stageOutput = Resolve-AbsolutePath (Join-Path $root 'out/game')
    if (!$DryRun) {
        $pythonExecutable = Resolve-PythonExecutable
        $modArguments = @(
            (Join-Path $PSScriptRoot 'mods.py'),
            'stage',
            '--game', $baseGamePath,
            '--mods', $modsPath,
            '--order', $orderPath,
            '--output', $stageOutput,
            '--replace'
        )
        if ($CopyModBase) { $modArguments += '--copy-base' }
        try {
            & $pythonExecutable @modArguments
            if ($LASTEXITCODE) { throw "Mod staging failed ($LASTEXITCODE)" }
        } finally {
            if ($generatedOrder -and (Test-Path -LiteralPath $generatedOrder)) {
                Remove-Item -LiteralPath $generatedOrder -Force
            }
        }
        $gamePath = Resolve-ReadDirectory $stageOutput 'Staged game directory'
    } else {
        $gamePath = $stageOutput
    }
}

$preset = 'win-amd64-' + $Configuration.ToLowerInvariant()
$executable = Join-Path $root "out/build/$preset/n3.exe"
$launchArguments = [System.Collections.Generic.List[string]]::new()

switch ($WindowMode) {
    'Windowed' { $launchArguments.Add('--no-ui.fullscreen') }
    'Borderless' {
        $launchArguments.Add('--ui.fullscreen')
        $launchArguments.Add('--no-ui.fullscreen_exclusive')
    }
    'Exclusive' {
        $launchArguments.Add('--ui.fullscreen')
        $launchArguments.Add('--ui.fullscreen_exclusive')
    }
}
if ($PSBoundParameters.ContainsKey('Monitor')) {
    $launchArguments.Add('--ui.monitor')
    $launchArguments.Add("$Monitor")
}
if ($PSBoundParameters.ContainsKey('Width') -or $PSBoundParameters.ContainsKey('Height')) {
    $launchArguments.Add('--ui.window_width')
    $launchArguments.Add("$Width")
    $launchArguments.Add('--ui.window_height')
    $launchArguments.Add("$Height")
}
if ($FrameRate -ne 'Configured') {
    $launchArguments.Add('--n3.frame_rate')
    $launchArguments.Add($(if ($FrameRate -in @('Uncapped','Original')) { '0' } else { $FrameRate }))
}
if ($TextLanguage -ne 'Configured') {
    $launchArguments.Add('--n3.text_language')
    $launchArguments.Add($TextLanguage.ToLowerInvariant())
}
if ($Anisotropic -ne 'Configured') {
    $anisotropicValues = @{
        '1' = '0'
        '2' = '2'
        '4' = '3'
        '8' = '4'
        '16' = '5'
    }
    $launchArguments.Add('--gpu.anisotropic_override')
    $launchArguments.Add($anisotropicValues[$Anisotropic])
}
if ($DisplayResolution -ne 'Configured') {
    $launchArguments.Add('--n3.display_resolution')
    $launchArguments.Add($DisplayResolution)
}
if ($RenderResolution -ne 'Configured') {
    $renderScales = @{
        '720' = '1'
        '1440' = '2'
        '2160' = '3'
    }
    $scale = $renderScales[$RenderResolution]
    foreach ($flag in @('--gpu.resolution_scale_x', '--gpu.resolution_scale_y')) {
        $launchArguments.Add($flag)
        $launchArguments.Add($scale)
    }
}
if ($Renderer -ne 'Configured') {
    $launchArguments.Add('--gpu.driver')
    $launchArguments.Add($Renderer.ToLowerInvariant())
}
switch ($VSync) {
    'On' { $launchArguments.Add('--gpu.vsync') }
    'Off' { $launchArguments.Add('--no-gpu.vsync') }
}
if ($voicePath) {
    $launchArguments.Add('--n3.voice_directory')
    $launchArguments.Add($voicePath)
}
if ($gamePath) {
    $launchArguments.Add('--title.game_root')
    $launchArguments.Add($gamePath)
}
$launchArguments.Add('--app.user_root')
$launchArguments.Add($userPath)
$launchArguments.Add('--app.cache_root')
$launchArguments.Add($cachePath)
$launchArguments.Add('--app.log_root')
$launchArguments.Add($logRoot)

$plan = [ordered]@{
    schemaVersion = 1
    executable = $executable
    configuration = $Configuration
    windowMode = $WindowMode
    renderer = $Renderer
    profile = $(if ($Profile) { $Profile } else { $null })
    setup = [bool]$Setup
    resetGameSelection = [bool]$ResetGameSelection
    voiceLanguage = $VoiceLanguage
    voiceDirectory = $voicePath
    availableVoiceLanguages = @($voiceBanks | ForEach-Object { "$($_.name) ($($_.code))" })
    stageMods = $stageMods
    stageOnly = [bool]$StageOnly
    modSelection = $(if ($UseEnabledMods) { 'enabled.txt' } elseif ($selectedMods.Count) { 'explicit' } else { 'none' })
    modIds = @($selectedMods)
    modOrder = $orderPath
    baseGameDirectory = $baseGamePath
    gameDirectory = $gamePath
    userDirectory = $userPath
    cacheDirectory = $cachePath
    logFile = $logPath
    arguments = $launchArguments.ToArray()
}

if ($DryRun) {
    $plan | ConvertTo-Json -Depth 5
    return
}
if ($StageOnly) {
    Write-Host "Staged mods at $gamePath"
    return
}
if (!(Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw 'Build n3.exe first with tools/build.ps1.'
}

$info = [Diagnostics.ProcessStartInfo]::new()
$info.FileName = $executable
$info.WorkingDirectory = $root
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
foreach ($argument in $launchArguments) {
    $info.ArgumentList.Add($argument)
}
$process = [Diagnostics.Process]::Start($info)
$process.WaitForExit()
$code = $process.ExitCode
$process.Dispose()
if ($code) { throw "n3.exe exited with code $code. See $logPath." }
