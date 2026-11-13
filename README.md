# Property Helper

A helper for your own apartment or house hunt that lives on your own computer. It is free and open source, has no
accounts, and keeps your data on your computer.

## Get started (about 2 minutes)

1. **Download it.** On this page press the green **Code** button, then **Download ZIP**. Unzip it somewhere you will
   keep it (not the Downloads folder).
2. **Double-click Start Property Helper.** On a Mac it is called `Start Property Helper.command` (the first time,
   right-click it, choose **Open**, then press **Open** again). On Windows it is `Start Property Helper.bat` (if
   "Windows protected your PC" appears, press **More info**, then **Run anyway**). The first time it sets itself up,
   which takes about a minute.
3. **It opens in your browser.** A window says "Property Helper is running". Keep that window open while you use the
   app, and close it to stop. Next time, double-click the same file.

If the page says it is **locked**, double-click Start Property Helper again. The app only answers to this computer.

## What it does

- **Keeps every place in one spot.** Paste a link or the listing text on **Add** and the price, bedrooms and fees are
  filled in for you to check. Property Helper never opens the link itself.
- **Shows where each place stands.** A **Board** with a column for each step (Saved, Contacted, Tour booked, Toured,
  Applied, and so on), plus **Today** for tours, replies you are waiting on and dates coming up.
- **Tells you what it really costs.** The true monthly cost with the fees counted, and the numbers still missing named.
- **Checks each place against what matters to you.** Price, bedrooms, commute, laundry, parking, pets and more, with
  "must haves" and how much each one matters. Commutes are measured to the important places you go often.
- **Maps and compares.** A **Map**, a **Calendar** of tours and dates, and a **Compare** page side by side.

A made-up **sample search** is in Settings so you can look around first. Your own notes are yours: an AI app can add
its own notes next to them but never changes or deletes yours.

## Use it with Claude

This is optional. With the Claude app on your computer you can paste a listing into a chat and say "add this to my
search". In Property Helper open **More**, then **Connect an AI app**, press **Connect the Claude app**, then **Add
skills**. Claude can add and update places, and it can never delete anything. (Claude on the web, in your browser,
can't reach apps on your computer, so it won't work for this.)

## What leaves your computer

Your data stays on this computer. The map loads street tiles from OpenStreetMap, which is on by default and can be
turned off in Settings. Nothing else is sent unless you turn it on or click it:

- an address lookup (off by default), through OpenStreetMap's free lookup service, at most one request a second;
- AI help with your own Anthropic key, only when you press an AI button;
- the "Open in Claude" link, which opens claude.ai with a prompt only when you click it;
- listing photos (off by default), which your browser loads from the website the listing points to.

No tracking, no analytics, no update checks, no accounts. The Privacy page lists all of this again. **Download a backup
copy** in Settings now and then.

## Advanced

**Install with an assistant.** Paste this repo's link into an assistant that can run commands on your own computer
(the Claude app's Code tab, Claude Code or Codex) and say "Install". It reads [INSTALL.md](INSTALL.md), runs the
one install script for your computer, checks the download against its checksum and opens the app. Or download
`PropertyHelper-mac.zip`, `PropertyHelper-windows.zip` or `PropertyHelper-linux.tar.gz` from the Releases page and
unzip it. Or run the install line yourself (it is saved to a file first, so a failed download stops with an error).
Mac or Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/rogerflores3113/property-tracker/main/install.sh -o "${TMPDIR:-/tmp}/ph-install.sh" && sh "${TMPDIR:-/tmp}/ph-install.sh"
```

Windows, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/rogerflores3113/property-tracker/main/install.ps1 | iex
```

The script checks the download against a checksum from the same release. That catches a damaged download, not a
tampered release. Builds exist for Apple silicon Macs, Windows 10 or 11 (64-bit) and Linux (x86_64). While this
repository is private, see INSTALL.md for the folder override (`PROPHELPER_INSTALL_FROM`). The app is not code-signed
yet. Your places are kept in a folder of their own, so installing again to update never touches them.

**Command line**, with [uv](https://docs.astral.sh/uv/) installed:

```sh
uv run prophelper serve        # starts the app and opens your browser (port 8767)
uv run prophelper open         # opens a fresh, unlocked window of the running app
```

**MCP.** Connecting an AI app runs `prophelper mcp`, an MCP server that talks to the same data over STDIO. It can add
and update places, and it can never delete anything. Other apps and the hand-written settings are on the Connect page
under "Other apps and details".

**Building and tests.**

```sh
uv sync --all-groups
uv run pytest -q
```

The code is in `src/prophelper`: `store.py` (SQLite, schema and migrations), the pure modules `stages.py`,
`scoring.py`, `money.py`, `commute.py`, `redflags.py` and `parsers.py`, `enrich.py` (puts them together for the
pages), and the pages in `routes_*.py` with templates in `templates/`. The product and architecture decisions are
in [docs/DESIGN.md](docs/DESIGN.md). Packaging (PyInstaller) is in `packaging/`.
