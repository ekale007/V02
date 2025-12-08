<#
commit-and-push-backups.ps1

Find the latest `calib.backup.*.json` and `sim.backup.*.json`, git-add them,
commit with a timestamped message and optionally push to the current branch.

Usage (in repo root):
  .\commit-and-push-backups.ps1

This script will prompt before pushing.
#>

Set-StrictMode -Version Latest

function Get-LatestFile($pattern) {
    $file = Get-ChildItem -Path . -Filter $pattern -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
    return $file
}

$calib = Get-LatestFile 'calib.backup.*.json'
$sim = Get-LatestFile 'sim.backup.*.json'

if (-not $calib -and -not $sim) {
    Write-Error "No backup files found matching patterns 'calib.backup.*.json' or 'sim.backup.*.json' in $(Get-Location)."
    exit 1
}

Write-Host "Found backups:" -ForegroundColor Cyan
if ($calib) { Write-Host "  calib: $($calib.Name)" }
if ($sim)   { Write-Host "  sim:   $($sim.Name)" }

# Ensure we're in a git repo
try {
    git rev-parse --is-inside-work-tree 2>$null | Out-Null
} catch {
    Write-Error "Current folder is not a git repository or 'git' is not in PATH. Run this script from the repo root where .git exists."
    exit 2
}

# Stage files
$filesToAdd = @()
if ($calib) { $filesToAdd += $calib.Name }
if ($sim)   { $filesToAdd += $sim.Name }

git add -- $filesToAdd

# Create commit message
$ts = (Get-Date).ToString('yyyyMMdd-HHmmss')
$commitMsg = "Add Pi calibration & sim backups ($ts)"

# Commit
$commitResult = git commit -m $commitMsg 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "git commit returned non-zero. Output:" -ForegroundColor Yellow
    Write-Host $commitResult
} else {
    Write-Host "Committed backups with message: $commitMsg" -ForegroundColor Green
}

# Ask whether to push
$push = Read-Host "Push commit to remote? (y/N)"
if ($push -match '^[yY]') {
    # determine current branch
    $branch = git rev-parse --abbrev-ref HEAD
    if (-not $branch) { $branch = 'HEAD' }
    Write-Host "Pushing to origin/$branch..."
    $pushResult = git push origin $branch 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "git push failed:" -ForegroundColor Red
        Write-Host $pushResult
        exit 3
    } else {
        Write-Host "Pushed to origin/$branch" -ForegroundColor Green
    }
} else {
    Write-Host "Skipped push. Local commit created." -ForegroundColor Yellow
}
