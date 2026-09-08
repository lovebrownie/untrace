#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$Repo = 'lovebrownie/untrace'
$Api = "https://api.github.com/repos/$Repo/releases/latest"
$release = Invoke-RestMethod -Uri $Api -UseBasicParsing
$tag = $release.tag_name
if (-not $tag) {
    throw 'failed to resolve latest release tag'
}

$setup = "untrace-$tag-setup.exe"
$url = "https://github.com/$Repo/releases/download/$tag/$setup"
$dest = Join-Path $env:TEMP $setup

Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
$proc = Start-Process -FilePath $dest -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    throw "Setup failed with exit code $($proc.ExitCode)"
}
