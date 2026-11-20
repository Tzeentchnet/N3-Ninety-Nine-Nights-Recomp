[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$RequestFile,
    [Parameter(Mandatory)][string]$EventFile
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$localTools = Join-Path $root '.tools'
$downloads = Join-Path $localTools 'downloads'
$lockPath = Join-Path $PSScriptRoot 'toolchain.lock.json'
$eventWriter = $null

function Write-SetupEvent(
    [string]$Type,
    [string]$Message,
    [int]$Progress = -1,
    [hashtable]$Details = @{}
) {
    $event = [ordered]@{
        type = $Type
        message = $Message
    }
    if ($Progress -ge 0) { $event.progress = $Progress }
    foreach ($name in $Details.Keys) { $event[$name] = $Details[$name] }
    $script:eventWriter.WriteLine(($event | ConvertTo-Json -Compress -Depth 5))
}

function Remove-OrdinaryDirectory([string]$Path) {
    if (!(Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    if (!$item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to remove non-directory or linked setup path: $Path"
    }
    Remove-Item -LiteralPath $Path -Recurse -Force
}

function Remove-OrdinaryFile([string]$Path) {
    if (!(Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to remove non-file or linked setup path: $Path"
    }
    Remove-Item -LiteralPath $Path -Force
}

function Initialize-OrdinaryDirectory([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force
        if (!$item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Setup directory must not be a file or linked path: $Path"
        }
        return
    }
    New-Item -ItemType Directory -Path $Path | Out-Null
}

function Get-Sha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return -join ($algorithm.ComputeHash($stream) |
            ForEach-Object { $_.ToString('x2') })
    } finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}

function Get-VerifiedDownload($Package) {
    $destination = Join-Path $downloads $Package.archive_name
    $partial = "$destination.partial"
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        $observed = Get-Sha256 $destination
        if ($observed -eq $Package.sha256) { return $destination }
        Remove-OrdinaryFile $destination
    }
    Remove-OrdinaryFile $partial
    Write-SetupEvent 'log' "Downloading $($Package.archive_name)"
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Package.url -OutFile $partial
        $observed = Get-Sha256 $partial
        if ($observed -ne $Package.sha256) {
            throw "Checksum mismatch for $($Package.archive_name)"
        }
        Move-Item -LiteralPath $partial -Destination $destination
    } catch {
        Remove-OrdinaryFile $partial
        throw
    }
    return $destination
}

function Get-ToolExecutable([string]$Target, $Package) {
    return Join-Path $Target $Package.executable
}

function Test-InstalledTool([string]$Target, [string]$Name, $Package) {
    $markerPath = Join-Path $Target '.n3-setup-tool.json'
    $executable = Get-ToolExecutable $Target $Package
    if (!(Test-Path -LiteralPath $markerPath -PathType Leaf) -or
        !(Test-Path -LiteralPath $executable -PathType Leaf)) {
        return $false
    }
    try {
        $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
        if ($marker.schema -ne 3 -or
            $marker.version -ne $Package.version -or
            $marker.sha256 -ne $Package.sha256) {
            return $false
        }
        $output = switch ($Name) {
            'powershell' {
                & $executable -NoProfile -Command '$PSVersionTable.PSVersion.ToString()' 2>&1
            }
            'python' { & $executable --version 2>&1 }
            'node' { & $executable --version 2>&1 }
            'seven_zip' { & $executable i 2>&1 | Select-Object -First 3 }
            'git' { & $executable --version 2>&1 }
            default { return $false }
        }
        if ($LASTEXITCODE -ne 0) { return $false }
        $text = ($output | Out-String).Trim()
        switch ($Name) {
            'powershell' { return $text -eq $Package.version }
            'python' {
                return $text -match (
                    "^Python $([regex]::Escape($Package.version))(?:\s|$)")
            }
            'node' {
                return $text -match (
                    "^v$([regex]::Escape($Package.version))(?:\s|$)")
            }
            'seven_zip' {
                return $text -match (
                    "7-Zip $([regex]::Escape($Package.version))(?:\s|$)")
            }
            'git' {
                return $text -match (
                    "^git version $([regex]::Escape($Package.version))" +
                    "(?:\.windows\.[0-9]+)?(?:\s|$)")
            }
        }
    } catch {
        return $false
    }
}

