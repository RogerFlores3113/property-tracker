# PyInstaller spec for Property Helper: macOS .app, Windows folder app, Linux folder.
#
# Windows gets two executables in one folder:
#   "Property Helper.exe"      windowed, what the user double-clicks
#   "prophelper-mcp.exe"  console, what Claude Desktop / Codex launch for MCP over stdio
# A windowed Windows exe has no usable stdin/stdout, so the MCP side needs its own console build.
# macOS and Linux use one binary for both (`... mcp`).
#
# Run from the repo root:  uv run pyinstaller packaging/property-helper.spec --noconfirm

import os
import sys
from PyInstaller.utils.hooks import collect_submodules

HERE = SPECPATH                       # .../packaging
SRC = os.path.join(HERE, "..", "src")

# Every module of the package (the routers are imported by name at start-up, so PyInstaller can't see them all).
hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("mcp", filter=lambda name: not name.startswith("mcp.cli"))
    + collect_submodules("prophelper")
    + ["python_multipart"]
)

a = Analysis(
    [os.path.join(HERE, "entry.py")],
    pathex=[SRC],
    datas=[
        (os.path.join(SRC, "prophelper", "templates"), os.path.join("prophelper", "templates")),
        (os.path.join(SRC, "prophelper", "static"), os.path.join("prophelper", "static")),
        (os.path.join(HERE, "..", "skills"), os.path.join("prophelper", "skills")),  # the Claude and Codex skill files (Skills page)
        (os.path.join(HERE, "..", ".claude-plugin"), os.path.join("prophelper", ".claude-plugin")),  # the Claude plugin and marketplace files
    ],
    hiddenimports=hidden,
    excludes=["tkinter", "pytest", "mcp.cli", "typer"],
    noarchive=False,
)
pyz = PYZ(a.pure)

app_exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Property Helper" if sys.platform != "linux" else "property-helper",
    console=sys.platform == "linux",
    upx=False,          # UPX breaks macOS codesign and trips Windows antivirus
    icon=None,          # TODO: app icon (icns / ico)
)

executables = [app_exe]
if sys.platform == "win32":
    mcp_exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="prophelper-mcp",
        console=True,
        upx=False,
    )
    executables.append(mcp_exe)

coll = COLLECT(*executables, a.binaries, a.datas, upx=False, name="Property Helper")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Property Helper.app",
        bundle_identifier="dev.rogerflores.propertyhelper",
        version="0.1.0",
        info_plist={"NSHighResolutionCapable": True, "LSUIElement": False},
    )
