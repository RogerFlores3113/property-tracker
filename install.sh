#!/bin/sh
# Property Helper installer for macOS (Apple Silicon) and Linux (x86_64).
#
#   curl -fsSL https://raw.githubusercontent.com/rogerflores3113/property-helper/main/install.sh -o "${TMPDIR:-/tmp}/ph-install.sh" && sh "${TMPDIR:-/tmp}/ph-install.sh"
#
# (Saved to a file first, so a failed download stops loudly instead of running nothing.)
#
# Options:  --no-open   install but do not open the app
# Offline or private repository: PROPHELPER_INSTALL_FROM=<folder (or an https:// address, never http://) holding PropertyHelper-*.zip/.tar.gz and SHA256SUMS.txt>
#           (while the repository is private, GitHub only serves releases to people who are signed in, so download
#           the release files from the Releases page first and point this at that folder)
# Testing:  PROPHELPER_INSTALL_FROM=<folder or base URL holding the release files>
#           PROPHELPER_INSTALL_DIR=<folder to install into>
set -eu

install_property_helper() {

  BASE_URL="https://github.com/rogerflores3113/property-helper/releases/latest/download"
  OPEN_APP=1
  UPGRADE=0
  for arg in "$@"; do
    case "$arg" in
      --no-open) OPEN_APP=0 ;;
      -h|--help)
        echo "Usage: install.sh [--no-open]"
        exit 0
        ;;
      *)
        echo "Unknown option: $arg" >&2
        exit 2
        ;;
    esac
  done

  say() { printf '%s\n' "$*"; }
  fail() {
    printf '\nProperty Helper was not installed.\n%s\n' "$*" >&2
    exit 1
  }

  SOURCE="${PROPHELPER_INSTALL_FROM:-$BASE_URL}"
  OVERRIDE_DIR="${PROPHELPER_INSTALL_DIR:-}"
  case "$SOURCE" in
    http://*) fail "PROPHELPER_INSTALL_FROM points at a plain http:// address. The checksum would come from the same place as the download, so it would prove nothing. Use a folder on this computer or an https:// address." ;;
  esac

  OS="$(uname -s)"
  ARCH="$(uname -m)"
  case "$OS" in
    Darwin)
      case "$ARCH" in
        arm64) ;;
        *) fail "This Mac has an Intel processor. Property Helper is only built for Apple Silicon Macs (M1 or later) as a ready-made app. On an Intel Mac, use the \"Run it\" steps in README.md (download the ZIP and double-click Start Property Helper)." ;;
      esac
      ASSET="PropertyHelper-mac.zip"
      ;;
    Linux)
      case "$ARCH" in
        x86_64|amd64) ;;
        *) fail "This computer is $ARCH. Property Helper is only built for Linux x86_64 for now. You can run it from source instead: see the Prefer a terminal section in README.md." ;;
      esac
      ASSET="PropertyHelper-linux.tar.gz"
      ;;
    *)
      fail "This script supports macOS and Linux. On Windows, use install.ps1 (see INSTALL.md)."
      ;;
  esac

  WORK="$(mktemp -d "${TMPDIR:-/tmp}/prophelper-install.XXXXXX")"
  cleanup() { rm -rf "$WORK"; }
  trap cleanup EXIT INT TERM

  # running_pids <regex>: ids of processes whose command line matches, leaving out Claude's helper copy of the
  # app (the same program started with the argument mcp), which is not the window the person has open.
  running_pids() {
    for pid in $(pgrep -f -- "$1" 2>/dev/null || true); do
      [ "$pid" = "$$" ] && continue
      cmd="$(ps -o command= -p "$pid" 2>/dev/null || true)"
      [ -n "$cmd" ] || continue
      case "$cmd" in
        *" mcp") continue ;;
      esac
      printf '%s\n' "$pid"
    done
  }
  regex_escape() { printf '%s' "$1" | sed 's/[][\\.*^$+?(){}|]/\\&/g'; }

  fetch() { # fetch <name> <dest>
    case "$SOURCE" in
      http://*|https://*)
        curl -fsSL "${SOURCE%/}/$1" -o "$2" || return 1
        ;;
      *)
        [ -f "$SOURCE/$1" ] || return 1
        cp "$SOURCE/$1" "$2" || return 1
        ;;
    esac
  }

  say "Installing Property Helper..."
  say "Downloading $ASSET"
  fetch "$ASSET" "$WORK/$ASSET" || fail "Could not download $ASSET. Check your internet connection and try again. If this repository is private, GitHub only serves its releases to people who are signed in: download the release files from the Releases page and run this again with PROPHELPER_INSTALL_FROM set to that folder."
  if ! fetch "SHA256SUMS.txt" "$WORK/SHA256SUMS.txt"; then
    case "$SOURCE" in
      https://*) fail "This release is still being published: its checksum file (SHA256SUMS.txt) is added a few minutes after the app files. Wait about five minutes and run this again. Nothing was installed. If it keeps failing, see PROPHELPER_INSTALL_FROM at the top of install.sh." ;;
      *) fail "SHA256SUMS.txt is not in $SOURCE, so the download cannot be checked. Put the release's SHA256SUMS.txt next to the app file, or see PROPHELPER_INSTALL_FROM at the top of install.sh." ;;
    esac
  fi

  say "Checking the download"
  if command -v shasum >/dev/null 2>&1 && [ "$OS" = "Darwin" ]; then
    ACTUAL="$(shasum -a 256 "$WORK/$ASSET" | awk '{print $1}')"
  elif command -v sha256sum >/dev/null 2>&1; then
    ACTUAL="$(sha256sum "$WORK/$ASSET" | awk '{print $1}')"
  elif command -v shasum >/dev/null 2>&1; then
    ACTUAL="$(shasum -a 256 "$WORK/$ASSET" | awk '{print $1}')"
  else
    fail "No tool found to check the download (sha256sum or shasum)."
  fi
  EXPECTED="$(awk -v n="$ASSET" '{f=$2; sub(/^\*/, "", f); if (f == n) {print $1; exit}}' "$WORK/SHA256SUMS.txt" | tr 'A-F' 'a-f')"
  [ -n "$EXPECTED" ] || fail "SHA256SUMS.txt does not list $ASSET, so the download cannot be checked."
  if [ "$ACTUAL" != "$EXPECTED" ]; then
    fail "The download does not match its checksum, so it was not installed. Expected $EXPECTED but got $ACTUAL. Try again later, and tell the Property Helper maintainer if it keeps happening."
  fi
  say "Download verified"
  say "(This check catches a damaged download. It cannot catch a tampered release, because the checksum comes from the same release.)"

  mkdir -p "$WORK/unpacked"
  if [ "$OS" = "Darwin" ]; then
    ditto -x -k "$WORK/$ASSET" "$WORK/unpacked" || fail "Could not unpack $ASSET."
    [ -d "$WORK/unpacked/Property Helper.app" ] || fail "The download did not contain Property Helper.app."
  else
    tar -xzf "$WORK/$ASSET" -C "$WORK/unpacked" || fail "Could not unpack $ASSET."
    [ -d "$WORK/unpacked/Property Helper" ] || fail "The download did not contain the Property Helper folder."
  fi

  if [ "$OS" = "Darwin" ]; then
    if [ -n "$OVERRIDE_DIR" ]; then
      TARGET_DIR="$OVERRIDE_DIR"
    elif [ -w /Applications ]; then
      TARGET_DIR="/Applications"
    else
      TARGET_DIR="$HOME/Applications"
    fi
    mkdir -p "$TARGET_DIR" || fail "Could not create $TARGET_DIR."
    APP="$TARGET_DIR/Property Helper.app"

    MAC_PATTERN="$(regex_escape "Property Helper.app/Contents/MacOS")"
    if [ -z "$OVERRIDE_DIR" ] && [ -n "$(running_pids "$MAC_PATTERN")" ]; then
      say "Closing Property Helper so it can be updated. Your places and settings are stored elsewhere and are kept."
      osascript -e 'tell application "Property Helper" to quit' >/dev/null 2>&1 || true
      i=0
      while [ -n "$(running_pids "$MAC_PATTERN")" ] && [ "$i" -lt 20 ]; do
        sleep 1
        i=$((i + 1))
      done
      if [ -n "$(running_pids "$MAC_PATTERN")" ]; then
        fail "Property Helper is still open. Please quit it (Property Helper menu, then Quit) and run this again. Your data is safe. The Claude app does not need to be closed: its own background copy of Property Helper is left alone."
      fi
    fi

    if [ -e "$APP" ]; then
      UPGRADE=1
      say "Replacing the existing copy. Your places and settings are kept."
    fi
    # Copy into a temporary folder next to the target first, then swap, so a failed copy never leaves no app.
    NEW_APP="$TARGET_DIR/.Property Helper.new.$$.app"
    OLD_APP="$TARGET_DIR/.Property Helper.old.$$.app"
    rm -rf "$NEW_APP"
    ditto "$WORK/unpacked/Property Helper.app" "$NEW_APP" || { rm -rf "$NEW_APP"; fail "Could not copy the app into $TARGET_DIR. Your existing copy, if any, was left as it was."; }
    if [ -e "$APP" ]; then
      mv "$APP" "$OLD_APP" || { rm -rf "$NEW_APP"; fail "Could not replace the old copy at $APP."; }
    fi
    mv "$NEW_APP" "$APP" || { [ -e "$OLD_APP" ] && mv "$OLD_APP" "$APP"; rm -rf "$NEW_APP"; fail "Could not move the new app into place."; }
    rm -rf "$OLD_APP"
    chmod +x "$APP/Contents/MacOS/"* 2>/dev/null || true
    say "Installed to $APP"

    if [ "$OPEN_APP" = "1" ]; then
      say "Opening Property Helper"
      open "$APP" || say "Could not open it automatically. Open Property Helper from $TARGET_DIR."
    fi
  else
    if [ -n "$OVERRIDE_DIR" ]; then
      TARGET_DIR="$OVERRIDE_DIR"
    else
      TARGET_DIR="$HOME/.local/share/property-helper-app"
    fi
    mkdir -p "$TARGET_DIR" || fail "Could not create $TARGET_DIR."
    APP_DIR="$TARGET_DIR/Property Helper"
    EXE="$APP_DIR/property-helper"

    LINUX_PATTERN="(^| )$(regex_escape "$EXE")( |\$)"
    if [ -z "$OVERRIDE_DIR" ] && [ -n "$(running_pids "$LINUX_PATTERN")" ]; then
      say "Closing Property Helper so it can be updated. Your places and settings are stored elsewhere and are kept."
      for pid in $(running_pids "$LINUX_PATTERN"); do kill -TERM "$pid" >/dev/null 2>&1 || true; done
      sleep 2
      if [ -n "$(running_pids "$LINUX_PATTERN")" ]; then
        fail "Property Helper is still open. Please close it and run this again. Your data is safe. The Claude app does not need to be closed: its own background copy of Property Helper is left alone."
      fi
    fi

    if [ -e "$APP_DIR" ]; then
      UPGRADE=1
      say "Replacing the existing copy. Your places and settings are kept."
      rm -rf "$APP_DIR" || fail "Could not remove the old copy at $APP_DIR."
    fi
    cp -R "$WORK/unpacked/Property Helper" "$APP_DIR" || fail "Could not copy the app into $TARGET_DIR."
    chmod +x "$EXE" 2>/dev/null || true
    say "Installed to $APP_DIR"

    LINK_OK=0
    MENU_OK=0
    if [ -z "$OVERRIDE_DIR" ]; then
      mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
      if [ ! -e "$HOME/.local/bin/property-helper" ] || [ -L "$HOME/.local/bin/property-helper" ]; then
        ln -sf "$EXE" "$HOME/.local/bin/property-helper" && LINK_OK=1
      else
        say "Note: $HOME/.local/bin/property-helper already exists and is not a link, so I left it alone."
      fi
      if cat > "$HOME/.local/share/applications/property-helper.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Property Helper
