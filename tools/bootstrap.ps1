[CmdletBinding()]
param(
    [string]$SevenZip = 'C:\Program Files\7-Zip\7z.exe',
    [string]$Python = 'python',
    [switch]$AcceptVisualStudioLicense,
    [switch]$ToolsOnly
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$localTools = Join-Path $root '.tools'
$lock = Get-Content (Join-Path $PSScriptRoot 'toolchain.lock.json') -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Force $localTools | Out-Null

function Get-VerifiedDownload($Package, [string]$Name) {
    $destination = Join-Path $localTools $Name
    if (!(Test-Path -LiteralPath $destination) -or
        (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Package.sha256) {
        Write-Host "Downloading $Name"
        Invoke-WebRequest $Package.url -OutFile $destination
    }
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Package.sha256) {
        throw "Checksum mismatch: $Name"
    }
    return $destination
}

function Test-ReXGlueSdk([string]$Path) {
    $executable = Join-Path $Path 'win-amd64/bin/rexglue.exe'
    $config = Join-Path $Path 'win-amd64/lib/cmake/rexglue/rexglueConfig.cmake'
    if (!(Test-Path -LiteralPath $executable -PathType Leaf) -or
        !(Test-Path -LiteralPath $config -PathType Leaf)) {
        return $false
    }
    try {
        $version = (& $executable --version 2>&1 | Out-String).Trim()
        $exitCode = $LASTEXITCODE
    } catch {
        return $false
    }
    return $exitCode -eq 0 -and $version -eq $lock.sdk.version
}

function Write-ReXGlueMarker([string]$Path) {
    $marker = [ordered]@{
        schema = 1
        version = $lock.sdk.version
        commit = $lock.sdk.commit
        releaseTag = $lock.sdk.release_tag
        archiveSha256 = $lock.sdk.sha256
    }
    $marker | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Path '.n3-sdk.json') -Encoding utf8NoBOM
}

function Test-ReXGlueMarker([string]$Path) {
    $markerPath = Join-Path $Path '.n3-sdk.json'
    if (!(Test-Path -LiteralPath $markerPath -PathType Leaf)) { return $false }
    try {
        $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
    } catch {
        return $false
    }
    return $marker.schema -eq 1 -and
        $marker.version -eq $lock.sdk.version -and
        $marker.commit -eq $lock.sdk.commit -and
        $marker.releaseTag -eq $lock.sdk.release_tag -and
        $marker.archiveSha256 -eq $lock.sdk.sha256
}

function Remove-OrdinaryDirectory([string]$Path) {
    if (!(Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    if (!$item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to replace non-directory or linked tool path: $Path"
    }
    Remove-Item -LiteralPath $Path -Recurse -Force
}

$sdkRoot = Join-Path $localTools 'rexglue-sdk'
$staging = Join-Path $localTools 'rexglue-sdk.installing'
$backup = Join-Path $localTools 'rexglue-sdk.previous'
if (!(Test-Path -LiteralPath $sdkRoot) -and (Test-Path -LiteralPath $backup)) {
    $backupItem = Get-Item -LiteralPath $backup -Force
    if (!$backupItem.PSIsContainer -or ($backupItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to recover non-directory or linked SDK backup: $backup"
    }
    Move-Item -LiteralPath $backup -Destination $sdkRoot
}
if (Test-Path -LiteralPath $sdkRoot) {
    $sdkItem = Get-Item -LiteralPath $sdkRoot -Force
    if (!$sdkItem.PSIsContainer -or ($sdkItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to use non-directory or linked SDK path: $sdkRoot"
    }
}
$sdkValid = Test-ReXGlueSdk $sdkRoot
$markerValid = Test-ReXGlueMarker $sdkRoot
if ($sdkValid -and $markerValid) {
    Remove-OrdinaryDirectory $staging
    Remove-OrdinaryDirectory $backup
} else {
    $archive = Get-VerifiedDownload $lock.sdk 'rexglue-sdk.zip'
    Remove-OrdinaryDirectory $staging
    New-Item -ItemType Directory -Path $staging | Out-Null
    try {
        Expand-Archive -LiteralPath $archive -DestinationPath $staging -Force
        if (!(Test-ReXGlueSdk $staging)) {
            throw "Downloaded ReXGlue SDK does not report version $($lock.sdk.version)"
        }
        Write-ReXGlueMarker $staging
        Remove-OrdinaryDirectory $backup
        if (Test-Path -LiteralPath $sdkRoot) {
            $item = Get-Item -LiteralPath $sdkRoot -Force
            if (!$item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw "Refusing to replace non-directory or linked SDK path: $sdkRoot"
            }
            Move-Item -LiteralPath $sdkRoot -Destination $backup
        }
        Move-Item -LiteralPath $staging -Destination $sdkRoot
        Remove-OrdinaryDirectory $backup
    } catch {
        Remove-OrdinaryDirectory $staging
        if (!(Test-Path -LiteralPath $sdkRoot) -and (Test-Path -LiteralPath $backup)) {
            Move-Item -LiteralPath $backup -Destination $sdkRoot
        }
        throw
    }
}
if (!(Test-Path "$localTools/llvm/bin/clang++.exe")) {
    if (!(Test-Path -LiteralPath $SevenZip)) { throw '7-Zip is required to unpack portable LLVM. Pass -SevenZip <path>.' }
    $llvmArchiveName = [System.IO.Path]::GetFileName(([uri]$lock.llvm.url).AbsolutePath)
    $archive = Get-VerifiedDownload $lock.llvm $llvmArchiveName
    & $SevenZip x $archive "-o$localTools/llvm" -y -bso0 -bsp0
    if ($LASTEXITCODE) { throw 'LLVM extraction failed' }
}
$cmakeArchiveName = [System.IO.Path]::GetFileName(([uri]$lock.cmake.url).AbsolutePath)
$cmakeDirectory = [System.IO.Path]::GetFileNameWithoutExtension($cmakeArchiveName)
if (!(Test-Path "$localTools/cmake/$cmakeDirectory/bin/cmake.exe")) {
    $archive = Get-VerifiedDownload $lock.cmake 'cmake.zip'
    Expand-Archive -LiteralPath $archive -DestinationPath "$localTools/cmake" -Force
}
if (!(Test-Path "$localTools/ninja/ninja.exe")) {
    $archive = Get-VerifiedDownload $lock.ninja 'ninja.zip'
    Expand-Archive -LiteralPath $archive -DestinationPath "$localTools/ninja" -Force
}
& $Python (Join-Path $PSScriptRoot 'prepare-rexglue.py')
if ($LASTEXITCODE) { throw 'Patched ReXGlue source preparation failed' }
if (!$ToolsOnly -and !(Test-Path "$localTools/msvc/setup_x64.bat")) {
    if (!$AcceptVisualStudioLicense) {
        throw 'Portable Microsoft tools require their licence. Run with -AcceptVisualStudioLicense or use -ToolsOnly with your own VS 2022 environment.'
    }
    $downloader = Get-VerifiedDownload $lock.msvc_downloader 'portable-msvc.py'
    & $Python (Join-Path $PSScriptRoot 'portable-msvc-guard.py') $downloader
    if ($LASTEXITCODE) { throw 'Portable MSVC setup failed' }
}
Write-Host 'Project-local toolchain ready.'