function Install-SetupTool([string]$Name, $Package, [int]$Progress) {
    $target = Join-Path $localTools $Name
    $staging = "$target.installing"
    $backup = "$target.previous"
    if (!(Test-Path -LiteralPath $target) -and
        (Test-Path -LiteralPath $backup)) {
        Move-Item -LiteralPath $backup -Destination $target
    }
    if (Test-InstalledTool $target $Name $Package) {
        Remove-OrdinaryDirectory $staging
        Remove-OrdinaryDirectory $backup
        Write-SetupEvent 'log' "$Name $($Package.version) is already ready."
        return Get-ToolExecutable $target $Package
    }
    if (Test-InstalledTool $backup $Name $Package) {
        Remove-OrdinaryDirectory $target
        Move-Item -LiteralPath $backup -Destination $target
        Remove-OrdinaryDirectory $staging
        Write-SetupEvent 'log' "$Name $($Package.version) was recovered."
        return Get-ToolExecutable $target $Package
    }

    Write-SetupEvent 'stage' "Installing portable $Name $($Package.version)..." $Progress
    $archive = Get-VerifiedDownload $Package
    Remove-OrdinaryDirectory $staging
    Remove-OrdinaryDirectory $backup
    New-Item -ItemType Directory -Path $staging | Out-Null
    $published = $false
    try {
        if ($Name -eq 'seven_zip') {
            $tar = (Get-Command tar.exe -CommandType Application -ErrorAction Stop |
                Select-Object -First 1).Source
            & $tar -xf $archive -C $staging
            if ($LASTEXITCODE) { throw 'Portable 7-Zip extraction failed' }
        } else {
            Expand-Archive -LiteralPath $archive -DestinationPath $staging -Force
        }
        $payload = if ($Package.archive_root) {
            Join-Path $staging $Package.archive_root
        } else {
            $staging
        }
        $executable = Get-ToolExecutable $payload $Package
        if (!(Test-Path -LiteralPath $executable -PathType Leaf)) {
            throw "$Name archive did not contain $($Package.executable)"
        }
        if ($Name -eq 'python') {
            $pathFiles = @(Get-ChildItem -LiteralPath $payload -Filter 'python*._pth' -File)
            if ($pathFiles.Count -ne 1) {
                throw 'Portable Python archive has an unexpected path configuration.'
            }
            $pathLines = @(Get-Content -LiteralPath $pathFiles[0].FullName)
            $configured = [System.Collections.Generic.List[string]]::new()
            $addedRoot = $false
            foreach ($line in $pathLines) {
                if ($line.Trim() -eq '#import site' -and !$addedRoot) {
                    $configured.Add('..\..')
                    $configured.Add('..\..\tools')
                    $configured.Add('import site')
                    $addedRoot = $true
                } else {
                    $configured.Add($line)
                }
            }
            if (!$addedRoot) {
                $configured.Add('..\..')
                $configured.Add('..\..\tools')
                $configured.Add('import site')
            }
            $configured | Set-Content -LiteralPath $pathFiles[0].FullName -Encoding ASCII
        }
        [ordered]@{
            schema = 3
            version = $Package.version
            sha256 = $Package.sha256
        } | ConvertTo-Json | Set-Content -LiteralPath (
            Join-Path $payload '.n3-setup-tool.json') -Encoding UTF8

        if (Test-Path -LiteralPath $target) {
            $item = Get-Item -LiteralPath $target -Force
            if (!$item.PSIsContainer -or
                ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw "Refusing to replace non-directory or linked tool path: $target"
            }
            Move-Item -LiteralPath $target -Destination $backup
        }
        Move-Item -LiteralPath $payload -Destination $target
        $published = $true
        Remove-OrdinaryDirectory $staging
        if (!(Test-InstalledTool $target $Name $Package)) {
            throw "Installed $Name failed its version check"
        }
        Remove-OrdinaryDirectory $backup
    } catch {
        Remove-OrdinaryDirectory $staging
        if ($published) { Remove-OrdinaryDirectory $target }
        if (Test-Path -LiteralPath $backup) {
            Move-Item -LiteralPath $backup -Destination $target
        }
        throw
    }
    return Get-ToolExecutable $target $Package
}