Comment=Keep track of your apartment or house hunt
Exec="$EXE"
Terminal=false
Categories=Office;
DESKTOP
      then
        MENU_OK=1
        say "Added a Property Helper entry to your applications menu"
      else
        say "Could not add an applications menu entry. You can still run $EXE"
      fi
      if [ "$LINK_OK" = "1" ]; then
        say "Added the command property-helper"
        case ":$PATH:" in
          *":$HOME/.local/bin:"*) ;;
          *) say "Note: $HOME/.local/bin is not on your PATH yet, so typing property-helper will not work until it is. For now run: $HOME/.local/bin/property-helper" ;;
        esac
      fi
    fi

    if [ "$OPEN_APP" = "1" ]; then
      say "Opening Property Helper"
      nohup "$EXE" >/dev/null 2>&1 &
    fi
  fi

  say ""
  say "Done. Your places and settings live in their own folder and are never touched by installs or updates."
  if [ "$OS" = "Darwin" ]; then
    say "Property Helper is in your Applications folder (or ~/Applications)."
    CLAUDE_CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
  else
    if [ "${MENU_OK:-0}" = "1" ] && [ "${LINK_OK:-0}" = "1" ]; then
      say "Property Helper is in your applications menu, or run property-helper."
    elif [ "${MENU_OK:-0}" = "1" ]; then
      say "Property Helper is in your applications menu."
    else
      say "Property Helper is installed in $APP_DIR. Run $EXE to open it."
    fi
    CLAUDE_CFG="$HOME/.config/Claude/claude_desktop_config.json"
  fi
  if [ "$OPEN_APP" = "1" ]; then
    say "Property Helper should now be open in your web browser."
  fi
  if [ "$UPGRADE" = "1" ] && [ -f "$CLAUDE_CFG" ] && grep -q "property-helper" "$CLAUDE_CFG" 2>/dev/null; then
    say "Already connected. Restart the Claude app to use the new version."
  elif [ "$OPEN_APP" = "1" ]; then
    say "Next: press \"Connect the Claude app\", then press \"Add skills\"."
  else
    say "Next: open Property Helper, then press \"Connect the Claude app\" and \"Add skills\"."
  fi
}

# Everything above is inside one function that only runs here, on the last line, so a download that was
# cut off part way installs nothing.
install_property_helper "$@"
