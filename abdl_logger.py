"""
abdl_logger.py — CrinkleDen debug logger
===================================================
Writes two log files alongside the project:

    errors.txt   — every exception, bad status, and warning from scrapers + UI
    timeouts.txt — every page/network timeout, with the URL that timed out

Usage
-----
    from abdl_logger import log_error, log_timeout, get_log_paths

    log_error("MySite", "https://example.com/page", "Connection refused")
    log_timeout("MySite", "https://example.com/page/2", attempt=2)

    # Get paths to share with developer
    paths = get_log_paths()   # {"errors": Path(...), "timeouts": Path(...)}

Wire-in via scraper_extended.patch_logger()
-------------------------------------------
Call patch_logger() once at startup (done automatically by _run_startup_hooks
in ui.py).  It monkey-patches scraper.py's internal get_page / fetch_json /
_worker_scrape so every timeout and error is captured without editing scraper.py.
"""

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

# ── Log file locations ────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
ERRORS_LOG   = _HERE / "errors.txt"
TIMEOUTS_LOG = _HERE / "timeouts.txt"

_lock = threading.Lock()

# ── Header written once per session ───────────────────────────────────────────
_SESSION_HEADER = (
    "=" * 72 + "\n"
    + "  CrinkleDen — {kind} Log\n"
    + "  Session started: {ts}\n"
    + "  Python: {pyver}   Platform: {plat}\n"
    + "=" * 72 + "\n\n"
)

_sessions_opened = set()   # set of str paths already written this process


def _open_session(path: Path, kind: str):
    """Write a session header the first time we write to a log file."""
    if str(path) in _sessions_opened:
        return
    _sessions_opened.add(str(path))
    header = _SESSION_HEADER.format(
        kind=kind,
        ts=datetime.now().strftime("%Y-%m-%d  %H:%M:%S"),
        pyver=sys.version.split()[0],
        plat=sys.platform,
    )
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(header)


# ── Public API ────────────────────────────────────────────────────────────────

def log_error(
    site,           # str: human-readable site name (e.g. "Tykables")
    url,            # str: the URL being fetched when the error occurred
    message,        # str: short description
    exc=None,       # optional Exception — full traceback will be appended
    context="",     # str: optional extra context (product name, page number, etc.)
):
    """
    Record any error to errors.txt.

    Parameters
    ----------
    site    : human-readable site name (e.g. "Tykables")
    url     : the URL being fetched when the error occurred
    message : short description
    exc     : optional exception object — full traceback will be appended
    context : optional extra context string (e.g. product name, page number)
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"[{ts}]  SITE={site!r}",
        f"  URL    : {url}",
        f"  ERROR  : {message}",
    ]
    if context:
        lines.append(f"  CONTEXT: {context}")
    if exc is not None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        lines.append("  TRACEBACK:")
        for tl in tb.splitlines():
            lines.append(f"    {tl}")
    lines.append("")   # blank separator

    with _lock:
        _open_session(ERRORS_LOG, "Errors")
        with open(ERRORS_LOG, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


def log_timeout(
    site,           # str: human-readable site name
    url,            # str: URL that timed out
    attempt=1,      # int: which retry attempt (1 = first try)
    timeout_ms=None,# int|None: the timeout threshold in ms, if known
):
    """
    Record a page/network timeout to timeouts.txt.

    Parameters
    ----------
    site       : human-readable site name
    url        : URL that timed out
    attempt    : which retry attempt (1 = first try)
    timeout_ms : the timeout threshold in ms, if known
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    limit_str = f"  LIMIT  : {timeout_ms} ms\n" if timeout_ms else ""
    entry = (
        f"[{ts}]  SITE={site!r}\n"
        f"  URL    : {url}\n"
        f"  ATTEMPT: {attempt}\n"
        f"{limit_str}"
        f"\n"
    )
    with _lock:
        _open_session(TIMEOUTS_LOG, "Timeouts")
        with open(TIMEOUTS_LOG, "a", encoding="utf-8") as fh:
            fh.write(entry)


