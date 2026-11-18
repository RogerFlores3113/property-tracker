# Property Helper installer for Windows 10/11 (64-bit), Windows PowerShell 5.1 or newer.
#
#   irm https://raw.githubusercontent.com/rogerflores3113/property-helper/main/install.ps1 | iex
#
# Options:  -NoOpen   install but do not open the app
#           ($env:PROPHELPER_NO_OPEN = '1' does the same; -NoOpen cannot be passed through irm | iex)
# Offline or private repository: while the repository is private, GitHub only serves releases to people who are
#           signed in. Download the release files from the Releases page, then set $env:PROPHELPER_INSTALL_FROM to that folder.
# Testing:  $env:PROPHELPER_INSTALL_FROM = folder or base URL holding the release files
#           $env:PROPHELPER_INSTALL_DIR  = folder to install into (the app goes in a 'Property Helper' folder inside it,
#                                       and the folder you name is never deleted)
param([switch]$NoOpen)

# -NoOpen cannot be passed through irm | iex, so an environment variable does the same.
if ($env:PROPHELPER_NO_OPEN -match '^(1|true|yes)$') { $NoOpen = [switch]$true }
# Only a script file (not irm | iex) has a path; exiting would close the window of a pasted command.
$JatScriptFile = $MyInvocation.MyCommand.Path
$global:LASTEXITCODE = 0

