# Move non-source artifacts into backups/ so the repo can be committed cleanly
$cwd = $PSScriptRoot
Set-Location $cwd
$patterns = @(
  'downloaded_index*.html',
  'downloaded_index_fresh.html',
  'page*.html',
  'page_raw*.html',
  'served_index.html',
  'page_raw_after_*.html',
  'sim_payload.json',
  'api_*.json',
  'sim.backup.*.json',
  'calib.backup.*.json'
)
if(-not (Test-Path backups)) { New-Item -ItemType Directory -Path backups | Out-Null }
foreach($p in $patterns){ Get-ChildItem -Path . -Filter $p -ErrorAction SilentlyContinue | ForEach-Object { Write-Output "Moving $_.Name -> backups/"; Move-Item -Path $_.FullName -Destination (Join-Path $cwd 'backups') -Force } }
Write-Output "Done. Review contents of ./backups before committing."