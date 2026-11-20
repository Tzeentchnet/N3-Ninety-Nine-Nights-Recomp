[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$launcher = Join-Path $PSScriptRoot 'launch.ps1'
$pwsh = (Get-Command pwsh -CommandType Application -ErrorAction Stop |
    Select-Object -First 1).Source
$checks = 0

function Assert-True([bool]$Condition, [string]$Message) {
    if (!$Condition) { throw $Message }
    $script:checks++
}

function Invoke-Plan([string[]]$Arguments) {
    $output = & $pwsh -NoProfile -File $launcher @Arguments 2>&1
    if ($LASTEXITCODE) {
        throw "Launcher plan failed ($LASTEXITCODE): $($output | Out-String)"
    }
    return ($output | Out-String | ConvertFrom-Json)
}

function Assert-Argument([object]$Plan, [string]$Name) {
    Assert-True ($Plan.arguments -contains $Name) "Missing launcher argument: $Name"
}

function Assert-NoArgument([object]$Plan, [string]$Name) {
    Assert-True ($Plan.arguments -notcontains $Name) "Unexpected launcher argument: $Name"
}

function Assert-ArgumentValue([object]$Plan, [string]$Name, [string]$Value) {
    $index = [Array]::IndexOf([object[]]$Plan.arguments, $Name)
    Assert-True ($index -ge 0) "Missing launcher argument: $Name"
    Assert-True ($index + 1 -lt $Plan.arguments.Count) "Missing value after launcher argument: $Name"
    Assert-True ($Plan.arguments[$index + 1] -eq $Value) "Unexpected value for ${Name}: $($Plan.arguments[$index + 1])"
}

function Assert-Fails([string[]]$Arguments, [string]$Expected) {
    $output = & $pwsh -NoProfile -File $launcher @Arguments 2>&1
    Assert-True ($LASTEXITCODE -ne 0) "Launcher unexpectedly accepted: $($Arguments -join ' ')"
    Assert-True (($output | Out-String) -match [regex]::Escape($Expected)) "Launcher failed for the wrong reason: $($output | Out-String)"
}

$default = Invoke-Plan @('-DryRun', '-Setup')
Assert-True ($default.schemaVersion -eq 1) 'Unexpected launcher plan schema'
Assert-True ($default.windowMode -eq 'Windowed') 'Default launcher mode is not Windowed'
Assert-True ([bool]$default.setup) 'Setup plan did not retain setup mode'
Assert-Argument $default '--no-ui.fullscreen'
Assert-NoArgument $default '--title.game_root'
Assert-ArgumentValue $default '--app.user_root' (Join-Path $root 'private/user')
Assert-ArgumentValue $default '--app.cache_root' (Join-Path $root 'private/cache')
Assert-ArgumentValue $default '--app.log_root' (Join-Path $root 'logs')
Assert-ArgumentValue $default '--gpu.driver' 'd3d12'
Assert-ArgumentValue $default '--gpu.xenos.present_effect' 'fsr1'
Assert-ArgumentValue $default '--n3.frame_rate' '60'
Assert-True ($default.upscaler -eq 'FSR1') 'Default launcher upscaler is not FSR1'

$reset = Invoke-Plan @('-DryRun', '-ResetGameSelection')
Assert-True ([bool]$reset.setup) 'Game-selection reset did not imply setup mode'
Assert-True ([bool]$reset.resetGameSelection) 'Game-selection reset was not retained'
Assert-NoArgument $reset '--title.game_root'

$graphics = Invoke-Plan @(
    '-DryRun',
    '-Setup',
    '-Profile', 'test-profile',
    '-WindowMode', 'Exclusive',
    '-Monitor', '2',
    '-FrameRate', 'Original',
    '-TextLanguage', 'Spanish',
    '-Anisotropic', '16',
    '-DisplayResolution', '1080',
    '-RenderResolution', '2160',
    '-Renderer', 'Vulkan',
    '-Upscaler', 'Bilinear',
    '-VSync', 'Off'
)
Assert-Argument $graphics '--ui.fullscreen'
Assert-Argument $graphics '--ui.fullscreen_exclusive'
Assert-NoArgument $graphics '--no-ui.fullscreen'
Assert-ArgumentValue $graphics '--ui.monitor' '2'
Assert-ArgumentValue $graphics '--n3.frame_rate' '0'
Assert-ArgumentValue $graphics '--n3.text_language' 'spanish'
Assert-ArgumentValue $graphics '--gpu.anisotropic_override' '5'
Assert-ArgumentValue $graphics '--n3.display_resolution' '1080'
Assert-ArgumentValue $graphics '--gpu.resolution_scale_x' '3'
Assert-ArgumentValue $graphics '--gpu.resolution_scale_y' '3'
Assert-ArgumentValue $graphics '--gpu.driver' 'vulkan'
Assert-ArgumentValue $graphics '--gpu.xenos.present_effect' 'bilinear'
Assert-Argument $graphics '--no-gpu.vsync'
Assert-True ($graphics.userDirectory -eq (Join-Path $root 'private/profiles/test-profile')) 'Named profile user path is incorrect'
Assert-True ($graphics.cacheDirectory -eq (Join-Path $root 'private/profiles/test-profile/cache')) 'Named profile cache path is incorrect'
Assert-True ($graphics.logFile -eq (Join-Path $root 'private/profiles/test-profile/logs/n3.log')) 'Named profile log path is incorrect'

$uncapped = Invoke-Plan @('-DryRun', '-Setup', '-FrameRate', 'Uncapped')
Assert-ArgumentValue $uncapped '--n3.frame_rate' '0'

$window = Invoke-Plan @(
    '-DryRun',
    '-Setup',
    '-WindowMode', 'Borderless',
    '-Width', '1920',
    '-Height', '1080',
    '-Renderer', 'Configured',
    '-Upscaler', 'Configured',
    '-VSync', 'On'
)
Assert-Argument $window '--ui.fullscreen'
Assert-Argument $window '--no-ui.fullscreen_exclusive'
Assert-ArgumentValue $window '--ui.window_width' '1920'
Assert-ArgumentValue $window '--ui.window_height' '1080'
Assert-NoArgument $window '--gpu.driver'
Assert-NoArgument $window '--gpu.xenos.present_effect'
Assert-Argument $window '--gpu.vsync'

$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ('n3-launch-test-' + [guid]::NewGuid().ToString('N'))
$game = Join-Path $temporary 'game'
$mods = Join-Path $temporary 'mods'
$englishVoice = Join-Path $game 'data\Sound\ENG\SoundRes'
$frenchVoice = Join-Path $game 'data\Sound\FRA\SoundRes'
$customVoice = Join-Path $temporary 'custom-voice'
New-Item -ItemType Directory -Path $game,$mods,$englishVoice,$frenchVoice,$customVoice -Force |
    Out-Null
try {
    $discDefaultVoice = Invoke-Plan @(
        '-DryRun',
        '-GameDirectory', $game,
        '-VoiceLanguage', 'DiscDefault'
    )
    Assert-ArgumentValue $discDefaultVoice '--n3.voice_directory' $englishVoice
    Assert-True ($discDefaultVoice.voiceLanguage -eq 'DiscDefault') 'Disc-default voice choice changed'
    Assert-True (($discDefaultVoice.availableVoiceLanguages -join ',') -eq
        'English (ENG),French (FRA)') 'Disc voice discovery changed'

    $frenchDiscVoice = Invoke-Plan @(
        '-DryRun',
        '-GameDirectory', $game,
        '-VoiceLanguage', 'French'
    )
    Assert-ArgumentValue $frenchDiscVoice '--n3.voice_directory' $frenchVoice
    Assert-True ($frenchDiscVoice.voiceDirectory -eq $frenchVoice) 'Selected disc voice path changed'

    $customVoicePlan = Invoke-Plan @(
        '-DryRun',
        '-GameDirectory', $game,
        '-VoiceDirectory', $customVoice
    )
    Assert-ArgumentValue $customVoicePlan '--n3.voice_directory' $customVoice

    $modded = Invoke-Plan @(
        '-DryRun',
        '-GameDirectory', $game,
        '-ModsDirectory', $mods,
        '-Mod', 'author.first,author.second',
        '-CopyModBase'
    )
    Assert-True ([bool]$modded.stageMods) 'Explicit mods did not enable staging'
    Assert-True ($modded.modSelection -eq 'explicit') 'Explicit mod selection mode is incorrect'
    Assert-True (($modded.modIds -join ',') -eq 'author.first,author.second') 'Explicit mod order changed'
    Assert-True ($modded.baseGameDirectory -eq $game) 'Base game directory changed'
    Assert-True ($modded.gameDirectory -eq (Join-Path $root 'out/game')) 'Staged game directory is incorrect'
    Assert-ArgumentValue $modded '--title.game_root' (Join-Path $root 'out/game')

    Assert-Fails @('-DryRun', '-Setup', '-GameDirectory', $game) '-Setup and -GameDirectory are mutually exclusive'
    Assert-Fails @('-DryRun', '-Setup', '-DisplayResolution', '1080', '-Width', '1920') '-DisplayResolution cannot be combined'
    Assert-Fails @('-DryRun', '-Setup', '-UseEnabledMods', '-Mod', 'author.first') 'mutually exclusive'
    Assert-Fails @('-DryRun', '-Setup', '-ResetGameSelection', '-UseEnabledMods') 'Mod staging requires'
    Assert-Fails @('-DryRun', '-GameDirectory', $game, '-VoiceLanguage', 'Italian') "Voice language 'Italian' is not present"
    Assert-Fails @('-DryRun', '-GameDirectory', $game, '-VoiceLanguage', 'English', '-VoiceDirectory', $customVoice) '-VoiceLanguage and -VoiceDirectory are mutually exclusive'
    Assert-Fails @('-DryRun', '-Setup', '-VoiceLanguage', 'English') '-VoiceLanguage requires an extracted game directory'
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}

Write-Output "Launcher option tests passed: $checks checks"
