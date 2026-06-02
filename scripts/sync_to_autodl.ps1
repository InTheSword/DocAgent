param(
    [string]$HostName = "connect.cqa1.seetacloud.com",
    [int]$Port = 13566,
    [string]$User = "root",
    [string]$RemoteDir = "/root/autodl-tmp/docagent",
    [string]$LocalDir = "D:\Projects\docagent"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not (Test-Path -LiteralPath $LocalDir)) {
    throw "LocalDir does not exist: $LocalDir"
}

$archive = Join-Path $env:TEMP "docagent-sync.tar"
if (Test-Path -LiteralPath $archive) {
    Remove-Item -LiteralPath $archive -Force
}

Push-Location -LiteralPath $LocalDir
try {
    tar --exclude "data/raw" `
        --exclude "data/processed" `
        --exclude "outputs" `
        --exclude "__pycache__" `
        --exclude ".pytest_cache" `
        -cf $archive .
}
finally {
    Pop-Location
}

ssh -p $Port "$User@$HostName" "mkdir -p '$RemoteDir'"
scp -P $Port $archive "$User@$HostName:$RemoteDir/docagent-sync.tar"
ssh -p $Port "$User@$HostName" "cd '$RemoteDir' && tar -xf docagent-sync.tar && rm docagent-sync.tar"

Write-Host "Synced $LocalDir to $User@$HostName:$RemoteDir"
