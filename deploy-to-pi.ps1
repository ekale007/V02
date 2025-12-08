<#
.\deploy-to-pi.ps1

Simple PowerShell helper to copy the project to a Raspberry Pi, fix line endings,
set execute bits and optionally run the install script (with or without systemd).

Usage examples:
  .\deploy-to-pi.ps1 -PiHost 192.168.68.100
  .\deploy-to-pi.ps1 -PiHost 192.168.68.100 -PiUser pi -UseSystemd

Requirements: OpenSSH client (scp/ssh) available in PATH.
#>

param(
    [string]$PiHost,
    [string]$PiUser = 'pi',
    [string]$LocalPath = "$PSScriptRoot",
    [string]$RemotePath = "~/V02",
    [switch]$UseSystemd,
    [switch]$RunInstaller
)

if (-not $PiHost) {
    Write-Error "PiHost is required. Example: .\deploy-to-pi.ps1 -PiHost 192.168.68.100 -RunInstaller -UseSystemd"
    exit 2
}

Write-Host "Deploying $LocalPath -> $PiUser@$PiHost:$RemotePath"

# 1) Copy files
Write-Host "Copying files via scp..."
$scpCmd = "scp -r `"$LocalPath`" $PiUser@$PiHost:$RemotePath"
Write-Host $scpCmd
& scp -r "$LocalPath" "$PiUser@$PiHost:$RemotePath"
if ($LASTEXITCODE -ne 0) { Write-Error "scp failed (exit $LASTEXITCODE)"; exit $LASTEXITCODE }

# 2) Fix line endings and make installer executable
Write-Host "Fixing line endings and permissions on the Pi..."
$fixCmd = "cd $RemotePath && sed -i 's/\r$//' ./scripts/install.sh && chmod +x ./scripts/install.sh"
Write-Host "ssh $PiUser@$PiHost '$fixCmd'"
& ssh "$PiUser@$PiHost" "cd $RemotePath && sed -i 's/\r$//' ./scripts/install.sh && chmod +x ./scripts/install.sh"
if ($LASTEXITCODE -ne 0) { Write-Warning "Remote fix commands returned $LASTEXITCODE; continuing..." }

if ($RunInstaller) {
    if ($UseSystemd) {
        Write-Host "Running installer on Pi and enabling systemd service (requires sudo)..."
        & ssh "$PiUser@$PiHost" "cd $RemotePath && sudo ./scripts/install.sh --yes"
    } else {
        Write-Host "Running installer on Pi without systemd (safe) ..."
        & ssh "$PiUser@$PiHost" "cd $RemotePath && ./scripts/install.sh --no-systemd --yes"
    }
    if ($LASTEXITCODE -ne 0) { Write-Warning "Installer returned $LASTEXITCODE" }
}

Write-Host "Deploy finished. You can open http://$PiHost:8080 in your browser."

Write-Host "If you enabled systemd you can check service status with:"
Write-Host "  ssh $PiUser@$PiHost 'sudo systemctl status robot-arm.service'"
