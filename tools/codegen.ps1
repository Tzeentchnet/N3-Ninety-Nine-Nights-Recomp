[CmdletBinding()]
param(
    [switch]$Regenerate,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$sdk = Join-Path $root '.tools/rexglue-sdk/win-amd64/bin/rexglue.exe'
if (!(Test-Path $sdk)) { throw 'Run tools/bootstrap.ps1 first.' }
$lock = Get-Content (Join-Path $PSScriptRoot 'toolchain.lock.json') -Raw | ConvertFrom-Json
$sdkVersion = (& $sdk --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $sdkVersion -ne $lock.sdk.version) {
    throw "Installed ReXGlue SDK is '$sdkVersion'; expected '$($lock.sdk.version)'. Run tools/bootstrap.ps1."
}
$expected = Get-Content (Join-Path $root 'docs/game-build.json') -Raw | ConvertFrom-Json
$xex = Join-Path $root 'private/game/default.xex'
if (!(Test-Path $xex)) { throw 'Extract the game first; see README.md.' }
if ((Get-FileHash $xex -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected.xexSha256) {
    throw 'Unsupported executable revision. Review the function hints before adding another build.'
}
Push-Location $root
try {
    New-Item -ItemType Directory -Force logs | Out-Null
    $arguments = @('--log-file', 'logs/codegen.log', 'codegen', 'n3_manifest.toml')
    if ($Regenerate) { $arguments += '--ignore-stamp' }
    & $sdk @arguments
    if ($LASTEXITCODE) { throw "Strict code generation failed ($LASTEXITCODE). See logs/codegen.log." }
    & $Python (Join-Path $PSScriptRoot 'fix_generated_cmake.py')
    if ($LASTEXITCODE) { throw 'Generated CMake integration failed.' }
} finally { Pop-Location }
