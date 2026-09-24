$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$env:PYTHONPATH = 'src'

$cases = @(
    'bijection-vandermonde',
    'number-theory-mod24',
    'extremal-noncut-vertices',
    'linear-algebra-rank-one',
    'probability-overlap-hh',
    'calculus-log-integral',
    'geometry-median-centroid',
    'counterexample-fixed-point',
    'algorithm-euclidean-gcd'
)

foreach ($caseId in $cases) {
    $outDir = "runs/ten-styles-live-approved-20260923-$caseId"
    Write-Output "START $caseId"
    python -m mathresearch research evaluate `
        --cases diagnostics/ten-styles-20260923 `
        --out-dir $outDir `
        --case-id $caseId `
        --model gpt-5.6-terra `
        --effort medium `
        --replicates 1 `
        --live `
        --max-provider-calls 9 `
        --max-wall-seconds 900 `
        --json
    Write-Output "END $caseId exit=$LASTEXITCODE"
}
