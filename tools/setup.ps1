[CmdletBinding()]
param(
    [string]$IsoPath,
    [ValidateSet('Debug','Release','RelWithDebInfo')]
    [string]$Configuration = 'RelWithDebInfo',
    [ValidateRange(1,64)]
    [int]$Jobs = [Math]::Min([Environment]::ProcessorCount, 8),
    [switch]$AcceptVisualStudioLicense,
    [switch]$NoShortcut,
    [switch]$NoLaunch,
    [switch]$InstallToolsOnly,
    [switch]$Headless,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$localTools = Join-Path $root '.tools'
$stateDirectory = Join-Path $localTools 'setup-state'
$requestFile = Join-Path $stateDirectory 'request.json'
$eventFile = Join-Path $stateDirectory 'last-setup.jsonl'
$workerScript = Join-Path $PSScriptRoot 'setup-worker.ps1'
$lock = Get-Content (
    Join-Path $PSScriptRoot 'toolchain.lock.json') -Raw | ConvertFrom-Json
$gameBuild = Get-Content (
    Join-Path $root 'docs\game-build.json') -Raw | ConvertFrom-Json
$gameRoot = Join-Path $root 'private\game'

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

function Test-SupportedGame {
    $xex = Join-Path $gameRoot 'default.xex'
    if (!(Test-Path -LiteralPath $xex -PathType Leaf)) { return $false }
    return (Get-Sha256 $xex) -eq $gameBuild.xexSha256
}

function Get-GameState {
    if (Test-SupportedGame) { return 'verified' }
    if (Test-Path -LiteralPath $gameRoot) { return 'invalid' }
    return 'missing'
}

function New-SetupRequest {
    return [ordered]@{
        schema = 1
        isoPath = $(if ($IsoPath) {
            [IO.Path]::GetFullPath($IsoPath)
        } else {
            $null
        })
        configuration = $Configuration
        jobs = $Jobs
        acceptVisualStudioLicense = [bool]$AcceptVisualStudioLicense
        createShortcut = !$NoShortcut
        launchWhenComplete = !$NoLaunch
        toolsOnly = [bool]$InstallToolsOnly
    }
}

function Write-Request {
    if (Test-Path -LiteralPath $stateDirectory) {
        $item = Get-Item -LiteralPath $stateDirectory -Force
        if (!$item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Setup state must not use a file or linked path: $stateDirectory"
        }
    } else {
        New-Item -ItemType Directory -Path $stateDirectory | Out-Null
    }
    New-SetupRequest | ConvertTo-Json |
        Set-Content -LiteralPath $requestFile -Encoding UTF8
    if (Test-Path -LiteralPath $eventFile) {
        $item = Get-Item -LiteralPath $eventFile -Force
        if ($item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Refusing to replace non-file or linked setup log: $eventFile"
        }
        Remove-Item -LiteralPath $eventFile -Force
    }
}

function Read-Events {
    if (!(Test-Path -LiteralPath $eventFile -PathType Leaf)) { return @() }
    $lines = @(Get-Content -LiteralPath $eventFile | Where-Object { $_ })
    $events = [System.Collections.Generic.List[object]]::new()
    for ($index = 0; $index -lt $lines.Count; $index++) {
        try {
            $events.Add(($lines[$index] | ConvertFrom-Json))
        } catch {
            if ($index -eq $lines.Count - 1) { break }
            throw
        }
    }
    return @($events)
}

function Quote-ProcessArgument([string]$Value) {
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}

function Get-WorkerArguments {
    return @(
        '-NoLogo',
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', $workerScript,
        '-RequestFile', $requestFile,
        '-EventFile', $eventFile
    )
}

function Write-Plan {
    $state = Get-GameState
    $toolRecords = foreach ($property in $lock.setup_tools.PSObject.Properties) {
        [ordered]@{
            name = $property.Name
            version = $property.Value.version
            target = Join-Path $localTools $property.Name
        }
    }
    $stages = @('portable-setup-tools')
    if (!$InstallToolsOnly) {
        $stages += @('verify-game-data')
        if ($state -ne 'verified') { $stages += 'import-game-data' }
        $stages += @('pinned-compiler-toolchain', 'build-and-test')
        if (!$NoShortcut) { $stages += 'desktop-shortcut' }
        if (!$NoLaunch) { $stages += 'open-settings-launcher' }
    }
    [ordered]@{
        schema = 1
        repository = $root
        gameDirectory = $gameRoot
        gameState = $state
        isoRequired = $state -ne 'verified'
        request = New-SetupRequest
        tools = @($toolRecords)
        stages = $stages
    } | ConvertTo-Json -Depth 6
}

function Invoke-HeadlessSetup {
    if (!$InstallToolsOnly -and !$AcceptVisualStudioLicense) {
        throw '-AcceptVisualStudioLicense is required for a headless source build.'
    }
    Write-Request
    $hostExecutable = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    & $hostExecutable @(Get-WorkerArguments)
    $exitCode = $LASTEXITCODE
    foreach ($event in Read-Events) {
        if ($event.type -in @('stage', 'log', 'error', 'complete')) {
            Write-Output $event.message
        }
    }
    if ($exitCode) { throw "Source setup failed with exit code $exitCode." }
}

function Show-SetupWizard {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [Windows.Forms.Application]::EnableVisualStyles()

    $form = New-Object Windows.Forms.Form
    $form.Text = 'N3 Recompiled - Source Setup'
    $form.ClientSize = New-Object Drawing.Size(780, 650)
    $form.StartPosition = 'CenterScreen'
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.Font = New-Object Drawing.Font('Segoe UI', 9)

    $title = New-Object Windows.Forms.Label
    $title.Text = 'Build and install N3 Recompiled from this source checkout'
    $title.Font = New-Object Drawing.Font('Segoe UI Semibold', 14)
    $title.SetBounds(20, 18, 740, 30)
    $form.Controls.Add($title)

    $intro = New-Object Windows.Forms.Label
    $intro.Text = 'Setup downloads checksum-pinned portable tools into .tools, verifies and imports your owned disc, compiles the runtime, runs its tests, and opens the settings launcher. No administrator access is required.'
    $intro.SetBounds(22, 55, 735, 50)
    $form.Controls.Add($intro)

    $gameStatus = New-Object Windows.Forms.Label
    $state = Get-GameState
    if ($state -eq 'verified') {
        $gameStatus.Text = 'Verified private\game data is already present; selecting an ISO is optional.'
        $gameStatus.ForeColor = [Drawing.Color]::DarkGreen
    } elseif ($state -eq 'invalid') {
        $gameStatus.Text = 'private\game exists but is not the supported game. Move it aside before setup.'
        $gameStatus.ForeColor = [Drawing.Color]::DarkRed
    } else {
        $gameStatus.Text = 'Select your supported USA/Europe ISO. The source image remains read-only.'
    }
    $gameStatus.SetBounds(22, 112, 735, 24)
    $form.Controls.Add($gameStatus)

    $isoLabel = New-Object Windows.Forms.Label
    $isoLabel.Text = 'Game ISO:'
    $isoLabel.SetBounds(22, 143, 75, 24)
    $form.Controls.Add($isoLabel)

    $isoBox = New-Object Windows.Forms.TextBox
    $isoBox.Text = $IsoPath
    $isoBox.SetBounds(98, 140, 555, 25)
    $form.Controls.Add($isoBox)

    $browse = New-Object Windows.Forms.Button
    $browse.Text = 'Browse...'
    $browse.SetBounds(663, 139, 94, 27)
    $browse.Add_Click({
        $picker = New-Object Windows.Forms.OpenFileDialog
        $picker.Title = 'Select your supported N3 disc image'
        $picker.Filter = 'Xbox disc images (*.iso)|*.iso|All files (*.*)|*.*'
        $picker.CheckFileExists = $true
        if ($picker.ShowDialog($form) -eq [Windows.Forms.DialogResult]::OK) {
            $isoBox.Text = $picker.FileName
        }
        $picker.Dispose()
    })
    $form.Controls.Add($browse)

    $configurationLabel = New-Object Windows.Forms.Label
    $configurationLabel.Text = 'Build:'
    $configurationLabel.SetBounds(22, 184, 75, 24)
    $form.Controls.Add($configurationLabel)

    $configurationBox = New-Object Windows.Forms.ComboBox
    $configurationBox.DropDownStyle = 'DropDownList'
    [void]$configurationBox.Items.AddRange(
        @('RelWithDebInfo', 'Release', 'Debug'))
    $configurationBox.SelectedItem = $Configuration
    $configurationBox.SetBounds(98, 181, 170, 25)
    $form.Controls.Add($configurationBox)

    $jobsLabel = New-Object Windows.Forms.Label
    $jobsLabel.Text = 'Parallel jobs:'
    $jobsLabel.SetBounds(300, 184, 92, 24)
    $form.Controls.Add($jobsLabel)

    $jobsBox = New-Object Windows.Forms.NumericUpDown
    $jobsBox.Minimum = 1
    $jobsBox.Maximum = 64
    $jobsBox.Value = $Jobs
    $jobsBox.SetBounds(395, 181, 70, 25)
    $form.Controls.Add($jobsBox)

    $shortcutBox = New-Object Windows.Forms.CheckBox
    $shortcutBox.Text = 'Create or refresh the N3 Recompiled desktop shortcut'
    $shortcutBox.Checked = !$NoShortcut
    $shortcutBox.SetBounds(22, 222, 430, 25)
    $form.Controls.Add($shortcutBox)

    $licenseBox = New-Object Windows.Forms.CheckBox
    $licenseBox.Text = 'I accept the Microsoft Visual Studio 2022 development-tool license.'
    $licenseBox.Checked = [bool]$AcceptVisualStudioLicense
    $licenseBox.SetBounds(22, 255, 510, 25)
    $form.Controls.Add($licenseBox)

    $licenseLink = New-Object Windows.Forms.LinkLabel
    $licenseLink.Text = 'View license terms'
    $licenseLink.SetBounds(540, 257, 150, 23)
    $licenseLink.Add_LinkClicked({
        Start-Process 'https://visualstudio.microsoft.com/license-terms/'
    })
    $form.Controls.Add($licenseLink)

    $notice = New-Object Windows.Forms.Label
    $notice.Text = 'The first run downloads several gigabytes and imports about 5.8 GB of game data. Existing verified downloads and completed stages are reused.'
    $notice.SetBounds(22, 290, 735, 38)
    $form.Controls.Add($notice)

    $startButton = New-Object Windows.Forms.Button
    $startButton.Text = 'Install and build'
    $startButton.SetBounds(22, 337, 145, 32)
    $form.Controls.Add($startButton)

    $statusLabel = New-Object Windows.Forms.Label
    $statusLabel.Text = 'Ready.'
    $statusLabel.SetBounds(180, 344, 575, 24)
    $form.Controls.Add($statusLabel)

    $progress = New-Object Windows.Forms.ProgressBar
    $progress.Minimum = 0
    $progress.Maximum = 100
    $progress.SetBounds(22, 380, 735, 23)
    $form.Controls.Add($progress)

    $logBox = New-Object Windows.Forms.TextBox
    $logBox.Multiline = $true
    $logBox.ReadOnly = $true
    $logBox.ScrollBars = 'Vertical'
    $logBox.WordWrap = $false
    $logBox.SetBounds(22, 417, 735, 205)
    $form.Controls.Add($logBox)

    $timer = New-Object Windows.Forms.Timer
    $timer.Interval = 250
    $script:workerProcess = $null
    $script:eventIndex = 0
    $script:sawTerminalEvent = $false

    $appendLog = {
        param([string]$Text)
        $logBox.AppendText($Text + [Environment]::NewLine)
        $logBox.SelectionStart = $logBox.TextLength
        $logBox.ScrollToCaret()
    }

    $finishFailure = {
        param([string]$Message)
        $script:sawTerminalEvent = $true
        $timer.Stop()
        $statusLabel.Text = 'Setup failed.'
        $statusLabel.ForeColor = [Drawing.Color]::DarkRed
        $startButton.Enabled = $true
        & $appendLog "ERROR: $Message"
        [Windows.Forms.MessageBox]::Show(
            $form, $Message, 'N3 Recompiled setup failed',
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    }

    $timer.Add_Tick({
        try {
            $events = Read-Events
            while ($script:eventIndex -lt $events.Count) {
                $event = $events[$script:eventIndex++]
                if ($null -ne $event.progress) {
                    $progress.Value = [Math]::Max(
                        0, [Math]::Min(100, [int]$event.progress))
                }
                switch ($event.type) {
                    'stage' {
                        $statusLabel.Text = $event.message
                        & $appendLog $event.message
                    }
                    'progress' { $statusLabel.Text = $event.message }
                    'log' { & $appendLog $event.message }
                    'error' { & $finishFailure $event.message }
                    'complete' {
                        $script:sawTerminalEvent = $true
                        $timer.Stop()
                        $progress.Value = 100
                        $statusLabel.Text = $event.message
                        & $appendLog $event.message
                        [Windows.Forms.MessageBox]::Show(
                            $form,
                            'Setup is complete. The N3 settings launcher is opening.',
                            'N3 Recompiled setup',
                            [Windows.Forms.MessageBoxButtons]::OK,
                            [Windows.Forms.MessageBoxIcon]::Information
                        ) | Out-Null
                        $form.Close()
                    }
                }
            }
            if ($script:workerProcess -and
                $script:workerProcess.HasExited -and
                !$script:sawTerminalEvent) {
                & $finishFailure (
                    "The setup worker exited with code $($script:workerProcess.ExitCode) without a final status.")
            }
        } catch {
            & $finishFailure $_.Exception.Message
        }
    })

    $startButton.Add_Click({
        try {
            if (!$licenseBox.Checked) {
                throw 'Accept the Microsoft development-tool license before setup.'
            }
            $currentState = Get-GameState
            if ($currentState -eq 'invalid') {
                throw 'private\game is not the supported game. Move it aside before setup.'
            }
            if ($currentState -ne 'verified' -and
                !(Test-Path -LiteralPath $isoBox.Text -PathType Leaf)) {
                throw 'Select your supported N3 ISO before setup.'
            }

            $script:IsoPath = $isoBox.Text
            $script:Configuration = [string]$configurationBox.SelectedItem
            $script:Jobs = [int]$jobsBox.Value
            $script:AcceptVisualStudioLicense = $true
            $script:NoShortcut = !$shortcutBox.Checked
            $script:NoLaunch = $false
            $script:InstallToolsOnly = $false
            Write-Request

            $hostExecutable =
                [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
            $arguments = (Get-WorkerArguments | ForEach-Object {
                Quote-ProcessArgument "$_"
            }) -join ' '
            $info = New-Object Diagnostics.ProcessStartInfo
            $info.FileName = $hostExecutable
            $info.Arguments = $arguments
            $info.WorkingDirectory = $root
            $info.UseShellExecute = $false
            $info.CreateNoWindow = $true
            $script:workerProcess = [Diagnostics.Process]::Start($info)
            $script:eventIndex = 0
            $script:sawTerminalEvent = $false
            $progress.Value = 0
            $logBox.Clear()
            $statusLabel.Text = 'Starting setup...'
            $statusLabel.ForeColor = [Drawing.Color]::ControlText
            $startButton.Enabled = $false
            $timer.Start()
        } catch {
            [Windows.Forms.MessageBox]::Show(
                $form, $_.Exception.Message, 'Cannot start setup',
                [Windows.Forms.MessageBoxButtons]::OK,
                [Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
        }
    })

    $form.Add_FormClosing({
        param($sender, $eventArgs)
        if ($script:workerProcess -and
            !$script:workerProcess.HasExited -and
            !$script:sawTerminalEvent) {
            $eventArgs.Cancel = $true
            [Windows.Forms.MessageBox]::Show(
                $form,
                'Setup is still running. Minimize this window and wait for the current operation to finish.',
                'N3 Recompiled setup',
                [Windows.Forms.MessageBoxButtons]::OK,
                [Windows.Forms.MessageBoxIcon]::Information) | Out-Null
        }
    })

    [void]$form.ShowDialog()
    $timer.Dispose()
    if ($script:workerProcess) { $script:workerProcess.Dispose() }
    $form.Dispose()
}

if ($DryRun) {
    Write-Plan
} elseif ($Headless -or $InstallToolsOnly) {
    Invoke-HeadlessSetup
} else {
    Show-SetupWizard
}
