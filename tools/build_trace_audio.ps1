[CmdletBinding()]
param(
    [ValidateRange(1,64)][int]$Jobs = 4,
    [switch]$ContinueRuntime,
    [switch]$StageExistingRuntime,
    [switch]$RebuildGame
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$localTools = Join-Path $root '.tools'
$work = Join-Path $root 'private\traces\runtime-instrumentation\local-sdl-dummy'
$archive = Join-Path $localTools 'source-archives\libsdl-org-SDL-147a8ee32dbf9ac02f3794964490687b6bbda1bc.tar.gz'
$expected = '29d9362282d347b8ae25c7f572a535e72de0749e60528abb1523daaf43d072fd'
$bundle = Join-Path $root 'out\release\ReXGlue-bd833a2-corresponding-source.zip'
$expectedBundle = 'eeb2b390ae97cf319f4c8cb01032c77f3148941dc0026a41c7784c76375b88d2'
if ((Test-Path -LiteralPath $work) -and !$ContinueRuntime) {
    throw 'The local SDL diagnostic build already exists.'
}
if ($ContinueRuntime -and !(Test-Path -LiteralPath "$work\game-build\n3.exe" -PathType Leaf)) {
    throw 'The diagnostic game build is missing; start a fresh build instead.'
}
if ($StageExistingRuntime -and !$ContinueRuntime) {
    throw 'Staging an existing runtime also requires -ContinueRuntime.'
}
if ($RebuildGame -and (!$ContinueRuntime -or !$StageExistingRuntime)) {
    throw 'Rebuilding the diagnostic game requires -ContinueRuntime and -StageExistingRuntime.'
}
if (!(Test-Path -LiteralPath $archive -PathType Leaf) -or
    (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    throw 'The pinned local SDL source archive is missing or has changed; no download was attempted.'
}
if (!(Test-Path -LiteralPath $bundle -PathType Leaf) -or
    (Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedBundle) {
    throw 'The pinned local SDK source bundle is missing or has changed; no download was attempted.'
}
for ($current = Split-Path $work -Parent; $current; $current = Split-Path $current -Parent) {
    if ((Test-Path -LiteralPath $current) -and
        ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'The private build directory must not use a linked or reparse path.'
    }
}
$lock = Get-Content (Join-Path $PSScriptRoot 'toolchain.lock.json') -Raw | ConvertFrom-Json
$cmakeArchive = [IO.Path]::GetFileName(([uri]$lock.cmake.url).AbsolutePath)
$cmakeDir = [IO.Path]::GetFileNameWithoutExtension($cmakeArchive)
$cmake = Join-Path $localTools "cmake\$cmakeDir\bin\cmake.exe"
$sdk = Join-Path $localTools 'rexglue-sdk\win-amd64'
$python = (Get-Command python -CommandType Application | Select-Object -First 1).Source
if (!(Test-Path -LiteralPath $cmake) -or !(Test-Path -LiteralPath "$sdk\bin\rexglue.exe") -or
    !(Test-Path -LiteralPath "$localTools\msvc\setup_x64.bat")) {
    throw 'The project-standard local toolchain is incomplete.'
}
if ((& "$sdk\bin\rexglue.exe" --version | Out-String).Trim() -ne $lock.sdk.version) {
    throw 'The installed ReXGlue SDK does not match the project lock.'
}

$saved = @{}
foreach ($name in @('PATH','INCLUDE','LIB','VCToolsInstallDir','WindowsSdkDir','WindowsSDKVersion','TMP','TEMP')) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
New-Item -ItemType Directory -Force $work | Out-Null
function Replace-Once([string]$Path, [string]$Before, [string]$After) {
    $text = [IO.File]::ReadAllText($Path)
    if ($text.IndexOf($Before, [StringComparison]::Ordinal) -lt 0 -or
        $text.IndexOf($Before, [StringComparison]::Ordinal) -ne
        $text.LastIndexOf($Before, [StringComparison]::Ordinal)) {
        throw 'The local SDK source did not match the pinned diagnostic patch.'
    }
    [IO.File]::WriteAllText($Path, $text.Replace($Before, $After), [Text.UTF8Encoding]::new($false))
}
function Export-Names([string]$Path) {
    $symbols = & "$localTools\llvm\bin\llvm-readobj.exe" --coff-exports $Path
    if ($LASTEXITCODE) { throw 'Could not inspect runtime DLL exports.' }
    return @($symbols | Where-Object { $_ -match '^\s*Name: ' } |
        ForEach-Object { $_.Trim().Substring(6) } | Sort-Object -Unique -CaseSensitive)
}
function Runtime-Imports([string]$Path) {
    $lines = & "$localTools\llvm\bin\llvm-readobj.exe" --coff-imports $Path
    if ($LASTEXITCODE) { throw 'Could not inspect diagnostic binary imports.' }
    $inside = $false
    foreach ($line in $lines) {
        if ($line -match '^\s*Name: rexruntimerd\.dll$') { $inside = $true }
        elseif ($inside -and $line -match '^}') { $inside = $false }
        elseif ($inside -and $line -match '^\s*Symbol: (.+?) \(\d+\)$') { $Matches[1] }
        elseif ($inside -and $line -match '^\s*Symbol: \(') {
            throw 'Ordinal-only runtime imports cannot be validated.'
        }
    }
}
try {
    $vc = Get-ChildItem "$localTools\msvc\VC\Tools\MSVC" -Directory | Sort-Object Name -Descending | Select-Object -First 1
    $kit = "$localTools\msvc\Windows Kits\10"
    $version = (Get-ChildItem "$kit\Include" -Directory | Sort-Object Name -Descending | Select-Object -First 1).Name
    $env:VCToolsInstallDir = "$($vc.FullName)\"
    $env:WindowsSdkDir = "$kit\"
    $env:WindowsSDKVersion = "$version\"
    $env:INCLUDE = "$($vc.FullName)\include;$kit\Include\$version\ucrt;$kit\Include\$version\shared;$kit\Include\$version\um;$kit\Include\$version\winrt"
    $env:LIB = "$($vc.FullName)\lib\x64;$kit\Lib\$version\ucrt\x64;$kit\Lib\$version\um\x64"
    $env:PATH = "$localTools\llvm\bin;$localTools\ninja;$($vc.FullName)\bin\Hostx64\x64;$kit\bin\$version\x64;$env:PATH"
    $env:TMP = $work
    $env:TEMP = $work
    if (!$ContinueRuntime) {
        New-Item -ItemType Directory -Path "$work\source" | Out-Null
        & tar -xf $archive --strip-components=1 -C "$work\source"
        if ($LASTEXITCODE) { throw 'Local SDL source extraction failed.' }
        & $cmake -S "$work\source" -B "$work\sdl-build" -G Ninja `
            -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_BUILD_TYPE=RelWithDebInfo `
            -DSDL_SHARED=OFF -DSDL_STATIC=ON -DSDL_TESTS=OFF -DSDL_TEST_LIBRARY=OFF `
            -DSDL_DUMMYAUDIO=ON -DSDL_DISKAUDIO=OFF -DSDL_INSTALL=ON `
            "-DCMAKE_INSTALL_PREFIX=$work\sdl-install"
        if ($LASTEXITCODE) { throw 'Local SDL diagnostic configure failed.' }
        & $cmake --build "$work\sdl-build" --target SDL3-static --parallel $Jobs
        if ($LASTEXITCODE) { throw 'Local SDL diagnostic build failed.' }
        & $cmake --install "$work\sdl-build"
        if ($LASTEXITCODE) { throw 'Local SDL diagnostic staging failed.' }
    }
    $sdlConfig = Get-ChildItem "$work\sdl-install" -Filter SDL3Config.cmake -File -Recurse | Select-Object -First 1
    if (!$sdlConfig) { throw 'The local SDL CMake package was not generated.' }
    if (!$ContinueRuntime) {
        & $cmake -S $root -B "$work\game-build" -G Ninja `
            -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_BUILD_TYPE=RelWithDebInfo `
            "-DCMAKE_PREFIX_PATH=$sdk" "-DSDL3_DIR=$($sdlConfig.DirectoryName)" `
            "-DPython3_EXECUTABLE=$python" -DBUILD_TESTING=OFF
        if ($LASTEXITCODE) { throw 'Diagnostic game configure failed.' }
        & $cmake --build "$work\game-build" --target n3 --parallel $Jobs
        if ($LASTEXITCODE) { throw 'Diagnostic game build failed.' }
    } elseif ($RebuildGame) {
        & $cmake --build "$work\game-build" --target n3 --parallel $Jobs
        if ($LASTEXITCODE) { throw 'Diagnostic game rebuild failed.' }
    }
    $runtimeSource = "$work\sdk-source-bundle"
    $sdkSource = "$runtimeSource\rexglue-sdk"
    if (!$StageExistingRuntime) {
        if (Test-Path -LiteralPath $runtimeSource) { throw 'The private SDK source copy already exists.' }
        Expand-Archive -LiteralPath $bundle -DestinationPath $runtimeSource
        foreach ($module in @('cli11','libmspack','FFmpeg','tomlplusplus','simde','xxHash',
                              'spdlog','fmt','utfcpp','imgui','sdl3','tracy')) {
            New-Item -ItemType Directory -Force "$sdkSource\thirdparty\$module\.git" | Out-Null
        }
        $thirdParty = "$sdkSource\thirdparty\CMakeLists.txt"
        Replace-Once $thirdParty 'set(SDL_DUMMYAUDIO OFF CACHE BOOL "" FORCE)' `
            'set(SDL_DUMMYAUDIO ON CACHE BOOL "" FORCE)'
        Replace-Once $thirdParty 'add_subdirectory(sdl3)' '# The parent imports the local diagnostic SDL package.'
        Replace-Once $thirdParty 'libmspack/cabextract/mspack' 'libmspack/libmspack/mspack'
        $sdkCmake = "$sdkSource\CMakeLists.txt"
        Replace-Once $sdkCmake 'add_subdirectory(thirdparty)' `
            "find_package(SDL3 CONFIG REQUIRED)`nadd_subdirectory(thirdparty)"
        $text = [IO.File]::ReadAllText($sdkCmake)
        $pattern = 'rex_resolve_version\(REXGLUE_FULL_VERSION\s+FLOOR_MAJOR \$\{PROJECT_VERSION_MAJOR\}\s+FLOOR_MINOR \$\{PROJECT_VERSION_MINOR\}\s+SOURCE_DIR "\$\{CMAKE_CURRENT_SOURCE_DIR\}"\s*\)'
        if ([regex]::Matches($text, $pattern).Count -ne 1) { throw 'The SDK version definition changed.' }
        $text = [regex]::Replace($text, $pattern, "set(REXGLUE_FULL_VERSION `"$($lock.sdk.version)`")")
        [IO.File]::WriteAllText($sdkCmake, $text, [Text.UTF8Encoding]::new($false))
        & $cmake -S $sdkSource -B "$work\runtime-build" -G Ninja `
            -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_BUILD_TYPE=RelWithDebInfo `
            "-DSDL3_DIR=$($sdlConfig.DirectoryName)" -DREXGLUE_BUILD_TESTS=OFF -DREXGLUE_USE_VULKAN=OFF
        if ($LASTEXITCODE) { throw 'Diagnostic runtime configure failed.' }
        & $cmake --build "$work\runtime-build" --target rexruntime --parallel $Jobs
        if ($LASTEXITCODE) { throw 'Diagnostic runtime build failed.' }
    }
    $oldRuntime = "$work\game-build\rexruntimerd.dll"
    $newRuntime = "$sdkSource\out\win-amd64\rexruntimerd.dll"
    if (!(Test-Path -LiteralPath $oldRuntime) -or !(Test-Path -LiteralPath $newRuntime) -or
        !(Test-Path -LiteralPath "$work\runtime-build\build.ninja")) {
        throw 'The expected runtime DLLs are missing.'
    }
    $graph = [IO.File]::ReadAllText("$work\runtime-build\build.ninja").Replace('\', '/')
    if (!$graph.Contains('local-sdl-dummy/sdl-install/lib/SDL3-static.lib')) {
        throw 'The diagnostic runtime was not linked against the local SDL library.'
    }
    $exportSet = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($symbol in (Export-Names $newRuntime)) { [void]$exportSet.Add($symbol) }
    foreach ($binary in @("$work\game-build\n3.exe", "$work\game-build\rexgpu-xenosrd.dll")) {
        $imports = @(Runtime-Imports $binary)
        if (!$imports.Count) { throw 'The runtime imports could not be validated.' }
        foreach ($symbol in $imports) {
            if (!$exportSet.Contains($symbol)) { throw 'The diagnostic runtime is missing a required import.' }
        }
    }
    $backup = "$work\standard-rexruntimerd.dll"
    if (Test-Path -LiteralPath $backup) {
        $existingHash = (Get-FileHash -LiteralPath $oldRuntime -Algorithm SHA256).Hash
        if ($existingHash -ne (Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash -and
            $existingHash -ne (Get-FileHash -LiteralPath $newRuntime -Algorithm SHA256).Hash) {
            throw 'The diagnostic runtime destination contains an unexpected DLL.'
        }
    } else {
        Copy-Item -LiteralPath $oldRuntime -Destination $backup
    }
    if ((Get-FileHash -LiteralPath $oldRuntime -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath $newRuntime -Algorithm SHA256).Hash) {
        Copy-Item -LiteralPath $newRuntime -Destination $oldRuntime -Force
    }
    Write-Output 'Local dummy-audio diagnostic executable and matching runtime DLL built under the ignored private trace directory.'
} finally {
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
}
