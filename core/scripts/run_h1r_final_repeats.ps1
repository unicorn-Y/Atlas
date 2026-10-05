param(
    [string]$HermesRoot = 'D:\hermes-agent-h1r-closeout',
    [string]$OutputDirectory = '',
    [string]$BasetempRoot = '',
    [ValidateSet('startup', 'concurrency')]
    [string[]]$Gates = @('startup', 'concurrency')
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$coreRoot = Join-Path $repoRoot 'core'
$python = Join-Path $coreRoot '.venv\Scripts\python.exe'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outputRoot = if ($OutputDirectory) { $OutputDirectory } else {
    Join-Path $repoRoot "artifacts\h1r-final-repeats-$stamp"
}
$basetempRoot = if ($BasetempRoot) { $BasetempRoot } else {
    Join-Path $env:TEMP "atlas-h1r-final-repeats-$stamp"
}

if (-not (Test-Path -LiteralPath $python)) { throw "Python venv not found: $python" }
if (-not (Test-Path -LiteralPath $HermesRoot)) {
    throw "Pinned Hermes checkout not found: $HermesRoot"
}
if ($env:ATLAS_LIVE -eq '1') { throw 'Unset ATLAS_LIVE before running these non-live gates.' }

$HermesRoot = (Resolve-Path -LiteralPath $HermesRoot).Path
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
New-Item -ItemType Directory -Path $basetempRoot -Force | Out-Null
$outputRoot = (Resolve-Path -LiteralPath $outputRoot).Path
$basetempRoot = (Resolve-Path -LiteralPath $basetempRoot).Path
$env:PYTHONPATH = "$HermesRoot;$coreRoot"

$summaryPath = Join-Path $outputRoot 'summary.json'
$results = [System.Collections.Generic.List[object]]::new()
$startedAt = (Get-Date).ToUniversalTime().ToString('o')
$previousRepeats = $env:ATLAS_H3_ISOLATION_REPEATS

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

function Save-Summary {
    $temporarySummary = "$summaryPath.tmp"
    [pscustomobject]@{
        schema_version = 1
        started_at_utc = $startedAt
        finished_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        repo_root = $repoRoot
        python = $python
        hermes_root = $HermesRoot
        output_directory = $outputRoot
        basetemp_root = $basetempRoot
        runs = @($results.ToArray())
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporarySummary -Encoding utf8
    Move-Item -LiteralPath $temporarySummary -Destination $summaryPath -Force
}

try {
    foreach ($gate in $Gates) {
        if ($gate -eq 'startup') {
            $repeatCount = 3
            $node = 'tests/test_startup_time.py::test_cold_start_median_within_h8_budget'
            $marker = 'integration'
        } else {
            $repeatCount = 20
            $node = 'tests/test_concurrency_isolation.py::test_eight_concurrent_sessions_isolated_across_repeated_waves'
            $marker = 'unit'
            $env:ATLAS_H3_ISOLATION_REPEATS = '1'
        }

        for ($index = 1; $index -le $repeatCount; $index++) {
            $runName = '{0}-{1:D2}' -f $gate, $index
            $log = Join-Path $outputRoot "$runName.log"
            $junit = Join-Path $outputRoot "$runName.xml"
            $base = Join-Path $basetempRoot $runName
            New-Item -ItemType Directory -Path $base -Force | Out-Null
            $pytestArgs = @(
                '-m', 'pytest', $node, '-m', $marker,
                '--timeout=300', '--show-capture=no', '--tb=short', '-q',
                "--junitxml=$junit", '--basetemp', $base
            )

            $code = 127
            Push-Location $coreRoot
            $watch = [System.Diagnostics.Stopwatch]::StartNew()
            try {
                & $python @pytestArgs 2>&1 | Out-File -LiteralPath $log -Encoding utf8
                $code = $LASTEXITCODE
            } catch {
                $_ | Out-String | Set-Content -LiteralPath $log -Encoding utf8
            } finally {
                $watch.Stop()
                Pop-Location
            }

            $elapsed = [Math]::Round($watch.Elapsed.TotalSeconds, 3)
            $junitCounts = Read-JunitCounts -Path $junit
            $failureReason = $null
            if ($code -ne 0) {
                $failureReason = "pytest exited with code $code"
            } elseif (-not $junitCounts) {
                $failureReason = 'JUnit report missing or unreadable'
            } elseif ($junitCounts.tests -ne 1) {
                $failureReason = "expected 1 selected test, found $($junitCounts.tests)"
            } elseif ($junitCounts.failures -ne 0 -or $junitCounts.errors -ne 0) {
                $failureReason = "JUnit reports failures=$($junitCounts.failures), errors=$($junitCounts.errors)"
            } elseif ($junitCounts.skipped -ne 0) {
                $failureReason = "expected 0 skipped tests, found $($junitCounts.skipped)"
            }
            $results.Add([pscustomobject]@{
                gate = $gate
                run = $index
                run_count = $repeatCount
                node = $node
                marker = $marker
                repeat_environment = if ($gate -eq 'concurrency') {
                    'ATLAS_H3_ISOLATION_REPEATS=1'
                } else { $null }
                elapsed_seconds = $elapsed
                exit_code = $code
                junit_counts = $junitCounts
                accepted = ($null -eq $failureReason)
                failure_reason = $failureReason
                log = $log
                junit_xml = $junit
                basetemp = $base
            })
            Save-Summary
            $countsText = if ($junitCounts) {
                "tests=$($junitCounts.tests) failures=$($junitCounts.failures) errors=$($junitCounts.errors) skipped=$($junitCounts.skipped)"
            } else { 'junit-counts=unavailable' }
            Write-Output "Final repeat ${runName}: exit=$code elapsed=${elapsed}s $countsText"

            if ($null -ne $failureReason) {
                Write-Output "Final repeat rejected: $failureReason"
                Write-Output "Final repeat stopped; summary: $summaryPath"
                exit 1
            }
        }
    }
} finally {
    $env:ATLAS_H3_ISOLATION_REPEATS = $previousRepeats
}

Save-Summary
Write-Output "Final repeat summary: $summaryPath"
exit 0