function Invoke-Logged(
    [string]$Executable,
    [string[]]$Arguments,
    [string]$Label,
    [int]$ProgressStart = -1,
    [int]$ProgressEnd = -1
) {
    Write-SetupEvent 'log' "$Label"
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Executable @Arguments 2>&1 | ForEach-Object {
            $text = "$_"
            Write-SetupEvent 'log' $text
            if ($ProgressStart -ge 0 -and
                $text -match '^Extracted ([0-9]+)/([0-9]+) files') {
                $value = $ProgressStart + [int]((
                    $ProgressEnd - $ProgressStart) *
                    ([double]$Matches[1] / [double]$Matches[2]))
                Write-SetupEvent 'progress' $text $value
            }
        }
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode) {
        throw "$Label failed with exit code $exitCode"
    }
}

function Test-SupportedGame([string]$GameRoot, [string]$ExpectedHash) {
    $xex = Join-Path $GameRoot 'default.xex'
    if (!(Test-Path -LiteralPath $xex -PathType Leaf)) { return $false }
    return (Get-Sha256 $xex) -eq $ExpectedHash
}

function Import-GameData(
    [string]$Node,
    [string]$IsoPath,
    [string]$ExpectedHash
) {
    $private = Join-Path $root 'private'
    $game = Join-Path $private 'game'
    if (Test-SupportedGame $game $ExpectedHash) {
        Write-SetupEvent 'log' 'Existing verified private\game data will be reused.'
        return
    }
    if (Test-Path -LiteralPath $game) {
        throw 'private\game exists but does not contain the supported default.xex; move it aside before setup.'
    }
    if (!$IsoPath) {
        throw 'Select the supported USA/Europe ISO before starting setup.'
    }
    $iso = [IO.Path]::GetFullPath($IsoPath)
    if (!(Test-Path -LiteralPath $iso -PathType Leaf)) {
        throw "ISO file not found: $iso"
    }
    $isoItem = Get-Item -LiteralPath $iso -Force
    if ($isoItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "ISO must not be a linked or reparse file: $iso"
    }

    Write-SetupEvent 'stage' 'Verifying the supported game ISO...' 30
    Invoke-Logged $Node @(
        (Join-Path $PSScriptRoot 'disc.mjs'),
        'verify',
        $iso,
        'default.xex',
        $ExpectedHash
    ) 'Game ISO verification'

    Initialize-OrdinaryDirectory $private
    $staging = Join-Path $private 'game.installing'
    $manifestStaging = Join-Path $private 'disc-manifest.installing.json'
    $manifest = Join-Path $private 'disc-manifest.json'
    $marker = Join-Path $private '.n3-source-setup-game.json'
    if ((Test-Path -LiteralPath $manifest) -and
        !(Test-Path -LiteralPath $marker)) {
        throw "Disc manifest already exists without installed game data: $manifest"
    }
    if (Test-Path -LiteralPath $marker -PathType Leaf) {
        $state = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
        if ($state.schema -ne 1 -or $state.staging -ne $staging) {
            throw "Unrecognized interrupted-import marker: $marker"
        }
        Remove-OrdinaryDirectory $staging
        Remove-OrdinaryFile $manifestStaging
        Remove-OrdinaryFile $marker
    } elseif (Test-Path -LiteralPath $staging) {
        throw "Unowned setup staging directory exists: $staging"
    }

    [ordered]@{ schema = 1; staging = $staging } |
        ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8
    try {
        Write-SetupEvent 'stage' 'Importing and hashing game data...' 35
        Invoke-Logged $Node @(
            (Join-Path $PSScriptRoot 'disc.mjs'),
            'extract',
            $iso,
            $staging,
            $manifestStaging
        ) 'Game ISO import' 35 55
        if (!(Test-SupportedGame $staging $ExpectedHash)) {
            throw 'Imported game data did not contain the supported default.xex.'
        }
        Move-Item -LiteralPath $staging -Destination $game
        if (Test-Path -LiteralPath $manifest) {
            throw "Disc manifest already exists: $manifest"
        }
        Move-Item -LiteralPath $manifestStaging -Destination $manifest
        Remove-OrdinaryFile $marker
    } catch {
        Remove-OrdinaryDirectory $staging
        Remove-OrdinaryFile $manifestStaging
        Remove-OrdinaryFile $marker
        throw
    }
}

