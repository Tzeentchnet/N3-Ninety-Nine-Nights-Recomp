[CmdletBinding()]
param(
    [ValidateRange(1,64)][int]$Jobs = 4,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$localTools = Join-Path $root '.tools'
$lock = Get-Content (Join-Path $PSScriptRoot 'toolchain.lock.json') -Raw | ConvertFrom-Json
$source = Join-Path $localTools 'rexglue-source'

& $Python (Join-Path $PSScriptRoot 'prepare-rexglue.py') --check
if ($LASTEXITCODE) {
    throw 'The patched ReXGlue source is missing or stale. Run tools/bootstrap.ps1.'
}
$thirdParty = Get-Content (Join-Path $source 'thirdparty\CMakeLists.txt') -Raw
if ($thirdParty -notmatch 'set\(SDL_DUMMYAUDIO ON\)') {
    throw 'The pinned ReXGlue source no longer enables the SDL dummy-audio driver.'
}

& (Join-Path $PSScriptRoot 'build.ps1') -Configuration RelWithDebInfo -Jobs $Jobs -Python $Python
if ($LASTEXITCODE) { throw 'The standard source build failed.' }
& $Python (Join-Path $PSScriptRoot 'bundle-sdk-source.py') --if-needed
if ($LASTEXITCODE) { throw 'The ReXGlue corresponding-source bundle failed.' }

$sdlCommit = (& git -C $source rev-parse HEAD:thirdparty/sdl3 2>$null | Out-String).Trim()
if ($LASTEXITCODE -or $sdlCommit -notmatch '^[0-9a-f]{40}$') {
    throw 'The pinned SDL source commit could not be resolved.'
}
$build = Join-Path $root 'out\build\win-amd64-relwithdebinfo'
$bundleName = "ReXGlue-$($lock.sdk.commit.Substring(0, 7))-corresponding-source.zip"
$result = [ordered]@{
    executable = Join-Path $build 'n3.exe'
    audioSourceArchive = Join-Path $localTools "source-archives\libsdl-org-SDL-$sdlCommit.tar.gz"
    audioLinkedLibrary = Join-Path $build 'SDL3rd.dll'
    audioSdkSourceBundle = Join-Path $root "out\release\$bundleName"
}
foreach ($path in $result.Values) {
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Expected dummy-audio provenance input is missing: $path"
    }
}
$result | ConvertTo-Json
