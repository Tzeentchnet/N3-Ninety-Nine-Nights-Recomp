[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$setup = Join-Path $PSScriptRoot 'setup.ps1'
$worker = Join-Path $PSScriptRoot 'setup-worker.ps1'
$shortcut = Join-Path $PSScriptRoot 'install-shortcut.ps1'
$pwsh = (Get-Command pwsh -CommandType Application -ErrorAction Stop |
    Select-Object -First 1).Source
$windowsPowerShell = Join-Path $env:SystemRoot (
    'System32\WindowsPowerShell\v1.0\powershell.exe')
$checks = 0

function Assert-True([bool]$Condition, [string]$Message) {
    if (!$Condition) { throw $Message }
    $script:checks++
}

function Invoke-Plan([string]$HostExecutable, [string[]]$Arguments) {
    $output = & $HostExecutable -NoProfile -ExecutionPolicy Bypass `
        -File $setup -DryRun @Arguments 2>&1
    if ($LASTEXITCODE) {
        throw "Setup plan failed ($LASTEXITCODE): $($output | Out-String)"
    }
    return ($output | Out-String) | ConvertFrom-Json
}

foreach ($hostExecutable in @($windowsPowerShell, $pwsh)) {
    $plan = Invoke-Plan $hostExecutable @('-NoLaunch', '-NoShortcut')
    Assert-True ($plan.schema -eq 1) 'Unexpected setup plan schema'
    Assert-True ($plan.repository -eq $root) 'Setup resolved the wrong repository'
    Assert-True ($plan.gameDirectory -eq (Join-Path $root 'private\game')) `
        'Setup resolved the wrong game directory'
    Assert-True ($plan.isoRequired -eq ($plan.gameState -ne 'verified')) `
        'ISO requirement does not match the detected game state'
    Assert-True ($plan.stages[0] -eq 'portable-setup-tools') `
        'Portable setup tools are not the first stage'
    Assert-True ($plan.stages -contains 'pinned-compiler-toolchain') `
        'Setup plan omitted the compiler toolchain'
    Assert-True ($plan.stages -contains 'build-and-test') `
        'Setup plan omitted the build'
    Assert-True ($plan.stages -notcontains 'desktop-shortcut') `
        'NoShortcut plan retained shortcut installation'
    Assert-True ($plan.stages -notcontains 'open-settings-launcher') `
        'NoLaunch plan retained launcher startup'
    $tools = @{}
    foreach ($tool in $plan.tools) { $tools[$tool.name] = $tool }
    Assert-True ($tools.powershell.version -eq '7.7.0') `
        'PowerShell setup pin changed'
    Assert-True ($tools.python.version -eq '3.14.10') `
        'Python setup pin changed'
    Assert-True ($tools.node.version -eq '22.23.5') `
        'Node setup pin changed'
    Assert-True ($tools.seven_zip.version -eq '25.01') `
        '7-Zip setup pin changed'
    Assert-True ($tools.git.version -eq '2.56.1') `
        'Git setup pin changed'
}

$toolsOnly = Invoke-Plan $windowsPowerShell @('-InstallToolsOnly')
Assert-True ([bool]$toolsOnly.request.toolsOnly) `
    'Tools-only setup mode was not retained'
Assert-True (($toolsOnly.stages -join ',') -eq 'portable-setup-tools') `
    'Tools-only setup planned unrelated work'

$failure = & $pwsh -NoProfile -File $setup -Headless -NoLaunch 2>&1
Assert-True ($LASTEXITCODE -ne 0) `
    'Headless source build accepted missing license consent'
Assert-True (($failure | Out-String) -match
    [regex]::Escape('-AcceptVisualStudioLicense is required')) `
    'Headless source build reported the wrong license error'

$shortcutPlan = & $pwsh -NoProfile -File $shortcut `
    -PowerShell $pwsh -DryRun | ConvertFrom-Json
Assert-True ($shortcutPlan.target -eq $pwsh) `
    'Shortcut did not retain the selected portable PowerShell'
Assert-True ($shortcutPlan.arguments -match '(?:^|\s)-Settings(?:\s|$)') `
    'Shortcut does not open the settings launcher'

$temporary = Join-Path $root (
    '.tools\setup-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $request = Join-Path $temporary 'request.json'
    $events = Join-Path $temporary 'events.jsonl'
    '{"schema":999}' | Set-Content -LiteralPath $request -Encoding UTF8
    & $windowsPowerShell -NoProfile -ExecutionPolicy Bypass -File $worker `
        -RequestFile $request -EventFile $events 2>&1 | Out-Null
    Assert-True ($LASTEXITCODE -ne 0) `
        'Setup worker accepted an invalid request'
    $lastEvent = Get-Content -LiteralPath $events | Select-Object -Last 1 |
        ConvertFrom-Json
    Assert-True ($lastEvent.type -eq 'error') `
        'Invalid setup request did not produce an error event'
    Assert-True ($lastEvent.message -match 'request is invalid') `
        'Invalid setup request produced the wrong error'
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}

Write-Output "Source setup tests passed: $checks checks"