def log_scrape_result(site: str, status: str, found: int, error: str = ""):
    """
    Write a one-line scrape summary to errors.txt when status != SUCCESS.
    Silent on success to keep the log clean.
    """
    if status.upper() in ("SUCCESS", "SKIP", "SKIPPED"):
        return
    log_error(site, "", f"Scrape ended with status={status!r}  found={found}",
              context=error or "")


def get_log_paths() -> dict[str, Path]:
    """Return the absolute paths of both log files."""
    return {"errors": ERRORS_LOG, "timeouts": TIMEOUTS_LOG}


def clear_logs():
    """Truncate both log files (called from the DB → Advanced tab)."""
    global _sessions_opened
    with _lock:
        _sessions_opened.discard(str(ERRORS_LOG))
        _sessions_opened.discard(str(TIMEOUTS_LOG))
        for p in (ERRORS_LOG, TIMEOUTS_LOG):
            if p.exists():
                p.unlink()


def get_log_sizes() -> dict[str, str]:
    """Return human-readable sizes for the UI status display."""
    def _fmt(p: Path) -> str:
        if not p.exists():
            return "0 B"
        b = p.stat().st_size
        return f"{b/1024:.1f} KB" if b >= 1024 else f"{b} B"
    return {"errors": _fmt(ERRORS_LOG), "timeouts": _fmt(TIMEOUTS_LOG)}


def get_recent_errors(n: int = 50) -> list[str]:
    """Return the last n non-blank lines from errors.txt (for the UI log viewer)."""
    if not ERRORS_LOG.exists():
        return []
    lines = ERRORS_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    return [l for l in lines if l.strip()][-n:]


def get_recent_timeouts(n: int = 50) -> list[str]:
    """Return the last n non-blank lines from timeouts.txt."""
    if not TIMEOUTS_LOG.exists():
        return []
    lines = TIMEOUTS_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    return [l for l in lines if l.strip()][-n:]


# ── Monkey-patch helpers (called by scraper_extended.patch_logger) ────────────

def _patch_scraper_module():
    """
    Wrap scraper.py's internal functions to capture timeouts and errors
    without modifying scraper.py.  Safe to call multiple times.
    """
    try:
        import scraper as _sc
    except ImportError:
        return  # scraper not available, nothing to patch

    if getattr(_sc, "_abdl_logger_patched", False):
        return   # already patched this session

    # ── Patch _ThreadBrowser.get_page ─────────────────────────────────────
    try:
        from playwright.sync_api import TimeoutError as _PWTimeout
    except ImportError:
        _PWTimeout = None

    _orig_get_page = _sc._ThreadBrowser.get_page

    def _patched_get_page(self, url, wait="domcontentloaded", retries=2):
        site_name = getattr(self, "_site_name", "unknown")
        for attempt in range(retries + 1):
            try:
                self.page.goto(url, wait_until=wait, timeout=12_000)
                import time, random
                time.sleep(random.uniform(0.2, 0.6))
                from bs4 import BeautifulSoup
                return BeautifulSoup(self.page.content(), "html.parser")
            except Exception as e:
                is_timeout = (_PWTimeout and isinstance(e, _PWTimeout)) or \
                             "timeout" in str(e).lower()
                if is_timeout:
                    log_timeout(site_name, url, attempt=attempt + 1, timeout_ms=12_000)
                    if attempt == retries:
                        return None
                    import time; time.sleep(2)
                else:
                    log_error(site_name, url, str(e), exc=e)
                    return None

    _sc._ThreadBrowser.get_page = _patched_get_page

    # ── Patch _worker_scrape (the per-site thread function) ───────────────
    _orig_worker = _sc._worker_scrape

    def _patched_worker(site, pcb=None, lcb=None, force=False):
        result = _orig_worker(site, pcb=pcb, lcb=lcb, force=force)
        if isinstance(result, dict):
            log_scrape_result(
                result.get("site", site.get("name", "?")),
                result.get("status", "?"),
                result.get("found", 0),
                result.get("error", ""),
            )
        return result

    _sc._worker_scrape = _patched_worker

    _sc._abdl_logger_patched = True
    print("[abdl_logger] Scraper patched — writing to errors.txt / timeouts.txt")
