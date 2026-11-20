[CmdletBinding()]
param(
    [string]$Name = 'N3 Recompiled',
    [string]$PowerShell,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if ($Name.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0 -or !$Name.Trim()) {
    throw 'Shortcut name must be a valid file name.'
}
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
if (!$desktop -or !(Test-Path -LiteralPath $desktop -PathType Container)) { throw 'Desktop folder not found.' }
$hostExecutable = if ($PowerShell) {
    $resolved = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($PowerShell)
    if (!(Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "PowerShell executable not found: $resolved"
    }
    $resolved
} else {
    (Get-Command pwsh -CommandType Application -ErrorAction Stop |
        Select-Object -First 1).Source
}
$shortcutPath = Join-Path $desktop "$Name.lnk"
$arguments = '-NoLogo -NoProfile -WindowStyle Hidden -File "' +
    (Join-Path $PSScriptRoot 'launch.ps1') + '" -Settings'
if ($DryRun) {
    [ordered]@{
        shortcut = $shortcutPath
        target = $hostExecutable
        arguments = $arguments
        workingDirectory = $root
    } | ConvertTo-Json
    return
}
$shell = New-Object -ComObject WScript.Shell
try {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    try {
        $shortcut.TargetPath = $hostExecutable
        $shortcut.Arguments = $arguments
        $shortcut.WorkingDirectory = $root
        $shortcut.Description = 'Open settings and play the current N3 Recompiled build'
        $shortcut.IconLocation = (Join-Path $root 'resources/n3.ico') + ',0'
        $shortcut.Save()
    } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shortcut) }
} finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell) }
Write-Output $shortcutPath
