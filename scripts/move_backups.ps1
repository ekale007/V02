$files = @(
  'downloaded_index.html',
  'downloaded_index_fresh.html',
  'page.html',
  'page_raw_after_deploy.html',
  'page_raw_after_patch.html',
  'page_raw_after_reapply.html',
  'served_index.html',
  'sim_payload.json',
  'api_calib.json',
  'api_sim.json',
  'api_status.json'
)
if(-not (Test-Path 'backups')){ New-Item -ItemType Directory -Path 'backups' | Out-Null }
foreach($f in $files){
  if(Test-Path $f){ Move-Item -Path $f -Destination 'backups' -Force; Write-Output "Moved $f" } else { Write-Output "Not found: $f" }
}
Write-Output 'Done.'
