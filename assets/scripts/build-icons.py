import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE = PROJECT_ROOT / "frontend/public/logo.png"
PUBLIC = PROJECT_ROOT / "frontend/public"
ICONS = PROJECT_ROOT / "assets/icons"
APP = PROJECT_ROOT / "build/SectorFlow.app"
MACOS = APP / "Contents/MacOS"
RESOURCES = APP / "Contents/Resources"
INFO_PLIST = APP / "Contents/Info.plist"
PKG_INFO = APP / "Contents/PkgInfo"
LAUNCHER_SRC = PROJECT_ROOT / "assets/app-launcher/launcher.c"
LAUNCHER_BIN = MACOS / "SectorFlow"
RUN_SH = RESOURCES / "run.sh"
ROOT_TXT = RESOURCES / "project-root.txt"
MAC_ICNS = ICONS / "SectorFlow-Mac.icns"
WIN_ICO = ICONS / "SectorFlow-Win.ico"
APP_ICNS = RESOURCES / "SectorFlow.icns"

ICNS_SIZES = [
    (16, False),
    (16, True),
    (32, False),
    (32, True),
    (128, False),
    (128, True),
    (256, False),
    (256, True),
    (512, False),
    (512, True),
]

FAVICON_PNG_SIZES = [16, 32, 48]
TOUCH_SIZE = 180
WIN_SIZES = [(16, 16), (32, 32), (48, 48), (256, 256)]
FAVICON_ICO_SIZES = [(16, 16), (32, 32), (48, 48)]


def load_source() -> Image.Image:
    if not SOURCE.exists():
        raise FileNotFoundError(f"source icon not found: {SOURCE}")
    return Image.open(SOURCE).convert("RGBA")


def save_png(img: Image.Image, size: int, path: Path) -> None:
    resized = img.resize((size, size), Image.LANCZOS)
    resized.save(path, "PNG")


def build_public(img: Image.Image) -> None:
    for size in FAVICON_PNG_SIZES:
        save_png(img, size, PUBLIC / f"favicon-{size}x{size}.png")
    save_png(img, TOUCH_SIZE, PUBLIC / "apple-touch-icon.png")
    img.save(PUBLIC / "favicon.ico", "ICO", sizes=FAVICON_ICO_SIZES)


def build_iconset(img: Image.Image) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="sf_iconset_"))
    iconset = tmp / "SectorFlow.iconset"
    iconset.mkdir()

    for base, is_2x in ICNS_SIZES:
        size = base * 2 if is_2x else base
        suffix = "@2x" if is_2x else ""
        save_png(img, size, iconset / f"icon_{base}x{base}{suffix}.png")

    return iconset


def build_mac_icns(img: Image.Image) -> None:
    iconset = build_iconset(img)
    try:
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(MAC_ICNS)],
            check=True,
        )
    finally:
        shutil.rmtree(iconset.parent)


def build_win_ico(img: Image.Image) -> None:
    img.save(WIN_ICO, "ICO", sizes=WIN_SIZES)


def make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build_app_bundle() -> None:
    APP.mkdir(parents=True, exist_ok=True)
    MACOS.mkdir(parents=True, exist_ok=True)
    RESOURCES.mkdir(parents=True, exist_ok=True)

    if not LAUNCHER_SRC.exists():
        raise FileNotFoundError(f"launcher source not found: {LAUNCHER_SRC}")

    subprocess.run(
        ["clang", "-arch", "arm64", "-O2", "-o", str(LAUNCHER_BIN), str(LAUNCHER_SRC)],
        check=True,
    )
    make_executable(LAUNCHER_BIN)

    info = {
        "CFBundleName": "SectorFlow",
        "CFBundleDisplayName": "SectorFlow",
        "CFBundleIdentifier": "com.sectorflow.SectorFlow",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "SectorFlow",
        "CFBundleIconFile": "SectorFlow",
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "10.15",
        "LSBackgroundOnly": True,
    }
    with INFO_PLIST.open("wb") as f:
        plistlib.dump(info, f, fmt=plistlib.FMT_XML)

    PKG_INFO.write_text("APPL????")
    shutil.copy2(MAC_ICNS, APP_ICNS)

    run_script = (
        "#!/bin/bash\n"
        'SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        'BUNDLE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"\n'
        "\n"
        'if [ -f "$SCRIPT_DIR/project-root.txt" ]; then\n'
        '  PROJECT_ROOT="$(cat "$SCRIPT_DIR/project-root.txt")"\n'
        "else\n"
        '  PROJECT_ROOT="$(cd "$BUNDLE_DIR/.." && pwd)"\n'
        "fi\n"
        "\n"
        'cd "$PROJECT_ROOT"\n'
        'export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"\n'
        "exec ./SectorFlow.command\n"
    )
    RUN_SH.write_text(run_script)
    make_executable(RUN_SH)

    ROOT_TXT.write_text(str(PROJECT_ROOT))

    try:
        subprocess.run(
            ["codesign", "--force", "--deep", "-s", "-", str(APP)],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        pass


def apply_command_icon() -> None:
    target = PROJECT_ROOT / "SectorFlow.command"
    if not target.exists():
        return
    try:
        subprocess.run(
            ["fileicon", "set", str(target), str(MAC_ICNS)],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        pass


def main() -> int:
    img = load_source()
    build_public(img)
    build_mac_icns(img)
    build_win_ico(img)
    build_app_bundle()
    apply_command_icon()
    print(f"built icons from {SOURCE}")
    print(f"  public: {PUBLIC}")
    print(f"  mac icns: {MAC_ICNS}")
    print(f"  win ico: {WIN_ICO}")
    print(f"  app bundle: {APP}")
    print(f"to run: open {APP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
