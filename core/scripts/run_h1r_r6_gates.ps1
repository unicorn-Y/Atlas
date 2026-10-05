param(
    [string]$HermesRoot = 'D:\hermes-agent-h1r-closeout',
    [string]$OutputDirectory = '',
    [string]$BasetempRoot = '',
    [ValidateSet('unit', 'unit-integration', 'desktop', 'frontend')]
    [string[]]$Gates = @('unit', 'unit-integration', 'desktop', 'frontend'),
    [switch]$ContinueOnFailure
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$coreRoot = Join-Path $repoRoot 'core'
$python = Join-Path $coreRoot '.venv\Scripts\python.exe'
$outputRoot = if ($OutputDirectory) { $OutputDirectory } else { Join-Path $repoRoot 'artifacts\h1r-r6' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$basetempRoot = if ($BasetempRoot) {
    $BasetempRoot
} else {
    Join-Path $env:TEMP "atlas-h1r-r6-$stamp"
}

if (-not (Test-Path -LiteralPath $python)) { throw "Python venv not found: $python" }
if (-not (Test-Path -LiteralPath $HermesRoot)) { throw "Pinned Hermes checkout not found: $HermesRoot" }
if ($env:ATLAS_LIVE -eq '1') { throw 'Unset ATLAS_LIVE before running non-live R6 gates.' }
$env:PYTHONPATH = "$HermesRoot;$coreRoot"
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
New-Item -ItemType Directory -Path $basetempRoot -Force | Out-Null

$results = [System.Collections.Generic.List[object]]::new()
$summaryPath = Join-Path $outputRoot 'summary.json'
if (Test-Path -LiteralPath $summaryPath) {
    foreach ($existingResult in @(Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json)) {
        $results.Add($existingResult)
    }
}

function Save-Summary {
    $temporarySummary = "$summaryPath.tmp"
    $results | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporarySummary -Encoding utf8
    Move-Item -LiteralPath $temporarySummary -Destination $summaryPath -Force
}

function Replace-Result {
    param([string]$Name)
    for ($index = $results.Count - 1; $index -ge 0; $index--) {
        if ($results[$index].name -eq $Name) { $results.RemoveAt($index) }
    }
}

function Read-JunitCounts {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        [xml]$document = Get-Content -LiteralPath $Path -Raw
        $root = $document.DocumentElement
        if ($root.HasAttribute('tests')) {
            return [pscustomobject]@{
                tests = [int]$root.GetAttribute('tests')
                failures = [int]$root.GetAttribute('failures')
                errors = [int]$root.GetAttribute('errors')
                skipped = [int]$root.GetAttribute('skipped')
            }
        }
        $suites = @($root.SelectNodes('.//testsuite'))
        return [pscustomobject]@{
            tests = [int](($suites | Measure-Object -Property tests -Sum).Sum)
            failures = [int](($suites | Measure-Object -Property failures -Sum).Sum)
            errors = [int](($suites | Measure-Object -Property errors -Sum).Sum)
            skipped = [int](($suites | Measure-Object -Property skipped -Sum).Sum)
        }
    } catch {
        return $null
    }
}

function Invoke-PytestGate {
    param(
        [string]$Name,
        [string]$MarkerExpression,
        [int]$WallBudgetSeconds,
        [bool]$UseXdist
    )
    $log = Join-Path $outputRoot "$Name.log"
    $junit = Join-Path $outputRoot "$Name.xml"
    $base = Join-Path $basetempRoot $Name
    New-Item -ItemType Directory -Path $base -Force | Out-Null
    $pytestArgs = @(
        '-m', 'pytest', 'tests', '-m', $MarkerExpression,
        '--timeout=300', '--show-capture=no', '--tb=short', '-q', '--durations=30',
        "--junitxml=$junit", '--basetemp', $base
    )
    if ($UseXdist) { $pytestArgs += @('-n', 'auto', '--dist', 'loadscope') }
    Push-Location $coreRoot
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        & $python @pytestArgs 2>&1 | Out-File -LiteralPath $log -Encoding utf8
        $code = $LASTEXITCODE
    } finally {
        $watch.Stop()
        Pop-Location
    }
    $elapsed = [Math]::Round($watch.Elapsed.TotalSeconds, 3)
    $junitCounts = Read-JunitCounts -Path $junit
    Replace-Result -Name $Name
    $results.Add([pscustomobject]@{
        name = $Name
        markers = $MarkerExpression
        elapsed_seconds = $elapsed
        exit_code = $code
        wall_budget_seconds = $WallBudgetSeconds
        within_budget = ($WallBudgetSeconds -le 0 -or $elapsed -le $WallBudgetSeconds)
        junit_counts = $junitCounts
        log = $log
        junit_xml = $junit
        basetemp = $base
    })
    Save-Summary
    $countsText = if ($junitCounts) {
        "tests=$($junitCounts.tests) failures=$($junitCounts.failures) errors=$($junitCounts.errors) skipped=$($junitCounts.skipped)"
    } else { 'junit-counts=unavailable' }
    Write-Output "R6 ${Name}: exit=$code elapsed=${elapsed}s $countsText"
    if (($code -ne 0 -or ($WallBudgetSeconds -gt 0 -and $elapsed -gt $WallBudgetSeconds)) -and -not $ContinueOnFailure) {
        Save-Summary
        exit 1
    }
}

if ($Gates -contains 'unit') {
    Invoke-PytestGate -Name 'unit' -MarkerExpression 'unit' -WallBudgetSeconds 180 -UseXdist $true
}
if ($Gates -contains 'unit-integration') {
    Invoke-PytestGate -Name 'unit-integration' -MarkerExpression 'unit or integration' -WallBudgetSeconds 600 -UseXdist $true
}
if ($Gates -contains 'desktop') {
    Invoke-PytestGate -Name 'desktop' -MarkerExpression 'desktop' -WallBudgetSeconds 0 -UseXdist $false
}

if ($Gates -contains 'frontend') {
    $frontendLog = Join-Path $outputRoot 'frontend.log'
    Push-Location (Join-Path $repoRoot 'frontend')
    $frontendWatch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        & npm.cmd test -- --reporter=dot 2>&1 | Out-File -LiteralPath $frontendLog -Encoding utf8
        $frontendCode = $LASTEXITCODE
    } finally {
        $frontendWatch.Stop()
        Pop-Location
    }
    $frontendElapsed = [Math]::Round($frontendWatch.Elapsed.TotalSeconds, 3)
    Replace-Result -Name 'frontend'
    $results.Add([pscustomobject]@{
        name = 'frontend'
        elapsed_seconds = $frontendElapsed
        exit_code = $frontendCode
        log = $frontendLog
    })
    Save-Summary
    Write-Output "R6 frontend: exit=$frontendCode elapsed=${frontendElapsed}s"
    if ($frontendCode -ne 0 -and -not $ContinueOnFailure) { exit 1 }
}

Save-Summary
Write-Output "R6 summary: $summaryPath"
$failed = @($results | Where-Object {
    $_.exit_code -ne 0 -or (
        ($_.PSObject.Properties.Name -contains 'within_budget') -and -not $_.within_budget
    )
})
if ($failed.Count -gt 0) { exit 1 }
exit 0