try {
    Initialize-OrdinaryDirectory $localTools
    Initialize-OrdinaryDirectory $downloads
    $eventParent = Split-Path $EventFile -Parent
    if ($eventParent) { Initialize-OrdinaryDirectory $eventParent }
    $eventWriter = [IO.StreamWriter]::new(
        $EventFile, $false, [Text.UTF8Encoding]::new($false))
    $eventWriter.AutoFlush = $true

    if (!(Test-Path -LiteralPath $RequestFile -PathType Leaf)) {
        throw "Setup request not found: $RequestFile"
    }
    $request = Get-Content -LiteralPath $RequestFile -Raw | ConvertFrom-Json
    if ($request.schema -ne 1 -or
        $request.configuration -notin @('Debug', 'Release', 'RelWithDebInfo') -or
        $request.jobs -lt 1 -or $request.jobs -gt 64) {
        throw 'Setup request is invalid.'
    }
    if (!$request.toolsOnly -and !$request.acceptVisualStudioLicense) {
        throw 'Microsoft Visual Studio license consent is required for the portable compiler tools.'
    }

    $lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
    Write-SetupEvent 'stage' 'Preparing portable setup tools...' 2
    $powerShell = Install-SetupTool 'powershell' $lock.setup_tools.powershell 5
    $python = Install-SetupTool 'python' $lock.setup_tools.python 11
    $node = Install-SetupTool 'node' $lock.setup_tools.node 17
    $sevenZip = Install-SetupTool 'seven_zip' $lock.setup_tools.seven_zip 23
    $git = Install-SetupTool 'git' $lock.setup_tools.git 27
    $env:PATH = "$(Split-Path $git -Parent);$env:PATH"

    if ($request.toolsOnly) {
        Write-SetupEvent 'complete' 'Portable setup tools are ready.' 100
        exit 0
    }

    $gameBuild = Get-Content (
        Join-Path $root 'docs\game-build.json') -Raw | ConvertFrom-Json
    Import-GameData $node $request.isoPath $gameBuild.xexSha256

    Write-SetupEvent 'stage' 'Downloading and validating the pinned compiler toolchain...' 58
    Invoke-Logged $powerShell @(
        '-NoProfile',
        '-File', (Join-Path $PSScriptRoot 'bootstrap.ps1'),
        '-AcceptVisualStudioLicense',
        '-SevenZip', $sevenZip,
        '-Python', $python
    ) 'Pinned toolchain bootstrap'

    Write-SetupEvent 'stage' 'Compiling N3 Recompiled and running native tests...' 72
    Invoke-Logged $powerShell @(
        '-NoProfile',
        '-File', (Join-Path $PSScriptRoot 'build.ps1'),
        '-Configuration', $request.configuration,
        '-Jobs', "$($request.jobs)",
        '-Python', $python
    ) 'Native build and regression tests'

    if ($request.createShortcut) {
        Write-SetupEvent 'stage' 'Creating the desktop shortcut...' 96
        Invoke-Logged $powerShell @(
            '-NoProfile',
            '-File', (Join-Path $PSScriptRoot 'install-shortcut.ps1'),
            '-PowerShell', $powerShell
        ) 'Desktop shortcut installation'
    }

    $preset = 'win-amd64-' + $request.configuration.ToLowerInvariant()
    $launcher = Join-Path $root "out\build\$preset\n3_launcher.exe"
    if (!(Test-Path -LiteralPath $launcher -PathType Leaf)) {
        throw "Build completed without the native launcher: $launcher"
    }
    Write-SetupEvent 'complete' 'Setup completed successfully.' 100 @{
        launcher = $launcher
        powershell = $powerShell
    }
    if ($request.launchWhenComplete) {
        Start-Process -FilePath $powerShell -ArgumentList @(
            '-NoProfile',
            '-File',
            "`"$(Join-Path $PSScriptRoot 'launch.ps1')`"",
            '-Configuration',
            $request.configuration,
            '-Settings'
        ) | Out-Null
    }
} catch {
    if ($eventWriter) {
        Write-SetupEvent 'error' $_.Exception.Message
    } else {
        Write-Error $_
    }
    exit 1
} finally {
    if ($eventWriter) { $eventWriter.Dispose() }
}
