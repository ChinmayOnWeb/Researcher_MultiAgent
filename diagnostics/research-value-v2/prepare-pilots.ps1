$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'src'

python -m mathresearch research evaluate `
  --cases evals/research-value-v2/development `
  --out-dir diagnostics/research-value-v2/development-dry-run-v2 `
  --condition architecture --replicates 1 --dry-run-manifest `
  --model gpt-5.6-terra --effort medium --json
if ($LASTEXITCODE -ne 0) { throw 'Development dry-run manifest failed.' }

python -m mathresearch research evaluate `
  --cases evals/research-value-v2/held-out `
  --out-dir diagnostics/research-value-v2/held-out-dry-run-v2 `
  --condition architecture --replicates 3 --dry-run-manifest `
  --model gpt-5.6-terra --effort medium --json
if ($LASTEXITCODE -ne 0) { throw 'Held-out dry-run manifest failed.' }