# Everything runs inside this block, so the settings below stay out of the caller's PowerShell session.
& {
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

$BaseUrl = 'https://github.com/rogerflores3113/property-helper/releases/latest/download'
$Asset = 'PropertyHelper-windows.zip'

function Stop-Install([string]$Message) {
    Write-Host ''
    Write-Host 'Property Helper was not installed.' -ForegroundColor Red
    Write-Host $Message
    throw 'PROPHELPER_INSTALL_STOPPED'
}

function Install-PropertyHelper {
    $Source = $env:PROPHELPER_INSTALL_FROM
    if (-not $Source) { $Source = $BaseUrl }
    $Override = $env:PROPHELPER_INSTALL_DIR
    if ($Source -match '^http://') {
        Write-Host ''
        Write-Host 'Property Helper was not installed.' -ForegroundColor Red
        Write-Host 'PROPHELPER_INSTALL_FROM points at a plain http:// address. The checksum would come from the same place as the download, so it would prove nothing. Use a folder on this computer or an https:// address.'
        $global:LASTEXITCODE = 1
        return
    }

    if (-not [Environment]::Is64BitOperatingSystem) {
        Write-Host ''
        Write-Host 'Property Helper was not installed.' -ForegroundColor Red
        Write-Host 'Property Helper is only built for 64-bit Windows.'
        $global:LASTEXITCODE = 1
        return
    }

    # With an override, the app goes in a folder of its own inside it, so replacing it never removes the folder you named.
    if ($Override) { $Target = Join-Path $Override 'Property Helper' } else { $Target = Join-Path $env:LOCALAPPDATA 'Programs\Property Helper' }

    $Work = Join-Path ([IO.Path]::GetTempPath()) ('prophelper-install-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Work | Out-Null

    try {
        function Get-ReleaseFile([string]$Name, [string]$Dest) {
            if ($Source -match '^https?://') {
                Invoke-WebRequest -UseBasicParsing -Uri ($Source.TrimEnd('/') + '/' + $Name) -OutFile $Dest
            } else {
                $local = Join-Path $Source $Name
                if (-not (Test-Path -LiteralPath $local)) { throw "Missing $local" }
                Copy-Item -LiteralPath $local -Destination $Dest
            }
        }

        Write-Host 'Installing Property Helper...'
        Write-Host "Downloading $Asset"
        $zip = Join-Path $Work $Asset
        $sums = Join-Path $Work 'SHA256SUMS.txt'
        try { Get-ReleaseFile $Asset $zip } catch { Stop-Install "Could not download $Asset. Check your internet connection and try again. If this repository is private, GitHub only serves its releases to people who are signed in: download the release files from the Releases page and run this again with PROPHELPER_INSTALL_FROM set to that folder." }
        try { Get-ReleaseFile 'SHA256SUMS.txt' $sums } catch {
            if ($Source -match '^https://') { Stop-Install 'This release is still being published: its checksum file (SHA256SUMS.txt) is added a few minutes after the app files. Wait about five minutes and run this again. Nothing was installed.' }
            Stop-Install "SHA256SUMS.txt is not in $Source, so the download cannot be checked. Put the release's SHA256SUMS.txt next to the app file, or see PROPHELPER_INSTALL_FROM at the top of install.ps1."
        }

        Write-Host 'Checking the download'
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash.ToLower()
        $expected = $null
        foreach ($line in Get-Content -LiteralPath $sums) {
            $parts = $line.Trim() -split '\s+', 2
            if ($parts.Count -eq 2 -and $parts[1].TrimStart('*') -eq $Asset) { $expected = $parts[0].ToLower(); break }
        }
        if (-not $expected) { Stop-Install "SHA256SUMS.txt does not list $Asset, so the download cannot be checked." }
        if ($actual -ne $expected) {
            Stop-Install "The download does not match its checksum, so it was not installed. Expected $expected but got $actual. Try again later, and tell the Property Helper maintainer if it keeps happening."
        }
        Write-Host 'Download verified'
        Write-Host '(This check catches a damaged download. It cannot catch a tampered release, because the checksum comes from the same release.)'

        $unpacked = Join-Path $Work 'unpacked'
        Expand-Archive -LiteralPath $zip -DestinationPath $unpacked -Force
        $inner = Join-Path $unpacked 'Property Helper'
        if (-not (Test-Path -LiteralPath (Join-Path $inner 'Property Helper.exe'))) {
            Stop-Install 'The download did not contain Property Helper.exe.'
        }

        $upgrade = $false
        # Stop a running copy that lives in the install folder.
        if (Test-Path -LiteralPath $Target) {
            $full = [IO.Path]::GetFullPath($Target).TrimEnd('\') + '\'
            $running = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
                $_.ProcessName -in @('Property Helper', 'prophelper-mcp') -and $_.Path -and $_.Path.StartsWith($full, [StringComparison]::OrdinalIgnoreCase)
            })
            if ($running.Count -gt 0) {
                Write-Host 'Closing Property Helper so it can be updated. Your places and settings are stored elsewhere and are kept.'
                $running | Stop-Process -Force
                Start-Sleep -Seconds 2
            }
            $upgrade = $true
            Write-Host 'Replacing the existing copy. Your places and settings are kept.'
            try { Remove-Item -LiteralPath $Target -Recurse -Force } catch {
                Stop-Install "Could not replace $Target. Please close Property Helper and try again. Your data is safe."
            }
        }

        New-Item -ItemType Directory -Path $Target -Force | Out-Null
        Copy-Item -Path (Join-Path $inner '*') -Destination $Target -Recurse -Force
        $exe = Join-Path $Target 'Property Helper.exe'
        Write-Host "Installed to $Target"

        if (-not $Override) {
            try {
                $programs = Join-Path ([Environment]::GetFolderPath('Programs')) 'Property Helper.lnk'
                $shell = New-Object -ComObject WScript.Shell
                $lnk = $shell.CreateShortcut($programs)
                $lnk.TargetPath = $exe
                $lnk.WorkingDirectory = $Target
                $lnk.Save()
                Write-Host 'Added Property Helper to your Start menu'
            } catch {
                Write-Host 'Could not add a Start menu shortcut. You can still open Property Helper from its folder.'
            }
        }

        Write-Host ''
        Write-Host 'Done. Your places and settings live in their own folder and are never touched by installs or updates.'
        Write-Host 'Property Helper is in your Start menu.'
        $cfg = Join-Path $env:APPDATA 'Claude\claude_desktop_config.json'
        $connected = $upgrade -and (Test-Path -LiteralPath $cfg) -and (Select-String -LiteralPath $cfg -SimpleMatch 'property-helper' -Quiet)
        if (-not $NoOpen) {
            Write-Host 'Opening Property Helper'
            Start-Process -FilePath $exe -WorkingDirectory $Target
            Write-Host 'Property Helper should now be open in your web browser.'
        }
        if ($connected) {
            Write-Host 'Already connected. Restart the Claude app to use the new version.'
        } elseif (-not $NoOpen) {
            Write-Host 'Next: press "Connect the Claude app", then press "Add skills".'
        } else {
            Write-Host 'Next: open Property Helper, then press "Connect the Claude app" and "Add skills".'
        }
    }
    catch {
        if ($_.Exception.Message -ne 'PROPHELPER_INSTALL_STOPPED') {
            Write-Host ''
            Write-Host 'Property Helper was not installed.' -ForegroundColor Red
            Write-Host $_.Exception.Message
        }
        $global:LASTEXITCODE = 1
        return
    }
    finally {
        Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Install-PropertyHelper
}
if ($global:LASTEXITCODE -ne 0 -and $JatScriptFile) { exit $global:LASTEXITCODE }
