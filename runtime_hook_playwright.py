# runtime_hook_playwright.py
# PyInstaller runtime hook — placed in project root, referenced by build.py
#
# When the bundled exe starts up, this code runs BEFORE ui.py.
# It sets environment variables so Playwright looks for Chromium in a
# "browsers" subfolder next to the exe, and sets the SCRAPE_AVAILABLE
# flag accordingly.

import os
import sys
from pathlib import Path


def _find_exe_dir():
    """Return the directory the exe is running from."""
    if getattr(sys, "frozen", False):
        # Running as PyInstaller bundle
        return Path(sys.executable).parent
    return Path(__file__).parent


_exe_dir = _find_exe_dir()

# Tell Playwright to look for browsers next to the exe.
# Users can run: playwright install chromium
# and the browser will be installed to the system default location.
# We also support a "browsers" subfolder next to the exe for portability.
_local_browsers = _exe_dir / "browsers"
if _local_browsers.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_local_browsers))

# Pre-flight: if playwright is importable but Chromium is missing,
# set a flag the app can check to show an install dialog.
try:
    from playwright.sync_api import sync_playwright as _swp
    with _swp() as _p:
        try:
            _b = _p.chromium.launch(headless=True)
            _b.close()
            os.environ["ABDL_PLAYWRIGHT_READY"] = "1"
        except Exception:
            os.environ["ABDL_PLAYWRIGHT_READY"] = "0"
            os.environ["ABDL_PLAYWRIGHT_REASON"] = "Chromium not installed"
except ImportError:
    os.environ["ABDL_PLAYWRIGHT_READY"] = "0"
    os.environ["ABDL_PLAYWRIGHT_REASON"] = "playwright package not installed"
except Exception as _e:
    os.environ["ABDL_PLAYWRIGHT_READY"] = "0"
    os.environ["ABDL_PLAYWRIGHT_REASON"] = str(_e)
