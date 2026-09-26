param(
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string[]]$CaseId = @(),
    [ValidateSet('paired', 'repair-paired', 'baseline', 'baseline_repair', 'pipeline')]
    [string]$Condition = 'paired',
    [ValidateRange(1, 20)][int]$Replicates = 1,
    [switch]$Live,
    [ValidateRange(1, 240)][int]$MaxProviderCalls,
    [ValidateRange(1, 7200)][int]$MaxWallSeconds
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$env:PYTHONPATH = 'src'

$arguments = @(
    '-m', 'mathresearch', 'research', 'evaluate',
    '--cases', 'diagnostics/ten-styles-20260923',
    '--out-dir', $OutDir,
    '--model', 'gpt-5.6-terra',
    '--effort', 'medium',
    '--condition', $Condition,
    '--replicates', "$Replicates",
    '--json'
)
foreach ($id in $CaseId) {
    $arguments += @('--case-id', $id)
}
if ($Live) {
    if (-not $PSBoundParameters.ContainsKey('MaxProviderCalls') -or
        -not $PSBoundParameters.ContainsKey('MaxWallSeconds')) {
        throw 'Live runs require explicit -MaxProviderCalls and -MaxWallSeconds.'
    }
    $arguments += @('--live', '--max-provider-calls', "$MaxProviderCalls",
                    '--max-wall-seconds', "$MaxWallSeconds")
}

python @arguments
exit $LASTEXITCODE
