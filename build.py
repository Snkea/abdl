"""
build.py — CrinkleDen standalone Windows build script
======================================================

Usage
-----
    python build.py --build           # build exe (prompts for missing tools)
    python build.py --build --onefile # single .exe (slower startup, easier to share)
    python build.py --build --onedir  # fast-start folder + launcher exe (default)
    python build.py --clean           # remove build/ and dist/ artefacts
    python build.py --check           # check all deps are installed, don't build
    python build.py --install-deps    # pip install everything needed, then exit

What gets baked in
------------------
  • All Python modules (ui.py, database.py, scraper.py, all extension modules)
  • PyQt6 runtime (Qt6 DLLs, platform plugins, styles)
  • SQLite3 (built into Python)
  • requests, beautifulsoup4, lxml, cryptography
  • abdl_logger, abdl_sites, image_cache, db_mgmt_enhanced, scraper_extended
  • A bundled default crinkleden.db  (created fresh on first run if absent)

What is NOT baked in (runs fine without, graceful fallback)
-----------------------------------------------------------
  • Playwright / Chromium — too large (~250 MB browser binary).
    The built exe detects whether Playwright is installed and shows a
    friendly "Install Playwright" dialog if it isn't.  The user just runs:
        playwright install chromium
    once after receiving the exe.  This is handled automatically by the
    built-in installer dialog (see PlaywrightInstallDialog in ui.py).

Output
------
  --onedir  (default):  dist/CrinkleDen/
                          CrinkleDen.exe        ← double-click to run
                          _internal/            ← Qt DLLs etc (keep with exe)
                        → Zip up dist/CrinkleDen/ and send that folder.

  --onefile:            dist/CrinkleDen.exe     ← single file, slower first launch
                        → Send just that one file.

Build takes ~2–5 min first time; subsequent builds are faster.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

# ── Project root = folder containing this script ────────────────────────────
ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
SPEC  = ROOT / "CrinkleDen.spec"

APP_NAME    = "CrinkleDen"
APP_VERSION = "2.0"
PYINSTALLER_MIN = (6, 11)  # minimum for Python 3.13 compatibility
ENTRY_POINT = ROOT / "ui.py"
ICON_FILE   = ROOT / "icon.ico"           # optional — skipped if absent

# All .py modules that must be present alongside ui.py
REQUIRED_MODULES = [
    "database.py",
    "scraper.py",
    "scrape_server.py",
    "db_mgmt_enhanced.py",
    "scraper_extended.py",
    "abdl_logger.py",
    "abdl_sites.py",
    "image_cache.py",
    "thumbnail_cache.py",
]

# PyPI packages the build depends on
# NOTE: PyInstaller 6.11+ is required for Python 3.13 — older versions
#       cause "Failed to load Python DLL" at runtime.
REQUIRED_PACKAGES = [
    "PyInstaller>=6.11",
    "PyQt6>=6.4.0",
    "requests>=2.31.0",
    "beautifulsoup4>=4.12.0",
    "lxml>=4.9.0",
    "cryptography",
    "Pillow",
]

# ── Colour helpers (Windows ANSI) ────────────────────────────────────────────
def _c(code, text):
    if sys.stdout.isatty() and platform.system() == "Windows":
        os.system("")   # enable VT100 on Windows 10+
    return f"\033[{code}m{text}\033[0m"

OK   = lambda s: print(_c("92", f"  ✓ {s}"))
WARN = lambda s: print(_c("93", f"  ⚠ {s}"))
ERR  = lambda s: print(_c("91", f"  ✗ {s}"))
INFO = lambda s: print(_c("96", f"  → {s}"))
HEAD = lambda s: print(_c("1;95", f"\n{'='*60}\n  {s}\n{'='*60}"))


# ════════════════════════════════════════════════════════════════════════════
# 1. Dependency checking
# ════════════════════════════════════════════════════════════════════════════

def check_python():
    HEAD("Checking Python version")
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        ERR(f"Python 3.10+ required, got {major}.{minor}")
        sys.exit(1)
    OK(f"Python {major}.{minor}")


def check_dependencies(install_missing=False):
    HEAD("Checking build dependencies")
    missing = []

    for pkg_spec in REQUIRED_PACKAGES:
        pkg_name = pkg_spec.split(">=")[0].split("==")[0].lower()
        import_name = {
            "pyinstaller": "PyInstaller",
            "pyqt6":       "PyQt6",
            "beautifulsoup4": "bs4",
            "pillow": "PIL",
        }.get(pkg_name, pkg_name)

        try:
            __import__(import_name)
            OK(pkg_spec)
        except ImportError:
            WARN(f"{pkg_spec}  — NOT INSTALLED")
            missing.append(pkg_spec)

    if missing:
        if install_missing:
            HEAD("Installing missing packages")
            for pkg in missing:
                INFO(f"pip install {pkg}")
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg],
                    stdout=subprocess.DEVNULL,
                )
                OK(f"Installed {pkg}")
        else:
            print()
            WARN(f"{len(missing)} missing package(s). Run:")
            print(f"\n    python build.py --install-deps\n")
            sys.exit(1)

    return len(missing) == 0


def check_source_files():
    HEAD("Checking source files")
    ok = True
    for name in REQUIRED_MODULES:
        p = ROOT / name
        if p.exists():
            OK(name)
        else:
            WARN(f"{name}  — missing (build will continue, feature disabled)")
    if not ENTRY_POINT.exists():
        ERR(f"Entry point not found: {ENTRY_POINT}")
        sys.exit(1)
    OK(f"Entry point: {ENTRY_POINT.name}")


def check_playwright():
    # ── PyInstaller version check ──────────────────────────────────────────
    HEAD("Checking PyInstaller version")
    try:
        import PyInstaller
        pyi_ver = tuple(int(x) for x in PyInstaller.__version__.split(".")[:2])
        if pyi_ver < PYINSTALLER_MIN:
            WARN(f"PyInstaller {PyInstaller.__version__} is too old for Python 3.13.")
            WARN(f"Python DLL loading will fail at runtime.")
            INFO(f"Run: pip install --upgrade 'PyInstaller>={".".join(str(x) for x in PYINSTALLER_MIN)}'")
            if input("  Upgrade now? [Y/n] ").strip().lower() not in ("n", "no"):
                subprocess.run([sys.executable, "-m", "pip", "install",
                                f"PyInstaller>={'.'.join(str(x) for x in PYINSTALLER_MIN)}"],
                               check=True)
                OK("PyInstaller upgraded — restart build")
                sys.exit(0)
        else:
            OK(f"PyInstaller {PyInstaller.__version__} — OK")
    except ImportError:
        WARN("PyInstaller not installed yet — will be installed via --install-deps")

    HEAD("Checking Playwright (optional)")
    try:
        import playwright
        OK("playwright installed — scraper will work out of the box")
        # Check if Chromium is installed
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
            OK("Chromium browser present")
        except Exception:
            WARN("Playwright installed but Chromium not found.")
            INFO("Run: playwright install chromium")
    except ImportError:
        WARN("Playwright not installed — scraper will be disabled in the exe.")
        INFO("Users can enable it post-install: pip install playwright && playwright install chromium")


# ════════════════════════════════════════════════════════════════════════════
# 2. Spec file generation
# ════════════════════════════════════════════════════════════════════════════

def _collect_data_files():
    """Return list of (src, dest_in_bundle) tuples for --add-data."""
    data = []

    # Bundle all project .py modules as data (PyInstaller also compiles them,
    # but having them as data means they're accessible via __file__ too)
    for name in REQUIRED_MODULES:
        p = ROOT / name
        if p.exists():
            data.append((str(p), "."))

    # Any .txt / README at root
    for name in ("requirements.txt", "README.md"):
        p = ROOT / name
        if p.exists():
            data.append((str(p), "."))

    return data


def generate_spec(onefile=False, no_upx=False):
    HEAD("Generating PyInstaller spec file")

    data_list = _collect_data_files()
    # Format as one tuple per line, 4-space indent (spec file is at col 0)
    data_lines = "\n    ".join(
        f"(r'{src}', r'{dst}')," for src, dst in data_list
    )

    icon_line = f"    icon=r'{ICON_FILE}'," if ICON_FILE.exists() else "    # icon=None,"

    hidden_imports = [
        # PyQt6 essentials
        "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets",
        "PyQt6.QtNetwork", "PyQt6.QtSvg", "PyQt6.QtXml",
        # SQLite / DB
        "sqlite3", "_sqlite3",
        # Networking / scraping
        "requests", "requests.adapters", "requests.auth",
        "urllib3", "urllib3.util", "certifi",
        "bs4", "lxml", "lxml.etree", "lxml.html",
        # Crypto
        "cryptography", "cryptography.hazmat",
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        # Image handling
        "PIL", "PIL.Image", "PIL.ImageFile", "PIL.ImageOps",
        # Project modules
        "database", "db_mgmt_enhanced",
        "scraper", "scraper_extended",
        "abdl_logger", "abdl_sites",
        "image_cache", "thumbnail_cache",
        # Optional — graceful if absent
        "playwright",
        "playwright.sync_api",
    ]

    excludes = [
        # Things we definitely don't need — cuts exe size significantly
        "tkinter", "turtle", "test", "unittest",
        "email", "html", "xml.etree.ElementTree",
        "PyQt6.QtWebEngine", "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtMultimedia", "PyQt6.QtBluetooth",
        "IPython", "jupyter", "notebook",
        "matplotlib", "numpy", "pandas",
        "scipy", "sklearn",
    ]

    hidimps_str  = "\n    ".join(f'"{h}",' for h in hidden_imports)
    excludes_str = "\n    ".join(f'"{e}",' for e in excludes)

    # Runtime hook for playwright graceful fallback
    hook_file = ROOT / "runtime_hook_playwright.py"
    # Use forward slashes — PyInstaller spec is Python so backslash escaping
    # can cause issues on Windows.
    if hook_file.exists():
        hook_path = hook_file.as_posix()
        runtime_hooks_str = f"[r'{hook_path}'],"
    else:
        runtime_hooks_str = "[],"

    _upx = "False" if no_upx else "True"

    # Version info file (written by write_version_info())
    ver_info = ROOT / "version_info.txt"
    version_str = f"r'{ver_info.as_posix()}'" if ver_info.exists() else "None"

    if onefile:
        exe_block = (
f"exe = EXE(\n"
f"    pyz,\n"
f"    a.scripts,\n"
f"    a.binaries,\n"
f"    a.datas,\n"
f"    name='{APP_NAME}',\n"
f"    debug=False,\n"
f"    bootloader_ignore_signals=False,\n"
f"    strip=False,\n"
f"    upx={_upx},\n"
f"    upx_exclude=[],\n"
f"    runtime_tmpdir=None,\n"
f"    console=False,\n"
f"    disable_windowed_traceback=False,\n"
f"{icon_line}\n"
f"    version={version_str},\n"
f")\n"
        )
    else:
        exe_block = (
f"exe = EXE(\n"
f"    pyz,\n"
f"    a.scripts,\n"
f"    [],\n"
f"    name='{APP_NAME}',\n"
f"    debug=False,\n"
f"    bootloader_ignore_signals=False,\n"
f"    strip=False,\n"
f"    upx={_upx},\n"
f"    upx_exclude=[],\n"
f"    console=False,\n"
f"    disable_windowed_traceback=False,\n"
f"{icon_line}\n"
f")\n"
f"\n"
f"coll = COLLECT(\n"
f"    exe,\n"
f"    a.binaries,\n"
f"    a.datas,\n"
f"    strip=False,\n"
f"    upx={_upx},\n"
f"    upx_exclude=[],\n"
f"    name='{APP_NAME}',\n"
f")\n"
        )

    # Build spec at column 0 — no leading whitespace anywhere.
    # Do NOT use textwrap.dedent with an f-string that interpolates
    # multi-line blocks; the varying indentation in the interpolated
    # strings defeats dedent's common-prefix detection.
    # Collect Python DLL explicitly — fixes "Failed to load Python DLL" on Python 3.13
    import glob, sys as _sys
    py_dlls = glob.glob(str(Path(_sys.executable).parent / "python3*.dll"))
    collect_binaries_val = repr([(dll, ".") for dll in py_dlls])

    spec_lines = [
        "# -*- mode: python ; coding: utf-8 -*-",
        "# Auto-generated by build.py — do not edit manually.",
        "# Regenerate with: python build.py --build",
        "",
        "from pathlib import Path",
        "import sys",
        "",
        "block_cipher = None",
        "",
        "a = Analysis(",
        f"    [r'{ENTRY_POINT}'],",
        f"    pathex=[r'{ROOT}'],",
        f"    binaries={collect_binaries_val},",
        "    datas=[",
        f"    {data_lines}",
        "    ],",
        "    hiddenimports=[",
        f"    {hidimps_str}",
        "    ],",
        "    hookspath=[],",
        "    hooksconfig={},",
        f"    runtime_hooks={runtime_hooks_str}",
        "    excludes=[",
        f"    {excludes_str}",
        "    ],",
        "    win_no_prefer_redirects=False,",
        "    win_private_assemblies=False,",
        "    cipher=block_cipher,",
        "    noarchive=False,",
        ")",
        "",
        "pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)",
        "",
        exe_block,
    ]

    spec_content = "\n".join(spec_lines)

    SPEC.write_text(spec_content, encoding="utf-8")
    OK(f"Spec written: {SPEC}")
    return SPEC


# ════════════════════════════════════════════════════════════════════════════
# 3. Version info file (Windows exe metadata)
# ════════════════════════════════════════════════════════════════════════════

def write_version_info():
    ver_file = ROOT / "version_info.txt"
    # Parse "2.0" → (2, 0, 0, 0)
    parts = APP_VERSION.split(".")
    v = tuple(int(x) for x in parts) + (0, 0)
    v = v[:4]
    ver_file.write_text(textwrap.dedent(f"""\
        VSVersionInfo(
          ffi=FixedFileInfo(
            filevers={v},
            prodvers={v},
            mask=0x3f,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0)
          ),
          kids=[
            StringFileInfo([
              StringTable(
                '040904B0',
                [StringStruct('CompanyName', 'CrinkleDen'),
                 StringStruct('FileDescription', 'CrinkleDen'),
                 StringStruct('FileVersion', '{APP_VERSION}'),
                 StringStruct('InternalName', '{APP_NAME}'),
                 StringStruct('LegalCopyright', ''),
                 StringStruct('OriginalFilename', '{APP_NAME}.exe'),
                 StringStruct('ProductName', 'CrinkleDen'),
                 StringStruct('ProductVersion', '{APP_VERSION}')]
              )
            ]),
            VarFileInfo([VarStruct('Translation', [1033, 1200])])
          ]
        )
    """), encoding="utf-8")
    OK(f"Version info written: {ver_file.name}")


# ════════════════════════════════════════════════════════════════════════════
# 4. Run PyInstaller
# ════════════════════════════════════════════════════════════════════════════

def run_pyinstaller(spec_path, onefile=False):
    HEAD("Running PyInstaller")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        f"--distpath={DIST}",
        f"--workpath={BUILD}",
        str(spec_path),
    ]

    INFO("Command: " + " ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        ERR("PyInstaller failed — see output above.")
        sys.exit(1)

    OK("PyInstaller completed successfully.")


# ════════════════════════════════════════════════════════════════════════════
# 5. Post-build: copy extra runtime files into dist
# ════════════════════════════════════════════════════════════════════════════

def post_build(onefile=False):
    HEAD("Post-build: copying runtime files")

    if onefile:
        dist_dir = DIST
        exe_path = DIST / f"{APP_NAME}.exe"
    else:
        dist_dir = DIST / APP_NAME
        exe_path = dist_dir / f"{APP_NAME}.exe"

    if not dist_dir.exists():
        ERR(f"Expected dist dir not found: {dist_dir}")
        sys.exit(1)

    # Write a minimal launcher batch file (onedir only)
    if not onefile:
        bat = dist_dir / "Run CrinkleDen.bat"
        bat.write_text(
            "@echo off\r\n"
            ":: CrinkleDen launcher — sets correct DLL search path for Python 3.13\r\n"
            "setlocal\r\n"
            f"set PATH=%~dp0_internal;%~dp0;%PATH%\r\n"
            f"start \"\" \"%~dp0{APP_NAME}.exe\"\r\n"
            "endlocal\r\n",
            encoding="utf-8"
        )
        OK(f"Launcher bat: {bat.name}")

        # Write a VBScript silent launcher (no cmd window flash)
    vbs = dist_dir / "CrinkleDen_Silent.vbs"
    vbs.write_text(
        'Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'WshShell.Run chr(34) & "%~dp0{APP_NAME}.exe" & chr(34), 1, False\r\n',
        encoding="utf-8"
    )

    # Copy README if present
    for name in ("README.md", "requirements.txt"):
        src_file = ROOT / name
        if src_file.exists():
            shutil.copy2(src_file, dist_dir / name)
            OK(f"Copied {name}")

    # Write a post-install instructions file
    notes = dist_dir / "INSTALL_NOTES.txt" if not onefile else DIST / "INSTALL_NOTES.txt"
    notes.write_text(textwrap.dedent(f"""\
        CrinkleDen — CDN v{APP_VERSION}
        ================================================

        TO RUN
        ------
        {"Double-click CrinkleDen.exe" if onefile else "Double-click  Run CrinkleDen.bat  or  CrinkleDen.exe"}

        If you see "Failed to load Python DLL":
          Run  Run CrinkleDen.bat  instead of the .exe directly.
          The .bat sets the correct DLL search path for Python 3.13.

        FIRST-TIME SETUP
        ----------------
        The app creates these in the same folder as the .exe:
          abdl_catalog.db   — your product database
          thumbnails/       — pre-generated image thumbnails (fast catalog)
          cache/            — full-size image cache
          errors.txt        — scraper error log
          timeouts.txt      — scraper timeout log

        ENABLE SCRAPER (optional)
        -------------------------
        The scraper requires a Chromium browser. Install once:
          1. Open Command Prompt in this folder
          2. pip install playwright
          3. playwright install chromium

        The app shows a prompt with instructions if Playwright is missing.

        NOTES
        -----
        - Database: abdl_catalog.db — back it up by copying this file.
        - Thumbnails/cache folders: keep alongside the exe.
        - To move the app, move the entire {"CrinkleDen\\" if not onefile else ""}folder.

        SUPPORT
        -------
        Send errors.txt + timeouts.txt to the developer for debugging.
    """), encoding="utf-8")
    OK(f"Install notes: {notes.name}")

    return exe_path, dist_dir


# ════════════════════════════════════════════════════════════════════════════
# 6. Size report
# ════════════════════════════════════════════════════════════════════════════

def size_report(dist_dir, onefile=False):
    HEAD("Build size report")

    if onefile:
        exe = dist_dir / f"{APP_NAME}.exe"
        if exe.exists():
            mb = exe.stat().st_size / 1024 / 1024
            OK(f"{exe.name}  —  {mb:.1f} MB")
    else:
        total = sum(f.stat().st_size for f in dist_dir.rglob("*") if f.is_file())
        mb = total / 1024 / 1024
        exe = dist_dir / f"{APP_NAME}.exe"
        exe_mb = exe.stat().st_size / 1024 / 1024 if exe.exists() else 0
        OK(f"Total folder: {mb:.1f} MB  ({total:,} bytes)")
        OK(f"Launcher exe: {exe_mb:.1f} MB")
        OK(f"Output folder: {dist_dir}")

    if onefile:
        WARN("Single-file exe: first launch may take 3–10 seconds while extracting to temp dir.")
        INFO("Subsequent launches are faster.")
    else:
        INFO("Onedir build: fast startup, but user must keep the folder structure intact.")
        INFO("To share: zip up the entire dist\\ folder.")


# ════════════════════════════════════════════════════════════════════════════
# 7. Clean
# ════════════════════════════════════════════════════════════════════════════

def clean():
    HEAD("Cleaning build artefacts")
    for path in (BUILD, DIST, SPEC, ROOT / "version_info.txt"):
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
                OK(f"Removed dir: {path.name}")
            else:
                path.unlink()
                OK(f"Removed file: {path.name}")
        else:
            INFO(f"Not found (skip): {path.name}")
    OK("Clean complete.")


# ════════════════════════════════════════════════════════════════════════════
# 8. Install-deps shortcut
# ════════════════════════════════════════════════════════════════════════════

def install_deps():
    HEAD("Installing all required packages")

    for pkg in REQUIRED_PACKAGES:
        pkg = pkg.strip()
        if not pkg:
            continue
        INFO(f"pip install {pkg}")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "--upgrade", pkg
        ])
        OK(f"Installed/updated: {pkg}")

    print()
    OK("All packages installed.")
    INFO("PyInstaller 6.11+ is required for Python 3.13 — DLL loading is fixed.")
    INFO("Run  python build.py --build  to build the exe.")


# ════════════════════════════════════════════════════════════════════════════
# 9. Main
# ════════════════════════════════════════════════════════════════════════════

def _make_icon():
    """Generate icon.ico if absent or if make_icon.py is newer."""
    if ICON_FILE.exists():
        OK(f"icon.ico exists ({ICON_FILE.stat().st_size // 1024} KB) — skipping generation")
        return
    make_icon_script = ROOT / "make_icon.py"
    if not make_icon_script.exists():
        WARN("make_icon.py not found — building without icon")
        return
    HEAD("Generating icon.ico")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("make_icon", make_icon_script)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.make_icon()
    except Exception as e:
        WARN(f"Could not generate icon: {e} — building without icon")


def main():
    parser = argparse.ArgumentParser(
        prog="build.py",
        description="Build CrinkleDen into a standalone Windows .exe",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python build.py --build              # onedir (recommended)
              python build.py --build --onefile    # single .exe
              python build.py --check              # verify deps without building
              python build.py --install-deps       # pip install everything
              python build.py --clean              # wipe build artefacts
        """),
    )
    parser.add_argument("--build",        action="store_true", help="Build the exe")
    parser.add_argument("--onefile",      action="store_true", help="Single .exe (slower startup)")
    parser.add_argument("--onedir",       action="store_true", help="Folder build (default, faster startup)")
    parser.add_argument("--check",        action="store_true", help="Check deps only, no build")
    parser.add_argument("--install-deps", action="store_true", dest="install_deps", help="pip install all deps")
    parser.add_argument("--clean",        action="store_true", help="Remove build artefacts")
    parser.add_argument("--no-upx",       action="store_true", dest="no_upx", help="Skip UPX compression (faster build)")
    args = parser.parse_args()

    if not any([args.build, args.check, args.install_deps, args.clean]):
        parser.print_help()
        sys.exit(0)

    print(_c("1;96", f"\n  CrinkleDen Build System v{APP_VERSION}"))
    print(_c("96",   f"  Platform: {platform.system()} {platform.machine()}\n"))

    if args.clean:
        clean()
        return

    if args.install_deps:
        install_deps()
        return

    if args.check or args.build:
        check_python()
        check_dependencies(install_missing=False)
        check_source_files()
        check_playwright()

    if args.check:
        print()
        OK("All checks passed — ready to build.")
        INFO("Run: python build.py --build")
        return

    if args.build:
        if platform.system() != "Windows":
            WARN("Building on non-Windows host. The output exe will target your current OS.")
            WARN("For a Windows .exe, run this script on Windows.")

        onefile = args.onefile and not args.onedir

        # Ensure deps installed
        check_dependencies(install_missing=True)

        # Generate icon.ico if not already present
        _make_icon()

        write_version_info()

        spec = generate_spec(onefile=onefile, no_upx=args.no_upx)
        run_pyinstaller(spec, onefile=onefile)

        exe_path, dist_dir = post_build(onefile=onefile)
        size_report(dist_dir if not onefile else DIST, onefile=onefile)

        print()
        HEAD("Build complete")
        if onefile:
            OK(f"Output: {DIST / f'{APP_NAME}.exe'}")
        else:
            OK(f"Output folder: {DIST / APP_NAME}")
            INFO(f"Zip and share the entire  dist\\{APP_NAME}\\  folder.")
        print()


if __name__ == "__main__":
    main()
