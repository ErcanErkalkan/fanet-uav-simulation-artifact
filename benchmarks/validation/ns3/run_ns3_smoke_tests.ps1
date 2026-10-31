param(
    [string]$Distribution = "Ubuntu-24.04"
)

$ErrorActionPreference = "Stop"
$repositoryDirectory = $PSScriptRoot
$originalLocation = Get-Location

try {
    Set-Location C:\
    $linuxHome = (& wsl.exe -d $Distribution -- bash -lc 'printf "%s" "$HOME"').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $linuxHome.StartsWith("/home/")) {
        throw "Could not resolve the WSL user's home directory."
    }

    $wslShareRoot = "\\wsl.localhost\$Distribution"
    $linuxHomeShare = $wslShareRoot + ($linuxHome -replace "/", "\")
    $ns3Share = Join-Path $linuxHomeShare "ns3-work\ns-3.49"
    $scratchShare = Join-Path $ns3Share "scratch"
    if (-not (Test-Path (Join-Path $ns3Share "ns3"))) {
        throw "ns-3.49 was not found in the WSL Linux home directory."
    }

    Copy-Item (Join-Path $repositoryDirectory "ns3_reference_smoke.cc") `
        (Join-Path $scratchShare "ns3_reference_smoke.cc") -Force
    Copy-Item (Join-Path $repositoryDirectory "run_ns3_smoke_tests.sh") `
        (Join-Path $scratchShare "run_ns3_smoke_tests.sh") -Force

    $linuxCommand = 'sed -i ''s/\r$//'' "$HOME/ns3-work/ns-3.49/scratch/run_ns3_smoke_tests.sh" && bash "$HOME/ns3-work/ns-3.49/scratch/run_ns3_smoke_tests.sh"'
    $runOutput = & wsl.exe -d $Distribution -- bash -lc $linuxCommand 2>&1
    $runExitCode = $LASTEXITCODE

    foreach ($name in @("ns3_smoke_test_results.csv", "ns3_smoke_test.log")) {
        $source = Join-Path $scratchShare $name
        if (Test-Path $source) {
            Copy-Item $source (Join-Path $repositoryDirectory $name) -Force
        }
    }

    $runOutput | ForEach-Object { Write-Output $_ }
    if ($runExitCode -ne 0) {
        throw "ns-3 smoke test runner exited with code $runExitCode. Inspect ns3_smoke_test.log."
    }
}
finally {
    Set-Location $originalLocation
}
