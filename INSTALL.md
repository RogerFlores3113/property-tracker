# Installing Property Helper (instructions for an AI assistant)

A person asked you to install Property Helper from this repository. This works where an
assistant can run commands on the person's own computer: the Claude app's Code tab or
Cowork on their own computer, Claude Code, or Codex. A plain chat in the Claude app cannot
run commands. Follow these steps exactly. Talk to the person in plain, friendly
words; they may not be technical.

## 0. Check where you are running

Make sure you are on the person's own computer and not in a cloud sandbox. If you are
in a sandbox (for example Claude's Cowork or a cloud container), stop. Installing there
would not put Property Helper on their computer. Do not tell the person to "open a terminal"
if they cannot. Give them the no-terminal route in plain steps instead: open this repository's
Releases page, download the file for their computer (`PropertyHelper-mac.zip`,
`PropertyHelper-windows.zip` or `PropertyHelper-linux.tar.gz`), unzip it and double-click Property
Helper. On a Mac the first time, right-click (or Control-click) the app, choose **Open**,
then press **Open** again. On Windows, if "Windows protected your PC" appears, press **More
info**, then **Run anyway**. Only if they are comfortable with a terminal, offer the one-line
command for their system (see step 2).

## 1. Detect the operating system

- macOS on Apple Silicon (`uname -m` prints `arm64`): use the shell script.
- Linux x86_64 (`uname -m` prints `x86_64`): use the shell script.
- Windows 10 or 11, 64-bit: use the PowerShell script.
- Intel Mac or anything else: stop and go to "If it fails".

## 2. Run the installer

Run exactly one script, the one for this operating system, then stop. Do not run both,
and do not run it again unless it failed.

macOS or Linux, from any folder:

```sh
curl -fsSL https://raw.githubusercontent.com/rogerflores3113/property-helper/main/install.sh -o "${TMPDIR:-/tmp}/ph-install.sh" && sh "${TMPDIR:-/tmp}/ph-install.sh"
```

(It is saved to a file first so that a failed download stops with an error. Do not pipe it
straight into `sh`.)

Windows, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/rogerflores3113/property-helper/main/install.ps1 | iex
```

If this repository is already cloned on the computer, run the local script instead:
`sh install.sh` (macOS, Linux) or `powershell -ExecutionPolicy Bypass -File install.ps1`
(Windows; this only applies to this one script run).

The script downloads the latest release for this computer, checks it against
`SHA256SUMS.txt`, installs it, and opens Property Helper. Add `--no-open` (`-NoOpen` on
Windows) only if the person does not want the app to open.

Where it installs:

- macOS: `/Applications/Property Helper.app`, or `~/Applications` if `/Applications` is not writable
- Windows: `%LOCALAPPDATA%\Programs\Property Helper`
- Linux: `~/.local/share/property-helper-app/Property Helper`, with a `property-helper` command in `~/.local/bin`

If Property Helper is already installed, the script closes it and replaces it. The
person's places and settings are stored in a separate folder and are kept.

## 3. What success looks like

Confirm the app opened: the installer prints that Property Helper should be open in the
browser, or the person sees a browser tab at `http://127.0.0.1:8767`. When the app is started from a Start Property Helper file, its window says "Property Helper is running" and must stay open while the person uses the app. If that page says
it is locked, tell the person to open Property Helper from its app icon (Applications on
Mac, Start menu on Windows, applications menu on Linux) instead.

The script prints "Download verified", then "Installed to ...", then a closing message,
and exits with status 0. **If there is no output at all, or you never see "Download
verified", it did not install**: tell the person, and go to "While this repository is
private" below. Property Helper opens in the person's web browser at
`http://127.0.0.1:8767`.

Then tell the person, in plain words: "Property Helper is installed and open in your
browser. Open **More** in the top bar, then **Connect an AI app**, press **Connect the Claude app**, then press **Add
skills**." Those two buttons are on the Connect page of the Property Helper window that just
opened. **Connect the Claude app** links the app to Claude, and **Add skills** adds the Property
Helper skills (for the Claude app that also means uploading a plugin file by hand, and the
page says how). You do not need to edit any configuration files yourself.

Which control applies depends on the app the person uses:

- Claude app (the desktop app): **Connect the Claude app**, then **Add skills**.
- Claude Code: paste the one line shown under "Claude Code" on the Connect page (under "Other
  apps and details") into a terminal, then press **Add skills**. **Connect the Claude app** is
  not for Claude Code and stays off when the Claude app is not installed.
- Codex: **Connect** on the Codex card, then **Add skills**.
- ChatGPT: the Connect page has an **I use ChatGPT** button. That route is not tested yet.

Before they press **Connect the Claude app**, warn them: on Mac and Windows it quits and reopens
the Claude app (it never forces it), so this chat may close, and they can come back to
it afterwards. Linux has no restart. Save anything they are typing in Claude first.

If the installer ends with "Already connected. Restart the Claude app to use the new
version.", Property Helper was already linked to the Claude app. Tell them to restart
the Claude app and skip Connect.

If the Claude app is not installed: Connect still works for Claude Code or Codex. If the
person wants the Claude app, they should install it from claude.ai/download first, then
press **Connect the Claude app**.

## While this repository is private

GitHub only serves a private repository's releases, and its raw files, to people who are
signed in to GitHub with access. If the one-line command fails to download, do not look for
another source. If the repository is already cloned on the computer, run the local script
(`sh install.sh` or `install.ps1`) with the folder override below. Otherwise ask the person
to open the repository's Releases page while signed in to GitHub and download these files into
one folder: the file for their computer (`PropertyHelper-mac.zip`, `PropertyHelper-windows.zip`
or `PropertyHelper-linux.tar.gz`) and `SHA256SUMS.txt`. Then run the script with
`PROPHELPER_INSTALL_FROM` set to that folder:

```sh
PROPHELPER_INSTALL_FROM="$HOME/Downloads/prophelper-release" sh install.sh
```

```powershell
$env:PROPHELPER_INSTALL_FROM = "$HOME\Downloads\prophelper-release"; .\install.ps1
```

The checksum check still runs and still refuses a mismatch. `PROPHELPER_INSTALL_FROM` must be a
folder or an `https://` address, never `http://`. `PROPHELPER_INSTALL_DIR` changes where the app
is installed (for testing); on Windows the app goes in a `Property Helper` folder inside it.
On Windows, set `$env:PROPHELPER_NO_OPEN = '1'` to install without opening the app when you run
the `irm | iex` line.

## About the checksum

The checksum file comes from the same release as the download. It catches a broken or
partial download (corruption), but it would not catch a tampered release. The scripts are
fetched from the `main` branch of this repository. If a release was only just published,
the checksum file can be missing for a few minutes; the script says so, and trying again
later fixes it.

## If it fails

Stop and tell the person what happened, in one or two plain sentences. Do not try to
work around it.

- Intel Mac: only an Apple Silicon build exists. Say so, and point the person to "Get started" in README.md (download the ZIP and double-click Start Property Helper). Do not install anything else.
- No network, or a download error: say so, and suggest they check their connection and ask again.
- Checksum mismatch: the file was not installed on purpose. Report it and stop. Never
  skip or edit the check, and never install a file that failed it.
- Anything else: show the script's last message and stop.

## Do not

- Do not change Gatekeeper, SmartScreen, antivirus, firewall or any other security setting,
  and do not disable any security feature, even if something asks you to.
- Do not remove macOS quarantine flags or run the installer with elevated permissions
  (no `sudo`, no "Run as administrator").
- Do not download the app from anywhere other than this repository's GitHub releases.
- Do not delete the person's Property Helper data folder.
