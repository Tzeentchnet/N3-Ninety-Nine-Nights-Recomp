[CmdletBinding()]
param(
    [ValidateSet('Debug','Release','RelWithDebInfo')][string]$Configuration = 'RelWithDebInfo',
    [ValidateRange(1,64)][int]$Jobs = 4,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$localTools = Join-Path $root '.tools'
$lock = Get-Content (Join-Path $PSScriptRoot 'toolchain.lock.json') -Raw | ConvertFrom-Json
$cmakeArchiveName = [System.IO.Path]::GetFileName(([uri]$lock.cmake.url).AbsolutePath)
$cmakeDirectory = [System.IO.Path]::GetFileNameWithoutExtension($cmakeArchiveName)
$cmake = Join-Path $localTools "cmake/$cmakeDirectory/bin/cmake.exe"
$ctest = Join-Path $localTools "cmake/$cmakeDirectory/bin/ctest.exe"
if (!(Test-Path $cmake)) { throw 'Run tools/bootstrap.ps1 first.' }
$sdk = Join-Path $localTools 'rexglue-sdk/win-amd64/bin/rexglue.exe'
if (!(Test-Path $sdk)) { throw 'Run tools/bootstrap.ps1 first.' }
$sdkVersion = (& $sdk --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $sdkVersion -ne $lock.sdk.version) {
    throw "Installed ReXGlue SDK is '$sdkVersion'; expected '$($lock.sdk.version)'. Run tools/bootstrap.ps1."
}
$pythonCommand = Get-Command $Python -CommandType Application -ErrorAction Stop |
    Select-Object -First 1
$pythonExecutable = $pythonCommand.Source
$saved = @{}
foreach ($name in @('PATH','INCLUDE','LIB','VCToolsInstallDir','WindowsSdkDir','WindowsSDKVersion')) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
Push-Location $root
try {
    & $pythonExecutable (Join-Path $PSScriptRoot 'bundle-sdk-source.py') --if-needed
    if ($LASTEXITCODE) { throw 'Pinned SDK source preparation failed.' }
    & $pythonExecutable (Join-Path $PSScriptRoot 'prepare-gpu.py')
    if ($LASTEXITCODE) { throw 'GPU extension preparation failed.' }
    if (Test-Path "$localTools/msvc/setup_x64.bat") {
        $vc = Get-ChildItem "$localTools/msvc/VC/Tools/MSVC" -Directory | Sort-Object Name -Descending | Select-Object -First 1
        $kit = "$localTools/msvc/Windows Kits/10"
        $version = (Get-ChildItem "$kit/Include" -Directory | Sort-Object Name -Descending | Select-Object -First 1).Name
        $env:VCToolsInstallDir = "$($vc.FullName)/"
        $env:WindowsSdkDir = "$kit/"
        $env:WindowsSDKVersion = "$version/"
        $env:INCLUDE = "$($vc.FullName)/include;$kit/Include/$version/ucrt;$kit/Include/$version/shared;$kit/Include/$version/um;$kit/Include/$version/winrt"
        $env:LIB = "$($vc.FullName)/lib/x64;$kit/Lib/$version/ucrt/x64;$kit/Lib/$version/um/x64"
        $env:PATH = "$($vc.FullName)/bin/Hostx64/x64;$kit/bin/$version/x64;$env:PATH"
    }
    $env:PATH = "$localTools/llvm/bin;$localTools/ninja;$env:PATH"
    & (Join-Path $PSScriptRoot 'codegen.ps1') -Python $pythonExecutable
    $preset = 'win-amd64-' + $Configuration.ToLowerInvariant()
    & $cmake --preset $preset "-DCMAKE_PREFIX_PATH=$localTools/rexglue-sdk/win-amd64" `
        "-DPython3_EXECUTABLE=$pythonExecutable"
    if ($LASTEXITCODE) { throw 'CMake configure failed.' }
    & $cmake --build --preset $preset --parallel $Jobs
    if ($LASTEXITCODE) { throw 'Native build failed.' }
    & $ctest --test-dir "out/build/$preset" --output-on-failure
    if ($LASTEXITCODE) { throw 'Native regression test failed.' }
    Write-Host "Built out/build/$preset/n3.exe"
} finally {
    Pop-Location
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
}
