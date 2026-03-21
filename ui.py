"""
CrinkleDen — ui.py
Pure PyQt6 native UI. No WebEngine required.  pip install PyQt6

Bug fixes in this version:
  - Thread: wait() + deleteLater() + no double-connect + _seed uses _start_worker
  - Debounce: search (300ms), price slider (400ms), qty spinner (500ms)
  - _start_worker: notifies user if already busy instead of silently dropping
  - _on_done: thread.quit() + thread.wait(3000) to prevent dangling threads
  - All DB calls stay on worker thread; UI only reads results
"""

import sys, json, os
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Ensure the folder containing ui.py is on the module search path so that
# downloader.py, talker.py, database.py etc. are always importable regardless
# of the working directory Python was launched from.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    import database as db
    DB_OK = True
    # ── Version guard: if database.py is the old pre-v3 version it won't have
    #    DB_VERSION or the library/download functions → show a clear message. ──
    _db_ver = getattr(db, "DB_VERSION", None)
    _required_fns = ("add_library_image", "save_site_credentials",
                     "get_library_images", "create_download_job")
    _missing = [f for f in _required_fns if not hasattr(db, f)]
    if _missing or _db_ver is None:
        import tkinter, tkinter.messagebox
        tkinter.Tk().withdraw()
        tkinter.messagebox.showerror(
            "CrinkleDen — Wrong database.py",
            f"Your database.py is an OLD version (v{_db_ver or '?'}).\n\n"
            f"Missing functions: {', '.join(_missing) or 'none'}\n\n"
            "Please copy the NEW database.py (v3.0) from the release into\n"
            r"I:\abdl\database.py"
            "\nthen restart the app.")
        sys.exit(1)
except Exception as _e:
    print(f"[WARN] database: {_e}")
    DB_OK = False

try:
    from scraper import (seed_demo_data, scrape_all, scrape_site_by_id,
                         SCRAPE_AVAILABLE, PLAYWRIGHT_AVAILABLE, MAX_CONCURRENT)
    _SCRAPER_ERR = ""
except Exception as _e:
    _SCRAPER_ERR = str(_e)
    print(f"[WARN] scraper import failed: {_e}")
    SCRAPE_AVAILABLE = PLAYWRIGHT_AVAILABLE = False
    MAX_CONCURRENT = 4
    def seed_demo_data(pcb=None, force=False): return 0
    def scrape_all(**kw): return []
    def scrape_site_by_id(sid, **kw): return {}

# Separate playwright detection — runs even if scraper.py failed to import.
# This distinguishes "playwright not installed" from "scraper.py has a bug".
_PLAYWRIGHT_IMPORT_OK = False
_PLAYWRIGHT_ERR       = ""
try:
    from playwright.sync_api import sync_playwright as _pw_check
    _PLAYWRIGHT_IMPORT_OK = True
except ImportError as _pwe:
    _PLAYWRIGHT_ERR = str(_pwe)
except Exception as _pwe:
    _PLAYWRIGHT_ERR = str(_pwe)


from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QTextEdit, QPlainTextEdit, QDialog, QFrame, QSplitter, QProgressBar,
    QAbstractItemView, QSlider, QSpinBox, QDoubleSpinBox, QFileDialog,
    QMessageBox, QListWidget, QListWidgetItem, QScrollArea, QFormLayout,
    QSizePolicy, QLayout, QLayoutItem, QInputDialog,
)
from PyQt6.QtCore  import (Qt, QThread, QObject, pyqtSignal, pyqtSlot,
                            QTimer, QUrl, QProcess, QBuffer,
                            QRect, QPoint, QSize)
from PyQt6.QtGui   import QColor, QPalette, QDesktopServices, QPixmap, QImage

# ── Optional modules (in same folder as ui.py) ────────────────────────────────
try:
    from downloader import SITES as DL_SITES, make_client as dl_make_client
    from downloader import KemonoClient as _KemonoClient
    _DL_OK = True
except ImportError:
    DL_SITES = {}; _DL_OK = False

try:
    from talker import transform as _talker_transform, available_modes as _talker_modes
    _TALKER_OK = True
except ImportError:
    _TALKER_OK = False

# ── Extension modules ─────────────────────────────────────────────────────

try:
    import db_mgmt_enhanced as _mgmt
    _MGMT_OK = True
except ImportError:
    _MGMT_OK = False

try:
    import scraper_extended as _scraper_ext
    _SCRAPER_EXT_OK = True
except ImportError:
    _SCRAPER_EXT_OK = False


try:
    from image_cache import get_cache as _get_img_cache
    _IMG_CACHE_OK = True
except ImportError:
    _IMG_CACHE_OK = False
    def _get_img_cache(*a, **kw): return None

try:
    from thumbnail_cache import get_thumb_cache as _get_thumb_cache
    _THUMB_CACHE_OK = True
except ImportError:
    _THUMB_CACHE_OK = False
    def _get_thumb_cache(*a, **kw): return None


# ── Palette ────────────────────────────────────────────────────────────────
C_DARK = {
    "bg":      "#07101f",
    "panel":   "#0c1a30",
    "panel2":  "#102040",
    "card":    "#152850",
    "border":  "#1e4080",
    "amber":   "#f5a623",
    "teal":    "#3ecfbf",
    "pink":    "#ff79b0",
    "lavender":"#a78bfa",
    "mint":    "#34d399",
    "white":   "#e4eef8",
    "muted":   "#4a6a90",
    "red":     "#f77171",
    "yellow":  "#fbbf24",
    "gold":    "#f59e0b",
    "sky":     "#60a8fa",
    "green":   "#4add80",
    "peach":   "#ffb380",
    "abdl_c":  "#ff79b0",
    "med_c":   "#60a8fa",
    "both_c":  "#3ecfbf",
    "reg_c":   "#a78bfa",
    "panel2_alias": "#102040",
}

C_LIGHT = {
    "bg":      "#f0f4f8",
    "panel":   "#ffffff",
    "panel2":  "#e8eef5",
    "card":    "#dde6f0",
    "border":  "#b0c4de",
    "amber":   "#d97706",
    "teal":    "#0d9488",
    "pink":    "#db2777",
    "lavender":"#7c3aed",
    "mint":    "#059669",
    "white":   "#1e293b",
    "muted":   "#64748b",
    "red":     "#dc2626",
    "yellow":  "#d97706",
    "gold":    "#b45309",
    "sky":     "#2563eb",
    "green":   "#16a34a",
    "peach":   "#ea580c",
    "abdl_c":  "#db2777",
    "med_c":   "#2563eb",
    "both_c":  "#0d9488",
    "reg_c":   "#7c3aed",
    "panel2_alias": "#e8eef5",
}

# Active palette — starts dark, can be toggled
_SETTINGS_PATH = _HERE / "settings.json"
def _load_settings() -> dict:
    try:
        return json.loads(_SETTINGS_PATH.read_text())
    except Exception:
        return {}
def _save_settings(d: dict):
    try:
        _SETTINGS_PATH.write_text(json.dumps(d, indent=2))
    except Exception:
        pass

_settings = _load_settings()
C = C_LIGHT if _settings.get("theme") == "light" else C_DARK
_CURRENT_THEME = _settings.get("theme", "dark")

APP_VERSION     = "2.0"
GITHUB_RELEASES = "https://api.github.com/repos/crinkleden/crinkleden/releases/latest"

BASE_SS = (
    # ── CrinkleDen Base Stylesheet ──────────────────────────────────────────
    f"QMainWindow,QDialog{{background:{C['bg']};}}"
    f"QWidget{{background:{C['bg']};color:{C['white']};font-family:'Segoe UI','Ubuntu','Helvetica Neue',sans-serif;font-size:13px;}}"
    # Tab bar — card catalog style
    f"QTabWidget::pane{{border:1px solid {C['border']};background:{C['panel']};border-radius:0px 6px 6px 6px;}}"
    f"QTabBar::tab{{background:{C['panel2']};color:{C['muted']};padding:8px 20px;border:1px solid {C['border']};border-bottom:none;border-radius:4px 4px 0 0;margin-right:3px;font-weight:600;font-size:12px;}}"
    f"QTabBar::tab:selected{{background:{C['panel']};color:{C['amber']};border-color:{C['amber']};}}"
    f"QTabBar::tab:hover{{background:{C['card']};color:{C['white']};}}"
    # Input fields
    f"QLineEdit{{background:{C['panel2']};border:1px solid {C['border']};border-radius:4px;color:{C['white']};padding:6px 10px;}}"
    f"QLineEdit:focus{{border-color:{C['amber']};background:{C['card']};}}"
    f"QComboBox{{background:{C['panel2']};border:1px solid {C['border']};border-radius:4px;color:{C['white']};padding:5px 10px;min-width:100px;}}"
    f"QComboBox::drop-down{{border:none;width:22px;background:transparent;}}"
    f"QComboBox QAbstractItemView{{background:{C['card']};color:{C['white']};selection-background-color:{C['border']};border:1px solid {C['border']};}}"
    f"QSpinBox,QDoubleSpinBox{{background:{C['panel2']};border:1px solid {C['border']};border-radius:4px;color:{C['white']};padding:4px 8px;}}"
    f"QSpinBox::up-button,QSpinBox::down-button,QDoubleSpinBox::up-button,QDoubleSpinBox::down-button{{background:{C['border']};width:18px;}}"
    # Checkboxes
    f"QCheckBox{{color:{C['white']};spacing:6px;}}"
    f"QCheckBox::indicator{{width:14px;height:14px;border:1px solid {C['border']};border-radius:3px;background:{C['panel2']};}}"
    f"QCheckBox::indicator:checked{{background:{C['amber']};border-color:{C['amber']};}}"
    # Tables
    f"QTableWidget{{background:{C['panel']};gridline-color:{C['border']};color:{C['white']};border:1px solid {C['border']};alternate-background-color:{C['panel2']};}}"
    f"QTableWidget::item{{padding:5px 8px;}}"
    f"QTableWidget::item:selected{{background:{C['border']};color:{C['amber']};}}"
    f"QHeaderView::section{{background:{C['panel2']};color:{C['amber']};padding:6px 10px;border:none;border-right:1px solid {C['border']};border-bottom:1px solid {C['border']};font-weight:700;font-size:11px;letter-spacing:0.05em;}}"
    # Lists
    f"QListWidget{{background:{C['panel']};color:{C['white']};border:1px solid {C['border']};}}"
    f"QListWidget::item{{padding:4px 8px;}}"
    f"QListWidget::item:selected{{background:{C['border']};color:{C['amber']};}}"
    f"QListWidget::item:hover{{background:{C['panel2']};}}"
    # Scrollbars — thin and clean
    f"QScrollBar:vertical{{background:{C['panel2']};width:8px;border-radius:4px;margin:0;}}"
    f"QScrollBar::handle:vertical{{background:{C['border']};border-radius:4px;min-height:24px;}}"
    f"QScrollBar::handle:vertical:hover{{background:{C['amber']};}}"
    f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
    f"QScrollBar:horizontal{{background:{C['panel2']};height:8px;border-radius:4px;margin:0;}}"
    f"QScrollBar::handle:horizontal{{background:{C['border']};border-radius:4px;}}"
    f"QScrollBar::handle:horizontal:hover{{background:{C['amber']};}}"
    f"QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{{width:0;}}"
    # Text areas
    f"QTextEdit,QPlainTextEdit{{background:{C['panel2']};border:1px solid {C['border']};border-radius:4px;color:{C['teal']};font-family:'Consolas','Cascadia Code','Courier New',monospace;font-size:12px;padding:6px;}}"
    f"QTextEdit:focus,QPlainTextEdit:focus{{border-color:{C['amber']};}}"
    # Progress
    f"QProgressBar{{background:{C['panel2']};border:1px solid {C['border']};border-radius:3px;height:6px;text-align:center;}}"
    f"QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {C['amber']},stop:1 {C['teal']});border-radius:3px;}}"
    # Splitter
    f"QSplitter::handle{{background:{C['border']};width:2px;height:2px;}}"
    f"QFrame[frameShape='4']{{background:{C['border']};max-height:1px;}}"  # HLine
    # Tooltips
    f"QToolTip{{background:{C['card']};color:{C['white']};border:1px solid {C['amber']};padding:4px 8px;border-radius:4px;}}"
)


def _build_stylesheet() -> str:
    """Rebuild the full stylesheet using the current C palette (for theme toggle)."""
    return (
        f"QMainWindow,QDialog{{background:{C['bg']};}}"
        f"QWidget{{background:{C['bg']};color:{C['white']};font-family:'Segoe UI','Ubuntu','Helvetica Neue',sans-serif;font-size:13px;}}"
        f"QTabWidget::pane{{border:1px solid {C['border']};background:{C['panel']};border-radius:0px 6px 6px 6px;}}"
        f"QTabBar::tab{{background:{C['panel2']};color:{C['muted']};padding:8px 20px;border:1px solid {C['border']};border-bottom:none;border-radius:4px 4px 0 0;margin-right:3px;font-weight:600;font-size:12px;}}"
        f"QTabBar::tab:selected{{background:{C['panel']};color:{C['amber']};border-color:{C['amber']};}}"
        f"QTabBar::tab:hover{{background:{C['card']};color:{C['white']};}}"
        f"QLineEdit{{background:{C['panel2']};border:1px solid {C['border']};border-radius:4px;color:{C['white']};padding:6px 10px;}}"
        f"QLineEdit:focus{{border-color:{C['amber']};background:{C['card']};}}"
        f"QComboBox{{background:{C['panel2']};border:1px solid {C['border']};border-radius:4px;color:{C['white']};padding:5px 10px;min-width:100px;}}"
        f"QComboBox::drop-down{{border:none;width:22px;background:transparent;}}"
        f"QComboBox QAbstractItemView{{background:{C['card']};color:{C['white']};selection-background-color:{C['border']};border:1px solid {C['border']};}}"
        f"QSpinBox,QDoubleSpinBox{{background:{C['panel2']};border:1px solid {C['border']};border-radius:4px;color:{C['white']};padding:4px 8px;}}"
        f"QCheckBox{{color:{C['white']};spacing:6px;}}"
        f"QCheckBox::indicator{{width:14px;height:14px;border:1px solid {C['border']};border-radius:3px;background:{C['panel2']};}}"
        f"QCheckBox::indicator:checked{{background:{C['amber']};border-color:{C['amber']};}}"
        f"QTableWidget{{background:{C['panel']};gridline-color:{C['border']};color:{C['white']};border:1px solid {C['border']};alternate-background-color:{C['panel2']};}}"
        f"QHeaderView::section{{background:{C['panel2']};color:{C['amber']};border:1px solid {C['border']};padding:5px 8px;font-weight:600;}}"
        f"QPushButton{{background:{C['panel2']};color:{C['amber']};border:1px solid {C['amber']}55;border-radius:4px;padding:7px 18px;font-weight:600;}}"
        f"QPushButton:hover{{background:{C['card']};border-color:{C['amber']};}}"
        f"QPushButton:pressed{{background:{C['border']};}}"
        f"QPushButton:disabled{{color:{C['muted']};border-color:{C['border']};}}"
        f"QScrollBar:vertical{{background:{C['panel2']};width:8px;border-radius:4px;margin:0;}}"
        f"QScrollBar::handle:vertical{{background:{C['border']};border-radius:4px;min-height:30px;}}"
        f"QScrollBar::handle:vertical:hover{{background:{C['amber']};}}"
        f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        f"QTextEdit,QPlainTextEdit{{background:{C['panel2']};border:1px solid {C['border']};border-radius:4px;color:{C['teal']};font-family:'Consolas','Cascadia Code','Courier New',monospace;font-size:12px;padding:6px;}}"
        f"QProgressBar{{background:{C['panel2']};border:1px solid {C['border']};border-radius:3px;height:6px;}}"
        f"QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {C['amber']},stop:1 {C['teal']});border-radius:3px;}}"
        f"QToolTip{{background:{C['card']};color:{C['white']};border:1px solid {C['amber']};padding:4px 8px;border-radius:4px;}}"
    )



def _btn(text, color=None, flat=False, small=False, icon=None):
    b = QPushButton(text)
    fg  = color or C["amber"]
    bg  = "transparent" if flat else C["panel2"]
    bdr = "none"        if flat else f"1px solid {fg}55"
    pad = "5px 12px" if small else "7px 18px"
    fs  = "12px"     if small else "13px"
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:{bdr};"
        f"border-radius:4px;padding:{pad};font-size:{fs};font-weight:600;}}"
        f"QPushButton:hover{{background:{C['border']};color:{C['white']};border-color:{fg};}}"
        f"QPushButton:pressed{{background:{fg}22;color:{fg};}}"
        f"QPushButton:disabled{{color:{C['muted']};border-color:{C['muted']}44;}}")
    return b

def _label(text, color=None, bold=False, size=13):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color:{color or C['white']};font-size:{size}px;"
                      f"{'font-weight:bold;' if bold else ''}background:transparent;")
    return lbl

def _sep():
    f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{C['border']};background:{C['border']};max-height:1px;")
    return f

def _card():
    w = QWidget()
    w.setStyleSheet(f"background:{C['card']};border:1px solid {C['border']};border-radius:8px;")
    lay = QVBoxLayout(w); lay.setContentsMargins(14,12,14,12); lay.setSpacing(8)
    return w, lay

def _type_color(btype):
    return {"abdl":C["abdl_c"],"medical":C["med_c"],"both":C["both_c"]}.get(
        str(btype).lower(), C["white"])

# ── US State tax rates (state-level, 2024) ─────────────────────────────────
STATE_TAXES = [
    ("No Sales Tax (0%)",           0.000),
    ("Alabama (4.0%)",              0.040),
    ("Alaska (0.0%)",               0.000),
    ("Arizona (5.6%)",              0.056),
    ("Arkansas (6.5%)",             0.065),
    ("California (7.25%)",          0.0725),
    ("Colorado (2.9%)",             0.029),
    ("Connecticut (6.35%)",         0.0635),
    ("Delaware (0.0%)",             0.000),
    ("Florida (6.0%)",              0.060),
    ("Georgia (4.0%)",              0.040),
    ("Hawaii (4.0%)",               0.040),
    ("Idaho (6.0%)",                0.060),
    ("Illinois (6.25%)",            0.0625),
    ("Indiana (7.0%)",              0.070),
    ("Iowa (6.0%)",                 0.060),
    ("Kansas (6.5%)",               0.065),
    ("Kentucky (6.0%)",             0.060),
    ("Louisiana (4.45%)",           0.0445),
    ("Maine (5.5%)",                0.055),
    ("Maryland (6.0%)",             0.060),
    ("Massachusetts (6.25%)",       0.0625),
    ("Michigan (6.0%)",             0.060),
    ("Minnesota (6.875%)",          0.06875),
    ("Mississippi (7.0%)",          0.070),
    ("Missouri (4.225%)",           0.04225),
    ("Montana (0.0%)",              0.000),
    ("Nebraska (5.5%)",             0.055),
    ("Nevada (6.85%)",              0.0685),
    ("New Hampshire (0.0%)",        0.000),
    ("New Jersey (6.625%)",         0.06625),
    ("New Mexico (5.0%)",           0.050),
    ("New York (4.0%)",             0.040),
    ("North Carolina (4.75%)",      0.0475),
    ("North Dakota (5.0%)",         0.050),
    ("Ohio (5.75%)",                0.0575),
    ("Oklahoma (4.5%)",             0.045),
    ("Oregon (0.0%)",               0.000),
    ("Pennsylvania (6.0%)",         0.060),
    ("Rhode Island (7.0%)",         0.070),
    ("South Carolina (6.0%)",       0.060),
    ("South Dakota (4.5%)",         0.045),
    ("Tennessee (7.0%)",            0.070),
    ("Texas (6.25%)",               0.0625),
    ("Utah (4.85%)",                0.0485),
    ("Vermont (6.0%)",              0.060),
    ("Virginia (5.3%)",             0.053),
    ("Washington (6.5%)",           0.065),
    ("Washington DC (6.0%)",        0.060),
    ("West Virginia (6.0%)",        0.060),
    ("Wisconsin (5.0%)",            0.050),
    ("Wyoming (4.0%)",              0.040),
]

# ── Thread worker helpers ──────────────────────────────────────────────────

def _stop_thread(thread, timeout_ms=3000):
    """Cleanly stop a QThread: quit event loop, wait for finish, schedule deletion."""
    if thread is None:
        return
    try:
        thread.quit()
        if not thread.wait(timeout_ms):
            thread.terminate()
            thread.wait(1000)
    except RuntimeError:
        pass  # already deleted by Qt
    try:
        thread.deleteLater()
    except RuntimeError:
        pass


def _run_startup_hooks():
    """Called once after DB init to wire up extension modules."""
    # Debug logger — creates errors.txt / timeouts.txt session header
    try:
        from abdl_logger import log_error
        log_error("startup", "", "Session started.")
        # If scraper.py failed to import, log the real error immediately
        if _SCRAPER_ERR:
            log_error("startup", "scraper.py",
                      f"scraper import failed: {_SCRAPER_ERR}")
        if _PLAYWRIGHT_ERR:
            log_error("startup", "playwright",
                      f"playwright import failed: {_PLAYWRIGHT_ERR}")
    except ImportError:
        pass

    # Image cache (for catalog product thumbnails)
    if _IMG_CACHE_OK:
        try:
            _get_img_cache()
        except Exception as e:
            print(f"[image_cache] {e}")

    # Patch scraper profiles + image cache hook
    if _SCRAPER_EXT_OK:
        try:
            _scraper_ext.patch_scraper()
            _scraper_ext.add_extra_sites()
        except Exception as e:
            print(f"[scraper_ext] {e}")

class ScrapeWorker(QObject):
    progress = pyqtSignal(str)
    done     = pyqtSignal(str)

    def __init__(self, site_id=None, force=False):
        super().__init__()
        self.site_id = site_id
        self.force   = force

    @pyqtSlot()
    def run(self):
        results = []
        try:
            if self.site_id:
                results = [scrape_site_by_id(
                    self.site_id,
                    pcb=lambda m: self.progress.emit(str(m)),
                    lcb=lambda m: self.progress.emit(str(m)),
                    force=self.force)]
            else:
                results = scrape_all(
                    pcb=lambda m: self.progress.emit(str(m)),
                    lcb=lambda m: self.progress.emit(str(m)),
                    force=self.force)
        except Exception as e:
            self.progress.emit(f"[ERROR] {e}")
        self.done.emit(json.dumps(results, default=str))


class SeedWorker(QObject):
    progress = pyqtSignal(str)
    done     = pyqtSignal(str)   # returns json string like ScrapeWorker for _start_worker compat

    @pyqtSlot()
    def run(self):
        n = seed_demo_data(pcb=lambda m: self.progress.emit(str(m)), force=True)
        self.done.emit(json.dumps({"seeded": n}))


# ── Product detail dialog ──────────────────────────────────────────────────

class ProductDialog(QDialog):
    add_to_list = pyqtSignal(int)

    def __init__(self, product, parent=None):
        super().__init__(parent)
        p = product
        self._pid = p.get("id")
        self._product_image_url = p.get("image_url", "")  # fallback when product_images is empty
        self.setWindowTitle(p.get("name", "Product"))
        self.setMinimumSize(780, 580)
        self.setStyleSheet(BASE_SS)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        # ── Header ─────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.addWidget(_label(p.get("name", ""), C["pink"], bold=True, size=16))
        hdr.addStretch()
        btype = (p.get("brand_type") or "abdl").upper()
        tc    = _type_color(btype.lower())
        badge = _label(f"  {btype}  ", "")
        badge.setStyleSheet(
            f"color:{C['bg']};background:{tc};border-radius:10px;"
            f"padding:2px 8px;font-weight:bold;")
        hdr.addWidget(badge)
        root.addLayout(hdr)
        root.addWidget(_sep())

        # ── Main body: image panel left, details right ────────────────────
        body = QHBoxLayout(); body.setSpacing(16)

        # ── Left: image viewer ────────────────────────────────────────────
        img_col = QVBoxLayout(); img_col.setSpacing(6)

        # Primary image display (large)
        self._img_lbl = QLabel()
        self._img_lbl.setFixedSize(300, 300)
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet(
            f"background:{C['panel']};border:1px solid {C['border']};"
            f"border-radius:6px;color:{C['muted']};")
        self._img_lbl.setText("Loading…")
        img_col.addWidget(self._img_lbl)

        # Thumbnail strip (shown when product has multiple images)
        self._thumb_row = QScrollArea()
        self._thumb_row.setFixedHeight(64)
        self._thumb_row.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._thumb_row.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._thumb_row.setWidgetResizable(True)
        self._thumb_row.setStyleSheet("background:transparent;border:none;")
        self._thumb_inner = QWidget()
        self._thumb_layout = QHBoxLayout(self._thumb_inner)
        self._thumb_layout.setContentsMargins(0, 0, 0, 0)
        self._thumb_layout.setSpacing(4)
        self._thumb_layout.addStretch()
        self._thumb_row.setWidget(self._thumb_inner)
        self._thumb_row.setVisible(False)
        img_col.addWidget(self._thumb_row)

        # Download images button
        self._dl_img_btn = _btn("⬇ Download Images", C["sky"], small=True)
        self._dl_img_btn.setToolTip("Download all product images from the store")
        self._dl_img_btn.clicked.connect(self._download_images)
        img_col.addWidget(self._dl_img_btn)
        img_col.addStretch()
        body.addLayout(img_col)

        # ── Right: product details ────────────────────────────────────────
        detail_col = QVBoxLayout(); detail_col.setSpacing(6)

        # Price + brand
        pr = QHBoxLayout()
        price = p.get("display_price") or p.get("price_usd") or p.get("price")
        if price:
            pr.addWidget(_label(f"${price:.2f}", C["mint"], bold=True, size=22))
        pr.addSpacing(12)
        if p.get("brand_name"):
            pr.addWidget(_label(f"🏷 {p['brand_name']}", C["lavender"]))
        if p.get("category_name"):
            pr.addWidget(_label(
                f"  {p.get('category_icon', '')} {p['category_name']}", C["yellow"]))
        pr.addStretch()
        detail_col.addLayout(pr)

        # Flags row
        fl = QHBoxLayout()
        if p.get("discreet_shipping") or p.get("b_discreet"):
            b = _label("  📦 Discreet Shipping  ", "")
            b.setStyleSheet(
                f"background:{C['green']};color:{C['bg']};border-radius:10px;"
                f"padding:2px 10px;font-weight:bold;")
            fl.addWidget(b)
        if p.get("free_sample") or p.get("b_free_sample"):
            b = _label("  🎁 Free Sample  ", "")
            b.setStyleSheet(
                f"background:{C['mint']};color:{C['bg']};border-radius:10px;"
                f"padding:2px 10px;font-weight:bold;")
            fl.addWidget(b)
        fl.addWidget(_label(
            "● In Stock" if p.get("in_stock") else "● Out of Stock",
            C["mint"] if p.get("in_stock") else C["red"], bold=True))
        fl.addStretch()
        detail_col.addLayout(fl)

        # Sizes
        sizes_avail = [l for k, l in [
            ("size_xs","XS"),("size_s","S"),("size_m","M"),("size_l","L"),
            ("size_xl","XL"),("size_xxl","XXL"),("size_xxxl","XXXL")] if p.get(k)]
        if p.get("size_range"):
            detail_col.addWidget(_label(f"📏 {p['size_range']}", C["peach"]))
        if sizes_avail:
            sr = QHBoxLayout()
            sr.addWidget(_label("Sizes:", C["muted"]))
            for s in sizes_avail:
                sl = QLabel(s)
                sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                sl.setStyleSheet(
                    f"background:{C['lavender']};color:{C['bg']};border-radius:8px;"
                    f"padding:2px 10px;font-weight:bold;font-size:12px;margin:2px;")
                sr.addWidget(sl)
            sr.addStretch()
            detail_col.addLayout(sr)

        # Spec grid
        grid = QGridLayout(); grid.setSpacing(4); grow = 0
        def gadd(k, v, c=None):
            nonlocal grow
            if not v: return
            grid.addWidget(_label(k, C["muted"], size=11), grow, 0)
            grid.addWidget(_label(str(v), c or C["white"], size=11), grow, 1)
            grow += 1
        abs_txt = p.get("absorbency_label") or (
            f"{p['absorbency_ml']} ml" if p.get("absorbency_ml") else None)
        gadd("Absorbency:", abs_txt)
        gadd("Colors:",     p.get("colors"),   C["pink"])
        gadd("Patterns:",   p.get("patterns"), C["lavender"])
        gadd("Source:",     p.get("source_site"), C["muted"])
        gadd("Updated:",   (p.get("last_updated") or "")[:10])
        if grow:
            detail_col.addLayout(grid)

        if p.get("tags"):
            detail_col.addWidget(_label(f"🏷 {p['tags']}", C["muted"], size=11))

        # Description
        if p.get("description"):
            detail_col.addWidget(_sep())
            desc = QTextEdit(p["description"][:600])
            desc.setReadOnly(True)
            desc.setMaximumHeight(110)
            desc.setStyleSheet(
                f"background:{C['panel']};color:{C['white']};"
                f"border:1px solid {C['border']};border-radius:4px;")
            detail_col.addWidget(desc)

        detail_col.addStretch()
        body.addLayout(detail_col, 1)
        root.addLayout(body)

        # ── Bottom buttons ─────────────────────────────────────────────────
        root.addWidget(_sep())
        brow = QHBoxLayout()
        if p.get("url"):
            ob = _btn("🌐 Open in Browser", C["sky"])
            url_str = p["url"]
            ob.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url_str)))
            brow.addWidget(ob)
        if self._pid:
            ab = _btn("🛒 Add to Shopping List", C["gold"])
            ab.clicked.connect(lambda: (self.add_to_list.emit(self._pid), self.accept()))
            brow.addWidget(ab)
        brow.addStretch()
        cb = _btn("Close", C["muted"])
        cb.clicked.connect(self.accept)
        brow.addWidget(cb)
        root.addLayout(brow)

        # ── Load images asynchronously ─────────────────────────────────────
        self._all_image_urls = []
        QTimer.singleShot(0, self._load_images)

    def _load_images(self):
        """Load product images: first from product_images table, then from image_url fallback."""
        pid = self._pid
        if not pid:
            # No DB id — use the product's image_url directly
            url = self._product_image_url
            if url:
                self._all_image_urls = [(None, url, False)]
                self._show_image_at(0)
            return

        def _fetch():
            try:
                if DB_OK:
                    rows = db.get_product_images(pid, include_data=False)
                    if rows:
                        return rows
            except Exception:
                pass
            return []

        def _apply(rows):
            if rows:
                # Store tuples of (row_id, url, has_blob)
                # has_blob = file_size > 0 (proxy for image_data being stored)
                self._all_image_urls = [
                    (r.get("id"), r.get("image_url", ""), bool(r.get("file_size")))
                    for r in rows if r.get("image_url")
                ]
                if self._all_image_urls:
                    self._show_image_at(0)
                    if len(self._all_image_urls) > 1:
                        self._build_thumbstrip()
                    return
            # Fallback: product_images table has no rows — use products.image_url
            url = self._product_image_url
            if url:
                self._all_image_urls = [(None, url, False)]
                self._show_image_at(0)
            else:
                self._img_lbl.setText("No image")

        future = _ThumbLoader._pool.submit(_fetch)
        future.add_done_callback(
            lambda f: QTimer.singleShot(0, lambda: _apply(f.result()))
        )

    def _show_image_at(self, idx):
        """Display image at idx — reads stored blob from DB, falls back to network."""
        if not self._all_image_urls or idx >= len(self._all_image_urls):
            return
        row_id, url, has_blob = self._all_image_urls[idx]
        if not url and not row_id:
            return

        def _fetch():
            # 1. Try stored blob in product_images first (no network needed)
            if row_id and DB_OK:
                try:
                    conn = db.get_connection()
                    result = conn.execute(
                        "SELECT image_data FROM product_images WHERE id=? AND image_data IS NOT NULL",
                        (row_id,)
                    ).fetchone()
                    conn.close()
                    if result and result[0]:
                        return bytes(result[0])
                except Exception:
                    pass

            if not url:
                return None

            # 2. Try local image cache
            try:
                if _IMG_CACHE_OK:
                    cache = _get_img_cache()
                    path = cache.fetch(url) if cache else None
                    if path:
                        return path.read_bytes()
            except Exception:
                pass

            # 3. Download from network
            try:
                from urllib.request import Request, urlopen
                req = Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/140.0.0.0 Safari/537.36",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                })
                with urlopen(req, timeout=15) as r:
                    return r.read()
            except Exception:
                return None

        def _apply(data):
            if data is None:
                self._img_lbl.setText("Image unavailable")
                return
            pix = QPixmap()
            pix.loadFromData(data)
            if pix.isNull():
                self._img_lbl.setText("Could not decode image")
                return
            pix = pix.scaled(
                300, 300,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self._img_lbl.setPixmap(pix)
            self._img_lbl.setText("")

        future = _ThumbLoader._pool.submit(_fetch)
        future.add_done_callback(
            lambda f: QTimer.singleShot(0, lambda: _apply(f.result()))
        )

    def _build_thumbstrip(self):
        """Build the thumbnail strip when a product has multiple images."""
        # Clear existing
        while self._thumb_layout.count() > 1:  # keep the stretch
            item = self._thumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._thumb_buttons = []
        for idx, (row_id, url, has_blob) in enumerate(self._all_image_urls):
            btn = QLabel()
            btn.setFixedSize(56, 56)
            btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            btn.setStyleSheet(
                f"background:{C['panel2']};border:2px solid "
                f"{C['amber'] if idx == 0 else C['border']};"
                f"border-radius:4px;cursor:pointer;")
            btn.setText(str(idx + 1))
            if url:
                btn.setToolTip(url.split("/")[-1])
            # Capture idx for click
            btn.mousePressEvent = (lambda e, i=idx: (
                self._show_image_at(i),
                self._highlight_thumb(i)
            ))

            # Load thumbnail — blob first, then cache, then network
            def _load_thumb(rid=row_id, u=url, lbl=btn):
                def _f():
                    # Try DB blob first
                    if rid and DB_OK:
                        try:
                            conn = db.get_connection()
                            r = conn.execute(
                                "SELECT image_data FROM product_images "
                                "WHERE id=? AND image_data IS NOT NULL", (rid,)
                            ).fetchone()
                            conn.close()
                            if r and r[0]:
                                return bytes(r[0])
                        except Exception:
                            pass
                    if not u:
                        return None
                    # Image cache
                    try:
                        if _IMG_CACHE_OK:
                            cache = _get_img_cache()
                            path = cache.fetch(u) if cache else None
                            if path:
                                return path.read_bytes()
                    except Exception:
                        pass
                    # Network
                    try:
                        from urllib.request import Request, urlopen
                        req = Request(u, headers={"User-Agent":
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"})
                        with urlopen(req, timeout=10) as r:
                            return r.read()
                    except Exception:
                        return None

                def _a(data):
                    if data:
                        pix = QPixmap()
                        pix.loadFromData(data)
                        if not pix.isNull():
                            pix = pix.scaled(
                                52, 52,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
                            lbl.setPixmap(pix)
                            lbl.setText("")

                fut = _ThumbLoader._pool.submit(_f)
                fut.add_done_callback(
                    lambda f: QTimer.singleShot(0, lambda: _a(f.result()))
                )

            _load_thumb()
            self._thumb_layout.insertWidget(idx, btn)
            self._thumb_buttons.append(btn)

        self._thumb_row.setVisible(True)

    def _highlight_thumb(self, active_idx):
        """Highlight the active thumbnail."""
        for i, btn in enumerate(getattr(self, '_thumb_buttons', [])):
            color = C['amber'] if i == active_idx else C['border']
            btn.setStyleSheet(
                f"background:{C['panel2']};border:2px solid {color};"
                f"border-radius:4px;cursor:pointer;")

    def _download_images(self):
        """Download pixel data for this specific product's images only."""
        pid = self._pid
        if not pid or not DB_OK:
            return
        self._dl_img_btn.setEnabled(False)
        self._dl_img_btn.setText("⏳ Downloading…")

        def _work():
            try:
                # First ensure this product has product_images rows at all
                conn = db.get_connection()
                img_rows = conn.execute(
                    "SELECT COUNT(*) FROM product_images WHERE product_id=?", (pid,)
                ).fetchone()[0]
                if img_rows == 0:
                    # Backfill from products.image_url
                    prod = conn.execute(
                        "SELECT image_url, url FROM products WHERE id=?", (pid,)
                    ).fetchone()
                    if prod and prod["image_url"]:
                        from datetime import datetime
                        conn.execute(
                            "INSERT OR IGNORE INTO product_images "
                            "(product_id, image_url, is_primary, source, added_at) "
                            "VALUES (?, ?, 1, 'backfill', ?)",
                            (pid, prod["image_url"], datetime.now().isoformat())
                        )
                        conn.commit()
                conn.close()

                # Download only rows for this product
                downloaded = 0
                conn2 = db.get_connection()
                rows = conn2.execute(
                    "SELECT pi.id, pi.image_url, pi.is_primary, p.url AS page_url "
                    "FROM product_images pi "
                    "JOIN products p ON p.id = pi.product_id "
                    "WHERE pi.product_id=? AND pi.image_url IS NOT NULL "
                    "  AND pi.image_url != '' AND pi.image_data IS NULL",
                    (pid,)
                ).fetchall()
                conn2.close()

                import urllib.request, random
                from urllib.parse import urlparse
                _UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
                      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"

                for row in rows:
                    img_url  = row["image_url"]
                    page_url = row["page_url"] or ""
                    iid      = row["id"]
                    try:
                        origin = ""
                        if page_url:
                            p = urlparse(page_url)
                            origin = f"{p.scheme}://{p.netloc}"
                        headers = {
                            "User-Agent": _UA,
                            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                            "Accept-Language": "en-US,en;q=0.9",
                            "Sec-Fetch-Dest": "image",
                            "Sec-Fetch-Mode": "no-cors",
                            "Sec-Fetch-Site": "same-site",
                            "DNT": "1",
                        }
                        if origin:
                            headers["Referer"] = page_url or origin
                        req = urllib.request.Request(img_url, headers=headers)
                        with urllib.request.urlopen(req, timeout=15) as resp:
                            data = resp.read()
                        ct    = resp.headers.get("Content-Type","image/jpeg").split(";")[0].strip()
                        fname = img_url.rstrip("/").split("/")[-1].split("?")[0] or "image.jpg"
                        if data and len(data) > 100:
                            c3 = db.get_connection()
                            c3.execute(
                                "UPDATE product_images SET image_data=?, filename=?, "
                                "mime_type=?, file_size=? WHERE id=?",
                                (data, fname, ct, len(data), iid)
                            )
                            c3.commit(); c3.close()
                            downloaded += 1
                    except Exception:
                        pass

                return downloaded
            except Exception as e:
                return str(e)

        def _done(result):
            self._dl_img_btn.setEnabled(True)
            if isinstance(result, int):
                if result > 0:
                    self._dl_img_btn.setText(f"✓ {result} image(s) downloaded")
                    QTimer.singleShot(200, self._load_images)
                else:
                    self._dl_img_btn.setText("✓ Already downloaded")
            else:
                self._dl_img_btn.setText("✗ Failed")

        future = _ThumbLoader._pool.submit(_work)
        future.add_done_callback(
            lambda f: QTimer.singleShot(0, lambda: _done(f.result()))
        )


# ── Catalog Tab ────────────────────────────────────────────────────────────

# ── Background thumbnail loader for catalog table ─────────────────────────
class _ThumbLoader:
    """
    Loads a single image into a QLabel in the background.
    Priority: thumbnail cache (disk) → DB blob → image_cache → network.
    Thread-pool limited to 4 concurrent fetches.
    """
    _pool = ThreadPoolExecutor(max_workers=12)

    @classmethod
    def load(cls, url: str, label, row: int, table, product_id: int = 0):
        """Fire-and-forget: load image and set label pixmap on completion."""
        def _work():
            # Resolve fetch_url first — needed for all cache lookups
            fetch_url = url
            if not fetch_url and product_id and DB_OK:
                try:
                    conn = db.get_connection()
                    r = conn.execute(
                        "SELECT image_url FROM products WHERE id=? LIMIT 1",
                        (product_id,)
                    ).fetchone()
                    conn.close()
                    if r: fetch_url = r[0] or ""
                except Exception:
                    pass

            # 1. Thumbnail cache — pre-generated JPEG on disk, instant
            if _THUMB_CACHE_OK and fetch_url:
                try:
                    tc = _get_thumb_cache()
                    path = tc.get(fetch_url) if tc else None
                    if path:
                        data = path.read_bytes()
                        if data and len(data) > 100:
                            return data
                except Exception:
                    pass

            # 2. DB blobs — all stored images for this product
            if product_id and DB_OK:
                try:
                    conn = db.get_connection()
                    db_rows = conn.execute(
                        "SELECT image_data, image_url FROM product_images "
                        "WHERE product_id=? AND image_data IS NOT NULL "
                        "ORDER BY is_primary DESC, id LIMIT 5",
                        (product_id,)
                    ).fetchall()
                    conn.close()
                    for db_row in db_rows:
                        if db_row and db_row[0]:
                            data = bytes(db_row[0])
                            if len(data) > 100:
                                # Store thumbnail so next load is instant
                                row_url = db_row[1] or fetch_url
                                if row_url and _THUMB_CACHE_OK:
                                    try:
                                        _get_thumb_cache().store(row_url, data)
                                    except Exception:
                                        pass
                                return data
                except Exception:
                    pass

            if not fetch_url:
                return None

            # 3. Image cache (full-size, local disk)
            try:
                if _IMG_CACHE_OK:
                    cache = _get_img_cache()
                    path = cache.fetch(fetch_url) if cache else None
                    if path:
                        data = path.read_bytes()
                        if data and _THUMB_CACHE_OK:
                            try:
                                _get_thumb_cache().store(fetch_url, data)
                            except Exception:
                                pass
                        return data
            except Exception:
                pass

            # 4. Network download
            try:
                from urllib.request import Request, urlopen
                req = Request(fetch_url, headers={"User-Agent":
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"})
                with urlopen(req, timeout=10) as r:
                    data = r.read()
                if data and len(data) > 100:
                    if _THUMB_CACHE_OK:
                        try:
                            _get_thumb_cache().store(fetch_url, data)
                        except Exception:
                            pass
                    return data
            except Exception:
                return None

        def _apply(data):
            if data is None: return
            try:
                pix = QPixmap()
                pix.loadFromData(data)
                if not pix.isNull():
                    pix = pix.scaled(46, 46,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
                    if table and row < table.rowCount():
                        w = table.cellWidget(row, 0)
                        if w:
                            w.setPixmap(pix)
                            w.setText("")
            except Exception:
                pass

        future = cls._pool.submit(_work)
        future.add_done_callback(
            lambda f: QTimer.singleShot(0, lambda: _apply(f.result()))
        )


class _ProductCard(QFrame):
    """
    A single product card for the catalog grid.
    Shows: large product image, name, price badge, brand, size/gender/stock badges.
    Click anywhere to open ProductDialog.
    """
    clicked = pyqtSignal(int)   # emits product id

    def __init__(self, product: dict, parent=None):
        super().__init__(parent)
        p = self._p = product
        pid = p.get("id", 0)
        self._pid = pid

        self.setFixedWidth(190)
        self.setMinimumHeight(260)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._base_ss = (
            f"_ProductCard{{background:{C['panel']};border:1px solid {C['border']};"
            f"border-radius:10px;}} "
            f"_ProductCard:hover{{border:1px solid {C['amber']};background:{C['panel2']};}}"
        )
        self.setStyleSheet(self._base_ss)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 8)
        root.setSpacing(4)

        # ── Image area ────────────────────────────────────────────────────────
        self._img_lbl = QLabel()
        self._img_lbl.setFixedSize(190, 160)
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet(
            f"background:{C['panel2']};border-radius:10px 10px 0 0;"
            f"color:{C['muted']};font-size:11px;")
        self._img_lbl.setText("⏳")
        root.addWidget(self._img_lbl)

        # ── Name ──────────────────────────────────────────────────────────────
        name_lbl = QLabel(p.get("name", ""))
        name_lbl.setWordWrap(True)
        name_lbl.setMaximumHeight(40)
        name_lbl.setStyleSheet(
            f"color:{C['white']};font-size:12px;font-weight:600;"
            f"padding:0 8px;background:transparent;")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        root.addWidget(name_lbl)

        # ── Price + brand row ─────────────────────────────────────────────────
        pr = QHBoxLayout(); pr.setContentsMargins(8, 0, 8, 0); pr.setSpacing(4)
        price = p.get("display_price") or p.get("price_usd") or p.get("price")
        if price:
            pl = QLabel(f"${price:.2f}")
            pl.setStyleSheet(
                f"color:{C['bg']};background:{C['mint']};border-radius:8px;"
                f"padding:1px 7px;font-weight:bold;font-size:12px;")
        else:
            pl = QLabel("–")
            pl.setStyleSheet(f"color:{C['muted']};font-size:12px;")
        pr.addWidget(pl)
        pr.addStretch()
        # Brand type badge (ABDL / Medical / Regression)
        btype = (p.get("brand_type") or "abdl").lower()
        tc = _type_color(btype)
        bt_lbl = QLabel(btype[:3].upper())
        bt_lbl.setStyleSheet(
            f"color:{C['bg']};background:{tc};border-radius:6px;"
            f"padding:1px 5px;font-size:10px;font-weight:bold;")
        pr.addWidget(bt_lbl)
        root.addLayout(pr)

        # ── Info badges row ───────────────────────────────────────────────────
        br = QHBoxLayout(); br.setContentsMargins(8, 0, 8, 0); br.setSpacing(3)

        # 🔥 Price drop badge
        if p.get("on_sale") and p.get("price_was"):
            fire = QLabel("🔥 SALE")
            fire.setStyleSheet(
                f"color:{C['bg']};background:{C['red']};border-radius:6px;"
                f"padding:1px 5px;font-size:10px;font-weight:bold;")
            fire.setToolTip(f"Was ${p['price_was']:.2f}")
            br.addWidget(fire)

        # Stock indicator
        in_stock = bool(p.get("in_stock"))
        stock_dot = QLabel("● In Stock" if in_stock else "● Out")
        stock_dot.setStyleSheet(
            f"color:{C['mint'] if in_stock else C['red']};font-size:10px;"
            f"background:transparent;")
        br.addWidget(stock_dot)
        br.addStretch()

        # Gender icon
        gender = (p.get("gender") or "").lower()
        gicon = {"male": "♂", "female": "♀", "unisex": "⚥"}.get(gender, "")
        if gicon:
            gl = QLabel(gicon)
            gl.setStyleSheet(f"color:{C['sky']};font-size:12px;background:transparent;")
            br.addWidget(gl)

        # Discreet shipping
        if p.get("discreet_shipping") or p.get("b_discreet"):
            dl = QLabel("📦")
            dl.setToolTip("Discreet shipping")
            dl.setStyleSheet("background:transparent;font-size:11px;")
            br.addWidget(dl)

        # 🤍 Wishlist heart toggle
        self._heart = QLabel("🤍")
        self._heart.setToolTip("Add to wishlist")
        self._heart.setCursor(Qt.CursorShape.PointingHandCursor)
        self._heart.setStyleSheet("background:transparent;font-size:13px;")
        self._heart.setProperty("pid", pid)
        self._heart.mousePressEvent = lambda e, _pid=pid: self._toggle_wishlist(_pid)
        if DB_OK:
            try:
                if db.is_on_wishlist(pid):
                    self._heart.setText("❤️")
                    self._heart.setToolTip("Remove from wishlist")
            except Exception:
                pass
        br.addWidget(self._heart)

        root.addLayout(br)

        # ── Brand name ────────────────────────────────────────────────────────
        brand = p.get("brand_name") or ""
        if brand:
            bl = QLabel(brand)
            bl.setStyleSheet(
                f"color:{C['lavender']};font-size:10px;padding:0 8px;"
                f"background:transparent;")
            bl.setMaximumHeight(16)
            root.addWidget(bl)

        # ── Load image ────────────────────────────────────────────────────────
        img_url = p.get("image_url") or ""
        self._load_image(pid, img_url)

    def _toggle_wishlist(self, pid):
        if not DB_OK: return
        try:
            if db.is_on_wishlist(pid):
                db.remove_from_wishlist(pid)
                self._heart.setText("🤍")
                self._heart.setToolTip("Add to wishlist")
            else:
                db.add_to_wishlist(pid)
                self._heart.setText("❤️")
                self._heart.setToolTip("Remove from wishlist")
        except Exception:
            pass



    def _load_image(self, pid, url):
        """Load product image: thumbnail cache (disk) → DB blob → image cache → network."""
        def _fetch():
            # Resolve the URL we'll use for all cache lookups
            fetch_url = url
            if not fetch_url and pid and DB_OK:
                try:
                    conn = db.get_connection()
                    r = conn.execute(
                        "SELECT image_url FROM products WHERE id=? LIMIT 1", (pid,)
                    ).fetchone()
                    conn.close()
                    if r: fetch_url = r[0] or ""
                except Exception:
                    pass

            # ── 1. Thumbnail cache (fastest — pre-generated JPEG on disk) ──
            if _THUMB_CACHE_OK and fetch_url:
                try:
                    tc = _get_thumb_cache()
                    path = tc.get(fetch_url) if tc else None
                    if path:
                        data = path.read_bytes()
                        if data and len(data) > 100:
                            return data
                except Exception:
                    pass

            # ── 2. DB blobs — all images for this product ──────────────────
            if pid and DB_OK:
                try:
                    conn = db.get_connection()
                    rows = conn.execute(
                        "SELECT image_data, image_url FROM product_images "
                        "WHERE product_id=? AND image_data IS NOT NULL "
                        "ORDER BY is_primary DESC, id LIMIT 5", (pid,)
                    ).fetchall()
                    conn.close()
                    for row in rows:
                        if row and row[0]:
                            data = bytes(row[0])
                            if len(data) > 100:
                                # Generate thumbnail now so next load is instant
                                row_url = row[1] or fetch_url
                                if row_url and _THUMB_CACHE_OK:
                                    try:
                                        _get_thumb_cache().store(row_url, data)
                                    except Exception:
                                        pass
                                return data
                except Exception:
                    pass

            if not fetch_url:
                return None

            # ── 3. Image cache (full-size, local disk) ─────────────────────
            try:
                if _IMG_CACHE_OK:
                    cache = _get_img_cache()
                    path = cache.fetch(fetch_url) if cache else None
                    if path:
                        data = path.read_bytes()
                        # Generate thumbnail from cached full image
                        if data and _THUMB_CACHE_OK:
                            try:
                                _get_thumb_cache().store(fetch_url, data)
                            except Exception:
                                pass
                        return data
            except Exception:
                pass

            # ── 4. Network download ────────────────────────────────────────
            try:
                from urllib.request import Request, urlopen
                req = Request(fetch_url, headers={
                    "User-Agent":
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                })
                with urlopen(req, timeout=15) as r:
                    data = r.read()
                if data and len(data) > 100:
                    # Generate thumbnail from downloaded image
                    if _THUMB_CACHE_OK:
                        try:
                            _get_thumb_cache().store(fetch_url, data)
                        except Exception:
                            pass
                    return data
            except Exception:
                pass

            return None

        def _apply(data):
            if not data:
                self._img_lbl.setText("🖼")
                return
            pix = QPixmap()
            pix.loadFromData(data)
            if not pix.isNull():
                pix = pix.scaled(
                    190, 160,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                self._img_lbl.setPixmap(pix)
                self._img_lbl.setText("")
            else:
                self._img_lbl.setText("🖼")

        future = _ThumbLoader._pool.submit(_fetch)
        future.add_done_callback(
            lambda f: QTimer.singleShot(0, lambda: _apply(f.result()))
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._pid)
        super().mousePressEvent(event)


class CatalogTab(QWidget):
    request_add_to_list = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._products = []
        self._cards    = []
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self.reload)
        self._price_timer = QTimer(self)
        self._price_timer.setSingleShot(True)
        self._price_timer.setInterval(400)
        self._price_timer.timeout.connect(self.reload)
        self._build()
        self.reload()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Filter bar ────────────────────────────────────────────────────────
        fbar = QWidget()
        fbar.setStyleSheet(
            f"background:{C['panel']};border-radius:8px;"
            f"border:1px solid {C['border']};")
        fl = QVBoxLayout(fbar)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setSpacing(8)

        r1 = QHBoxLayout(); r1.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Search products…")
        self.search.setMinimumWidth(220)
        self.search.textChanged.connect(lambda: self._search_timer.start())
        r1.addWidget(self.search, 3)

        self.type_cb = QComboBox()
        self.type_cb.addItems(["All Types", "ABDL", "Medical", "Both"])
        self.type_cb.currentIndexChanged.connect(self._on_type_change)
        r1.addWidget(self.type_cb)
        self.brand_cb = QComboBox(); self.brand_cb.addItem("All Brands")
        self.brand_cb.currentIndexChanged.connect(self.reload)
        r1.addWidget(self.brand_cb, 2)
        self.cat_cb = QComboBox(); self.cat_cb.addItem("All Categories")
        self.cat_cb.currentIndexChanged.connect(self.reload)
        r1.addWidget(self.cat_cb, 2)
        self.sort_cb = QComboBox()
        self.sort_cb.addItems(["Name ↑", "Price ↑", "Newest", "Rating"])
        self.sort_cb.currentIndexChanged.connect(self.reload)
        r1.addWidget(self.sort_cb)
        fl.addLayout(r1)

        r2 = QHBoxLayout(); r2.setSpacing(12)
        self.in_stock_chk = QCheckBox("In Stock Only")
        self.discreet_chk = QCheckBox("📦 Discreet Only")
        self.sample_chk   = QCheckBox("🎁 Free Sample")
        self.sale_chk     = QCheckBox("🔥 On Sale")
        self.wishlist_chk = QCheckBox("❤️ Wishlist")
        for chk in [self.in_stock_chk, self.discreet_chk, self.sample_chk,
                    self.sale_chk, self.wishlist_chk]:
            chk.stateChanged.connect(self.reload); r2.addWidget(chk)
        r2.addSpacing(8)
        r2.addWidget(_label("Gender:", C["muted"]))
        self.gender_cb = QComboBox(); self.gender_cb.setFixedHeight(28)
        self.gender_cb.addItems(["Any", "♂ Male", "♀ Female", "⚥ Unisex"])
        self.gender_cb.currentIndexChanged.connect(self.reload)
        r2.addWidget(self.gender_cb)
        r2.addSpacing(8)
        r2.addWidget(_label("Size:", C["muted"]))
        self.size_cb = QComboBox()
        self.size_cb.addItems(["All Sizes","XS","S","M","L","XL","XXL","XXXL"])
        self.size_cb.currentIndexChanged.connect(self.reload)
        r2.addWidget(self.size_cb)
        r2.addSpacing(8)
        r2.addWidget(_label("Max $:", C["muted"]))
        self.price_sl = QSlider(Qt.Orientation.Horizontal)
        self.price_sl.setRange(0, 200); self.price_sl.setValue(0)
        self.price_sl.setFixedWidth(110)
        self.price_lbl = _label("Any", C["mint"])
        self.price_sl.valueChanged.connect(self._on_price_changed)
        r2.addWidget(self.price_sl); r2.addWidget(self.price_lbl)
        r2.addStretch()
        self.result_lbl = _label("", C["muted"], size=12)
        r2.addWidget(self.result_lbl)
        fl.addLayout(r2)
        root.addWidget(fbar)

        # ── Card grid inside scroll area ──────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(
            f"QScrollArea{{background:{C['bg']};border:none;}}"
            f"QWidget#grid_host{{background:{C['bg']};}}")
        self._grid_host = QWidget()
        self._grid_host.setObjectName("grid_host")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setSpacing(12)
        self._grid.setContentsMargins(4, 8, 4, 8)
        self._scroll.setWidget(self._grid_host)
        root.addWidget(self._scroll, 1)

        # ── Bottom bar ─────────────────────────────────────────────────────────
        bot = QHBoxLayout()
        rb = _btn("↺ Refresh", C["mint"], small=True)
        rb.clicked.connect(self.reload)
        bot.addWidget(rb)
        bot.addStretch()
        self.result_lbl2 = _label("", C["muted"], size=12)
        bot.addWidget(self.result_lbl2)
        root.addLayout(bot)

        self._populate_dropdowns()

    def _on_price_changed(self, v):
        self.price_lbl.setText("Any" if v == 0 else f"${v}")
        self._price_timer.start()

    def _populate_dropdowns(self):
        if not DB_OK: return
        btype = self.type_cb.currentText().lower()
        btype = None if btype == "all types" else btype
        brands = db.get_brands(btype)
        self.brand_cb.blockSignals(True)
        self.brand_cb.clear(); self.brand_cb.addItem("All Brands")
        for b in brands: self.brand_cb.addItem(b["name"], b["id"])
        self.brand_cb.blockSignals(False)
        cats = db.get_categories()
        self.cat_cb.blockSignals(True)
        self.cat_cb.clear(); self.cat_cb.addItem("All Categories")
        for c in cats:
            self.cat_cb.addItem(f"{c.get('icon','')} {c['name']}", c["id"])
        self.cat_cb.blockSignals(False)

    def _on_type_change(self):
        self._populate_dropdowns(); self.reload()

    def reload(self):
        if not DB_OK: return
        btype = self.type_cb.currentText().lower()
        btype = "all" if btype == "all types" else btype
        sort  = ["name","price","newest","rating"][self.sort_cb.currentIndex()]
        size_txt   = self.size_cb.currentText()
        gender_txt = self.gender_cb.currentText()
        gender = None
        if "Male" in gender_txt and "♀" not in gender_txt: gender = "male"
        elif "Female"  in gender_txt: gender = "female"
        elif "Unisex"  in gender_txt: gender = "unisex"
        q = self.search.text().strip()

        try:
            if q and hasattr(db, "search_products_fts"):
                # FTS5 path — all non-text filters applied in SQL via search_products_fts
                self._products = db.search_products_fts(
                    q, brand_type=btype,
                    in_stock_only    = self.in_stock_chk.isChecked(),
                    discreet_only    = self.discreet_chk.isChecked(),
                    free_sample_only = self.sample_chk.isChecked(),
                    on_sale_only     = self.sale_chk.isChecked(),
                    max_price        = self.price_sl.value() if self.price_sl.value() > 0 else None,
                    gender           = gender,
                )
            else:
                # Standard SQL path — everything in one query
                self._products = db.get_all_products(
                    search           = q,
                    brand_id         = self.brand_cb.currentData(),
                    category_id      = self.cat_cb.currentData(),
                    in_stock_only    = self.in_stock_chk.isChecked(),
                    sort             = sort,
                    brand_type       = btype,
                    size_filter      = None if size_txt == "All Sizes" else size_txt.lower(),
                    discreet_only    = self.discreet_chk.isChecked(),
                    free_sample_only = self.sample_chk.isChecked(),
                    max_price        = self.price_sl.value() if self.price_sl.value() > 0 else None,
                    on_sale_only     = self.sale_chk.isChecked(),
                    gender           = gender,
                )

            # Wishlist filter — one SQL query, set-based lookup
            if self.wishlist_chk.isChecked():
                try:
                    wl_ids = {w["product_id"] for w in db.get_wishlist(include_product_data=False)}
                    self._products = [p for p in self._products if p.get("id") in wl_ids]
                except Exception:
                    pass

        except Exception as e:
            print(f"[CatalogTab.reload] {e}")
            self._products = []
        self._fill_grid()


    def _fill_grid(self):
        # Clear old cards
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards = []

        # Remove everything from layout
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Calculate columns based on scroll area width (each card 190px + 12 gap)
        available = max(self._scroll.viewport().width() - 16, 190)
        cols = max(1, (available + 12) // (190 + 12))

        prods = self._products
        n = len(prods)
        count_label = f"{n:,} product{'s' if n != 1 else ''}"
        self.result_lbl.setText(count_label)
        self.result_lbl2.setText(count_label)

        if not prods:
            empty = QLabel("No products found.\nRun a scrape from the Scraper tab to populate the catalog.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color:{C['muted']};font-size:14px;padding:40px;background:transparent;")
            self._grid.addWidget(empty, 0, 0, 1, max(cols, 3))
            return

        for idx, p in enumerate(prods):
            card = _ProductCard(p, self._grid_host)
            card.clicked.connect(self._open_product)
            row, col = divmod(idx, cols)
            self._grid.addWidget(card, row, col)
            self._cards.append(card)

        # Fill remaining cells in last row with stretch spacers
        last_row_cards = n % cols
        if last_row_cards:
            for col in range(last_row_cards, cols):
                spacer = QWidget()
                spacer.setFixedWidth(190)
                self._grid.addWidget(spacer, (n - 1) // cols, col)

    def _open_product(self, pid: int):
        if not pid or not DB_OK: return
        try:
            p = db.get_product_by_id(pid)
        except Exception: return
        if not p: return
        dlg = ProductDialog(p, self)
        dlg.add_to_list.connect(self.request_add_to_list)
        dlg.exec()

    def resizeEvent(self, event):
        """Re-flow the grid when the window is resized."""
        super().resizeEvent(event)
        if self._products:
            self._fill_grid()


# ── Shopping List Tab ──────────────────────────────────────────────────────

class ShoppingListTab(QWidget):
    def __init__(self):
        super().__init__()
        self._items = []
        # Debounce qty spinner: wait 500ms after last change before writing DB
        self._qty_timers = {}   # lid → QTimer
        self._build()
        self.reload()

    def _build(self):
        root = QVBoxLayout(self); root.setContentsMargins(12,12,12,12); root.setSpacing(10)
        hdr = QHBoxLayout()
        hdr.addWidget(_label("🛒 Shopping List", C["gold"], bold=True, size=16))
        hdr.addStretch()
        self.item_count_lbl = _label("0 items", C["muted"], size=12)
        hdr.addWidget(self.item_count_lbl)
        root.addLayout(hdr)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: items table
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(6)
        COLS = ["✕","Product","Brand","Site","Unit $","Qty","Subtotal"]
        self.table = QTableWidget(); self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 36)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in [2,3]: self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        for i in [4,5,6]: self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        ll.addWidget(self.table, 1)
        tbtn = QHBoxLayout()
        clear_btn = _btn("🗑 Clear All", C["red"], small=True)
        clear_btn.clicked.connect(self._clear_all); tbtn.addWidget(clear_btn); tbtn.addStretch()
        ll.addLayout(tbtn)
        splitter.addWidget(left)

        # Right: tariff / tax / shipping / total
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(8)

        # ── Destination country selector ──────────────────────────────────────
        dest_card, dcl = _card()
        dcl.addWidget(_label("🌍 Ship To", C["lavender"], bold=True))

        dest_row = QHBoxLayout(); dest_row.setSpacing(6)
        dest_row.addWidget(_label("Country:", C["muted"], size=11))
        self._dest_cb = QComboBox()
        try:
            from tariff_engine import get_destinations, get_sub_regions, TariffEngine
            self._tariff_eng = TariffEngine()
            self._tariff_ok  = True
            for name in get_destinations():
                self._dest_cb.addItem(name)
        except ImportError:
            self._tariff_ok = False
            self._tariff_eng = None
            for label, _ in STATE_TAXES:
                self._dest_cb.addItem(f"🇺🇸 United States")
                break
        self._dest_cb.setMinimumWidth(200)
        self._dest_cb.currentIndexChanged.connect(self._on_dest_changed)
        dest_row.addWidget(self._dest_cb, 2)

        # Currency display selector
        dest_row.addSpacing(6)
        dest_row.addWidget(_label("Show in:", C["muted"], size=11))
        self._curr_cb = QComboBox()
        self._curr_cb.addItems(["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "SGD", "NZD"])
        self._curr_cb.setFixedWidth(70)
        self._curr_cb.currentIndexChanged.connect(self._recalc)
        dest_row.addWidget(self._curr_cb)
        dcl.addLayout(dest_row)

        # Sub-region (state / province / EU country)
        sub_row = QHBoxLayout(); sub_row.setSpacing(6)
        self._sub_lbl = _label("State:", C["muted"], size=11)
        sub_row.addWidget(self._sub_lbl)
        self._sub_cb = QComboBox()
        self._sub_cb.setMinimumWidth(220)
        self._sub_cb.currentIndexChanged.connect(self._recalc)
        sub_row.addWidget(self._sub_cb, 1)
        sub_row.addStretch()
        dcl.addLayout(sub_row)

        self._dest_note = _label("", C["muted"], size=10)
        self._dest_note.setWordWrap(True)
        dcl.addWidget(self._dest_note)
        rl.addWidget(dest_card)

        # ── Shipping ──────────────────────────────────────────────────────────
        sh_card, shl = _card()
        shl.addWidget(_label("📦 Shipping Estimate", C["lavender"], bold=True))
        self.free_ship_chk = QCheckBox("Free / no shipping fee")
        self.free_ship_chk.stateChanged.connect(self._on_free_ship)
        shl.addWidget(self.free_ship_chk)
        sh_row2 = QHBoxLayout()
        sh_row2.addWidget(_label("Flat shipping (USD): $", C["muted"], size=11))
        self.ship_spin = QDoubleSpinBox()
        self.ship_spin.setRange(0, 999.99); self.ship_spin.setDecimals(2)
        self.ship_spin.setSingleStep(0.50); self.ship_spin.setValue(9.99)
        self.ship_spin.valueChanged.connect(self._recalc)
        sh_row2.addWidget(self.ship_spin); sh_row2.addStretch()
        shl.addLayout(sh_row2)
        shl.addWidget(_label("Tip: most sites offer free shipping over $50–$75.", C["muted"], size=10))
        rl.addWidget(sh_card)

        # ── Cost breakdown ────────────────────────────────────────────────────
        tot_card, tol = _card()
        tol.addWidget(_label("💰 Landed Cost Estimate", C["gold"], bold=True))
        tol.addWidget(_sep())
        grid = QGridLayout(); grid.setColumnStretch(1, 1); grid.setSpacing(4)

        self._tot_sub     = _label("$0.00", C["white"],   bold=True, size=13)
        self._tot_ship_lbl= _label("$0.00", C["sky"],     bold=True, size=13)
        self._tot_duty    = _label("$0.00", C["peach"],   bold=True, size=13)
        self._tot_tax     = _label("$0.00", C["yellow"],  bold=True, size=13)
        self._tot_grand   = _label("$0.00", C["gold"],    bold=True, size=20)

        rows = [
            ("Subtotal (USD):",  self._tot_sub),
            ("Shipping:",        self._tot_ship_lbl),
            ("Import Duty:",     self._tot_duty),
            ("VAT / Sales Tax:", self._tot_tax),
        ]
        for r, (lbl, val) in enumerate(rows):
            grid.addWidget(_label(lbl, C["muted"], size=11), r, 0)
            grid.addWidget(val, r, 1)
        tol.addLayout(grid)
        tol.addWidget(_sep())

        grand_row = QHBoxLayout()
        grand_row.addWidget(_label("ESTIMATED TOTAL:", C["gold"], bold=True, size=13))
        grand_row.addStretch()
        grand_row.addWidget(self._tot_grand)
        tol.addLayout(grand_row)

        self._fx_lbl = _label("", C["muted"], size=9)
        tol.addWidget(self._fx_lbl)

        # Per-item tariff details (collapsible)
        self._tariff_detail = QTextEdit()
        self._tariff_detail.setReadOnly(True)
        self._tariff_detail.setMaximumHeight(110)
        self._tariff_detail.setStyleSheet(
            f"background:{C['bg']};color:{C['muted']};border:1px solid {C['border']};"
            f"font-size:10px;font-family:Consolas,monospace;padding:4px;")
        self._tariff_detail.setPlaceholderText("Per-item tariff breakdown will appear here…")
        tol.addWidget(self._tariff_detail)

        self._tariff_warn = _label("", C["amber"], size=10)
        self._tariff_warn.setWordWrap(True)
        tol.addWidget(self._tariff_warn)

        tol.addWidget(_label(
            "⚠ Estimates only — tariff rates can change. Always verify before ordering.",
            C["muted"], size=9))
        rl.addWidget(tot_card)

        self.export_btn = _btn("💾 Export List…", C["gold"])
        self.export_btn.clicked.connect(self._export)
        rl.addWidget(self.export_btn)
        rl.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([620, 380])
        root.addWidget(splitter, 1)

        # Populate initial sub-region list
        self._on_dest_changed()

    def reload(self):
        if not DB_OK: return
        try:
            self._items = db.get_shopping_list()
        except Exception as e:
            print(f"[ShoppingList.reload] {e}"); self._items = []
        self._fill_table()
        self._recalc()

    def add_product(self, product_id):
        try:
            db.add_to_shopping_list(product_id, 1)
        except Exception as e:
            print(f"[ShoppingList.add] {e}")
        self.reload()

    def _fill_table(self):
        items = self._items
        # Stop any pending qty timers for rows about to be replaced
        for t in self._qty_timers.values():
            t.stop()
        self._qty_timers.clear()

        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(items))
        for r, item in enumerate(items):
            price = item.get("unit_price") or 0.0
            qty   = item.get("quantity", 1)
            sub   = round(price * qty, 2)
            lid   = item.get("list_id")

            rm_btn = QPushButton("✕")
            rm_btn.setFixedSize(30, 26)
            rm_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C['red']};border:none;font-weight:bold;font-size:14px;}}"
                f"QPushButton:hover{{color:white;background:{C['red']};border-radius:4px;}}")
            rm_btn.clicked.connect(lambda _, l=lid: self._remove_item(l))
            self.table.setCellWidget(r, 0, rm_btn)

            CTR = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            def cell(txt, color=C["white"], align=Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter):
                it = QTableWidgetItem(str(txt) if txt is not None else "")
                it.setForeground(QColor(color)); it.setTextAlignment(align)
                it.setData(Qt.ItemDataRole.UserRole, lid)
                return it

            self.table.setItem(r, 1, cell(item.get("name",""),       C["white"]))
            self.table.setItem(r, 2, cell(item.get("brand_name",""),  C["lavender"]))
            self.table.setItem(r, 3, cell(item.get("source_site",""), C["muted"]))
            self.table.setItem(r, 4, cell(f"${price:.2f}", C["mint"], CTR))

            # Qty spinner with debounce: only write DB 500ms after user stops clicking
            spin = QSpinBox(); spin.setRange(1, 999); spin.setValue(qty); spin.setFixedWidth(70)
            spin.setStyleSheet(
                f"QSpinBox{{background:{C['panel2']};border:1px solid {C['border']};border-radius:4px;"
                f"color:{C['white']};padding:2px 4px;}}"
                f"QSpinBox::up-button,QSpinBox::down-button{{background:{C['border']};width:16px;border-radius:2px;}}")

            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(500)
            self._qty_timers[lid] = timer
            # Connect timeout ONCE here — not inside the value-changed handler
            timer.timeout.connect(lambda l=lid, sp=spin: self._flush_qty(l, sp))

            def _make_qty_handler(list_id, spinner, row_idx, unit_price):
                def on_changed(v):
                    # Restart debounce timer (stop first to reset countdown)
                    self._qty_timers[list_id].stop()
                    self._qty_timers[list_id].start()
                    # Update subtotal cell immediately for responsiveness
                    sub2 = round(unit_price * v, 2)
                    it2  = QTableWidgetItem(f"${sub2:.2f}")
                    it2.setForeground(QColor(C["peach"]))
                    it2.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(row_idx, 6, it2)
                    self._recalc_from_table()
                return on_changed

            spin.valueChanged.connect(_make_qty_handler(lid, spin, r, price))
            self.table.setCellWidget(r, 5, spin)
            self.table.setItem(r, 6, cell(f"${sub:.2f}", C["peach"], CTR))
            self.table.setRowHeight(r, 38)

        self.table.setUpdatesEnabled(True)
        n = sum(it.get("quantity",1) for it in items)
        self.item_count_lbl.setText(f"{len(items)} item{'s' if len(items)!=1 else ''} ({n} units)")

    def _flush_qty(self, lid, spinner):
        """Write the spinner's current value to DB."""
        try:
            val = spinner.value()
            db.update_shopping_list_qty(lid, val)
        except Exception as e:
            print(f"[ShoppingList._flush_qty] {e}")

    def _remove_item(self, lid):
        if lid in self._qty_timers:
            self._qty_timers[lid].stop()
            del self._qty_timers[lid]
        try:
            db.remove_from_shopping_list(lid)
        except Exception as e:
            print(f"[ShoppingList._remove] {e}")
        self.reload()

    def _on_dest_changed(self):
        """Update sub-region list when destination country changes."""
        dest_name = self._dest_cb.currentText()
        try:
            from tariff_engine import get_destinations, get_sub_regions, DESTINATIONS
            dests = get_destinations()
            cfg   = dests.get(dest_name, {})
            code  = cfg.get("code", "US")

            subs = get_sub_regions(code)
            self._sub_cb.blockSignals(True)
            self._sub_cb.clear()
            if subs:
                for name, _ in subs:
                    self._sub_cb.addItem(name)
                self._sub_cb.setVisible(True)
                self._sub_lbl.setVisible(True)
                sub_type = cfg.get("sub_region_type", "")
                labels = {"state":"State:", "eu_country":"Country:", "ca_province":"Province:",
                          "au_state":"State:"}
                self._sub_lbl.setText(labels.get(sub_type, "Region:"))
            else:
                self._sub_cb.setVisible(False)
                self._sub_lbl.setVisible(False)
            self._sub_cb.blockSignals(False)

            # Set suggested currency for destination
            curr_map = {"US":"USD","EU":"EUR","GB":"GBP","JP":"JPY","AU":"AUD",
                        "CA":"CAD","SG":"SGD","NZ":"NZD"}
            suggested = curr_map.get(code, "USD")
            idx = self._curr_cb.findText(suggested)
            if idx >= 0:
                self._curr_cb.blockSignals(True)
                self._curr_cb.setCurrentIndex(idx)
                self._curr_cb.blockSignals(False)

            # Destination note
            de_min = cfg.get("de_minimis_usd", 0)
            note = ""
            if de_min:
                note = f"De minimis: ${de_min} — orders below this are duty-free"
            self._dest_note.setText(note)
        except Exception:
            pass
        self._recalc()

    def _recalc_from_table(self):
        subtotal = 0.0
        for r in range(self.table.rowCount()):
            sub_item = self.table.item(r, 6)
            if sub_item:
                try: subtotal += float(sub_item.text().replace("$",""))
                except: pass
        ship_amt = 0.0 if self.free_ship_chk.isChecked() else self.ship_spin.value()
        self._tot_sub.setText(f"${subtotal:.2f}")
        self._tot_ship_lbl.setText(f"${ship_amt:.2f}")
        self._recalc()

    def _recalc(self):
        subtotal = sum((it.get("unit_price") or 0) * it.get("quantity",1) for it in self._items)
        ship_amt = 0.0 if self.free_ship_chk.isChecked() else self.ship_spin.value()

        if self._tariff_ok and self._items:
            try:
                from tariff_engine import get_destinations
                dest_name = self._dest_cb.currentText()
                dests     = get_destinations()
                cfg       = dests.get(dest_name, {})
                dest_code = cfg.get("code", "US")
                currency  = self._curr_cb.currentText()

                # Sub-region
                sub_text = self._sub_cb.currentText()
                # Extract just the abbreviation/name part
                sub_region = sub_text.split("–")[0].strip() if "–" in sub_text else sub_text.split(" ")[0].strip()

                result = self._tariff_eng.calculate(
                    self._items, destination=dest_code,
                    sub_region=sub_region,
                    shipping_usd=ship_amt,
                    currency=currency,
                )

                sym = cfg.get("symbol", "$")
                local = result.grand_total_local
                fx = result.fx_rate

                self._tot_sub.setText(f"${subtotal:.2f}")
                self._tot_ship_lbl.setText(f"${ship_amt:.2f}")
                self._tot_duty.setText(f"${result.total_duty_usd:.2f}")
                self._tot_tax.setText(f"${result.total_vat_usd:.2f}")

                if currency == "USD":
                    self._tot_grand.setText(f"${result.grand_total_usd:.2f}")
                    self._fx_lbl.setText("")
                else:
                    self._tot_grand.setText(f"{sym}{local:.2f} {currency}")
                    self._fx_lbl.setText(
                        f"1 USD = {fx:.4f} {currency}  ·  rate: {result.fx_last_updated}")

                # Per-item breakdown
                lines = []
                for item in result.items:
                    flag = "🔥 " if getattr(item, 'on_sale', False) else ""
                    lines.append(
                        f"{item.name[:28]:<28}  origin:{item.origin:<2}  "
                        f"duty:{item.duty_rate*100:.0f}%={sym}{item.duty_usd*fx:.2f}  "
                        f"tax:{item.vat_rate*100:.1f}%={sym}{item.vat_usd*fx:.2f}"
                    )
                self._tariff_detail.setPlainText("\n".join(lines))

                # Warnings
                warn_text = "\n".join(result.warnings[:3])
                if result.tariff_note:
                    warn_text += ("\n" if warn_text else "") + result.tariff_note
                self._tariff_warn.setText(warn_text)
                return

            except Exception as e:
                self._tariff_warn.setText(f"Tariff calc error: {e}")

        # Fallback: simple tax/ship without tariffs
        try:
            from tariff_engine import get_destinations, US_STATES
            dest_code = get_destinations().get(self._dest_cb.currentText(), {}).get("code","US")
            if dest_code == "US":
                sub = self._sub_cb.currentText()
                rate = 0.0
                for name, r in US_STATES:
                    if name.split("–")[0].strip() == sub.split("–")[0].strip():
                        rate = r; break
                tax_amt = round(subtotal * rate, 2)
            else:
                tax_amt = 0.0
        except Exception:
            tax_rate = STATE_TAXES[0][1] if STATE_TAXES else 0.0
            tax_amt  = round(subtotal * tax_rate, 2)

        grand = round(subtotal + tax_amt + ship_amt, 2)
        self._tot_sub.setText(f"${subtotal:.2f}")
        self._tot_ship_lbl.setText(f"${ship_amt:.2f}")
        self._tot_duty.setText("$0.00")
        self._tot_tax.setText(f"${tax_amt:.2f}")
        self._tot_grand.setText(f"${grand:.2f}")

    def _clear_all(self):
        if not self._items: return
        try: db.clear_shopping_list()
        except Exception as e: print(f"[clear] {e}")
        self.reload()

    def _on_free_ship(self, state):
        self.ship_spin.setEnabled(not bool(state)); self._recalc()

    def _export(self):
        if not self._items:
            QMessageBox.information(self, "Empty List", "Your shopping list is empty.")
            return

        # Format chooser dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("💾 Export Shopping List")
        dlg.setFixedWidth(340)
        dl = QVBoxLayout(dlg)
        dl.setSpacing(10); dl.setContentsMargins(20, 16, 20, 16)
        dl.addWidget(_label("Choose export format:", C["amber"], bold=True))

        btn_txt  = _btn("📄 Plain Text (.txt)",  C["mint"])
        btn_html = _btn("🌐 Rich HTML (.html)",  C["sky"])
        btn_clip = _btn("📋 Copy to Clipboard",  C["lavender"])
        btn_canc = _btn("Cancel",                C["muted"],  flat=True)

        chosen = [None]
        btn_txt.clicked.connect(lambda: (chosen.__setitem__(0,"txt"),  dlg.accept()))
        btn_html.clicked.connect(lambda: (chosen.__setitem__(0,"html"), dlg.accept()))
        btn_clip.clicked.connect(lambda: (chosen.__setitem__(0,"clip"), dlg.accept()))
        btn_canc.clicked.connect(dlg.reject)

        for b in [btn_txt, btn_html, btn_clip, btn_canc]:
            dl.addWidget(b)
        if not dlg.exec(): return
        fmt = chosen[0]

        # ── Build data using tariff engine ───────────────────────────────────
        subtotal  = sum((it.get("unit_price") or 0) * it.get("quantity",1) for it in self._items)
        ship_amt  = 0.0 if self.free_ship_chk.isChecked() else self.ship_spin.value()
        ship_label = "Free" if self.free_ship_chk.isChecked() else f"${ship_amt:.2f} (flat)"

        duty_amt  = 0.0
        tax_amt   = 0.0
        tax_label = "Tax"
        dest_label = ""
        currency  = self._curr_cb.currentText()

        if self._tariff_ok and self._items:
            try:
                from tariff_engine import get_destinations
                dest_name  = self._dest_cb.currentText()
                dest_label = dest_name
                cfg        = get_destinations().get(dest_name, {})
                dest_code  = cfg.get("code", "US")
                sub_text   = self._sub_cb.currentText()
                sub_region = sub_text.split("–")[0].strip() if "–" in sub_text else sub_text.split(" ")[0].strip()
                result     = self._tariff_eng.calculate(
                    self._items, destination=dest_code,
                    sub_region=sub_region, shipping_usd=ship_amt, currency=currency
                )
                duty_amt  = result.total_duty_usd
                tax_amt   = result.total_vat_usd
                tax_label = cfg.get("vat_label", "Tax")
                grand     = result.grand_total_usd
            except Exception:
                grand = subtotal + ship_amt
        else:
            grand = subtotal + ship_amt

        by_site: dict = {}
        for it in self._items:
            by_site.setdefault(it.get("source_site") or "Unknown", []).append(it)

        # ── Plain text ───────────────────────────────────────────────────────
        def _build_txt() -> str:
            W = 68; line = "─" * W
            rows = [
                "╔" + "═"*W + "╗",
                "║" + "  CrinkleDen — Shopping List".center(W) + "║",
                "║" + f"  {datetime.now().strftime('%Y-%m-%d  %H:%M')}  ·  {dest_label}".ljust(W) + "║",
                "╚" + "═"*W + "╝", "",
            ]
            i = 1
            for site, items in sorted(by_site.items()):
                rows.append(f"  ┌─ {site}")
                for it in items:
                    name = it.get("name","")[:38]; qty = it.get("quantity",1)
                    up = it.get("unit_price") or 0.0; sub = round(up*qty,2)
                    url = it.get("url",""); brand = it.get("brand_name","")
                    rows.append(f"  │  {i:2d}. {name:<40} x{qty:<3}  ${up:7.2f} = ${sub:8.2f}")
                    if brand: rows.append(f"  │      Brand: {brand}")
                    if url:   rows.append(f"  │      URL:   {url}")
                    rows.append("  │"); i += 1
                if rows[-1] == "  │": rows[-1] = "  └─"
                rows.append("")
            rows += [
                line,
                f"  {'Subtotal:':<30} ${subtotal:>10.2f}",
                f"  {'Shipping (' + ship_label + '):':<30} ${ship_amt:>10.2f}",
                f"  {'Import Duty:':<30} ${duty_amt:>10.2f}",
                f"  {tax_label + ':':<30} ${tax_amt:>10.2f}",
                line,
                f"  {'ESTIMATED TOTAL:':<30} ${grand:>10.2f}",
                line, "",
                "  Tariff estimates only — rates can change. Verify before ordering.",
                "  Generated by CrinkleDen (CDN)  🐾",
            ]
            return "\n".join(rows)

        # ── Rich HTML ────────────────────────────────────────────────────────
        def _build_html() -> str:
            rows_html = ""
            i = 1
            for site, items in sorted(by_site.items()):
                rows_html += f'<tr><td colspan="5" style="background:#1e4080;color:#f5a623;font-weight:bold;padding:6px 10px">🛍 {site}</td></tr>'
                for it in items:
                    name = it.get("name",""); qty = it.get("quantity",1)
                    up = it.get("unit_price") or 0.0; sub = round(up*qty,2)
                    url = it.get("url",""); brand = it.get("brand_name","")
                    sale = "🔥 " if it.get("on_sale") else ""
                    name_cell = (f'<a href="{url}" style="color:#3ecfbf;text-decoration:none">{sale}{name}</a>'
                                 if url else f'{sale}{name}')
                    rows_html += (
                        f'<tr style="background:#0c1a30">'
                        f'<td style="padding:5px 10px;color:#4a6a90">{i}</td>'
                        f'<td style="padding:5px 10px">{name_cell}<br>'
                        f'<small style="color:#a78bfa">{brand}</small></td>'
                        f'<td style="padding:5px 10px;text-align:center">{qty}</td>'
                        f'<td style="padding:5px 10px;text-align:right;color:#34d399">${up:.2f}</td>'
                        f'<td style="padding:5px 10px;text-align:right;color:#f5a623;font-weight:bold">${sub:.2f}</td>'
                        f'</tr>'
                    )
                    i += 1
            return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>CrinkleDen Shopping List</title>
<style>body{{background:#07101f;color:#e4eef8;font-family:'Segoe UI',sans-serif;padding:24px;}}
h1{{color:#f5a623}}table{{width:100%;border-collapse:collapse}}
th{{background:#102040;color:#f5a623;padding:8px 10px;text-align:left}}
tr:hover{{background:#152850!important}}
.total-row{{background:#102040;color:#f5a623;font-weight:bold;font-size:1.1em}}
</style></head><body>
<h1>🐻 CrinkleDen — Shopping List</h1>
<p style="color:#4a6a90">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} &nbsp;·&nbsp; {len(self._items)} items</p>
<table><thead><tr><th>#</th><th>Product</th><th>Qty</th><th>Unit</th><th>Subtotal</th></tr></thead>
<tbody>{rows_html}
<tr class="total-row"><td colspan="4" style="padding:8px 10px;text-align:right">Subtotal</td><td style="padding:8px 10px;text-align:right">${subtotal:.2f}</td></tr>
<tr class="total-row"><td colspan="4" style="padding:8px 10px;text-align:right">Shipping ({ship_label})</td><td style="padding:8px 10px;text-align:right">${ship_amt:.2f}</td></tr>
<tr class="total-row"><td colspan="4" style="padding:8px 10px;text-align:right">Tax ({tax_label})</td><td style="padding:8px 10px;text-align:right">${tax_amt:.2f}</td></tr>
<tr style="background:#f5a623;color:#07101f;font-weight:bold;font-size:1.2em">
<td colspan="4" style="padding:10px;text-align:right">ESTIMATED TOTAL</td>
<td style="padding:10px;text-align:right">${grand:.2f}</td></tr>
</tbody></table>
<p style="color:#4a6a90;margin-top:20px;font-size:0.85em">Prices are estimates — verify before purchasing. &nbsp; Generated by CrinkleDen (CDN) 🐾</p>
</body></html>"""

        # ── Dispatch ─────────────────────────────────────────────────────────
        try:
            if fmt == "clip":
                QApplication.clipboard().setText(_build_txt())
                QMessageBox.information(self, "Copied",
                    f"Shopping list copied to clipboard!\n\nEstimated total: ${grand:.2f}")
            elif fmt == "html":
                path, _ = QFileDialog.getSaveFileName(
                    self, "Save HTML", "crinkleden_cart.html", "HTML (*.html)")
                if not path: return
                Path(path).write_text(_build_html(), encoding="utf-8")
                QMessageBox.information(self, "Saved",
                    f"HTML saved to:\n{path}\n\nOpen in any browser for clickable links.")
                __import__("webbrowser").open(f"file:///{path}")
            else:  # txt
                path, _ = QFileDialog.getSaveFileName(
                    self, "Save Text", "crinkleden_cart.txt", "Text (*.txt)")
                if not path: return
                Path(path).write_text(_build_txt(), encoding="utf-8")
                QMessageBox.information(self, "Saved",
                    f"Shopping list saved to:\n{path}\n\nEstimated total: ${grand:.2f}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))




# ── Scraper Tab ────────────────────────────────────────────────────────────

class ScraperTab(QWidget):
    refresh_catalog = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._thread = None
        self._worker = None
        self._build()
        self._refresh_sites()

    def _build(self):
        root = QVBoxLayout(self); root.setContentsMargins(12,12,12,12); root.setSpacing(10)
        hdr = QHBoxLayout()
        hdr.addWidget(_label("🌐 Scraper Engine", C["pink"], bold=True, size=15))
        hdr.addSpacing(12)
        if SCRAPE_AVAILABLE:
            badge = _label(f"  ✓ Chromium (max {MAX_CONCURRENT} browsers)  ","")
            badge.setStyleSheet(f"background:{C['mint']};color:{C['bg']};border-radius:10px;padding:2px 10px;font-weight:bold;")
        elif _PLAYWRIGHT_IMPORT_OK and _SCRAPER_ERR:
            # Playwright is installed but scraper.py itself failed to import
            badge = _label("  ⚠ Scraper module error  ","")
            badge.setStyleSheet(f"background:{C['amber']};color:{C['bg']};border-radius:10px;padding:2px 10px;font-weight:bold;")
            badge.setToolTip(f"Playwright is installed ✓\nBut scraper.py failed:\n{_SCRAPER_ERR}")
        elif _PLAYWRIGHT_IMPORT_OK and not SCRAPE_AVAILABLE:
            # Playwright imports but Chromium browser not found
            badge = _label("  ⚠ Chromium not installed  ","")
            badge.setStyleSheet(f"background:{C['amber']};color:{C['bg']};border-radius:10px;padding:2px 10px;font-weight:bold;")
            badge.setToolTip("Playwright package is installed ✓\nBut Chromium browser is missing.\nRun: playwright install chromium")
        else:
            # Playwright not installed at all
            badge = _label("  ⚠ Playwright not installed  ","")
            badge.setStyleSheet(f"background:{C['red']};color:white;border-radius:10px;padding:2px 10px;font-weight:bold;")
            badge.setToolTip("Run:  pip install playwright\nThen: playwright install chromium")
        hdr.addWidget(badge); hdr.addStretch()
        self.force_chk = QCheckBox("Force re-scrape (ignore schedule)")
        self.force_chk.setStyleSheet(f"color:{C['yellow']};"); hdr.addWidget(self.force_chk)

        # Diagnose button — always visible so user can see exactly what's wrong
        if not SCRAPE_AVAILABLE:
            diag_btn = _btn("🔍 Diagnose", C["sky"], small=True, flat=True)
            diag_btn.clicked.connect(self._diagnose_playwright)
            hdr.addWidget(diag_btn)

        root.addLayout(hdr)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(6)
        ll.addWidget(_label("Sites", C["lavender"], bold=True))
        self.sites_table = QTableWidget(); self.sites_table.setColumnCount(4)
        self.sites_table.setHorizontalHeaderLabels(["Site","Type","Status","Next"])
        self.sites_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sites_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sites_table.verticalHeader().setVisible(False)
        self.sites_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1,4):
            self.sites_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        ll.addWidget(self.sites_table, 1)
        sb = QHBoxLayout()
        self.scrape_one_btn = _btn("▶ Scrape Selected", C["lavender"], small=True)
        self.scrape_one_btn.clicked.connect(self._scrape_one)
        self.scrape_one_btn.setEnabled(SCRAPE_AVAILABLE)
        sb.addWidget(self.scrape_one_btn); sb.addStretch()
        ref = _btn("↺", C["muted"], flat=True, small=True)
        ref.clicked.connect(self._refresh_sites); sb.addWidget(ref)
        ll.addLayout(sb)
        splitter.addWidget(left)

        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(6)
        rl.addWidget(_label("Live Log", C["lavender"], bold=True))
        self.log_box = QTextEdit(); self.log_box.setReadOnly(True)
        rl.addWidget(self.log_box, 1)
        self.pbar = QProgressBar(); self.pbar.setRange(0, 0); self.pbar.setVisible(False)
        rl.addWidget(self.pbar)
        ab = QHBoxLayout()
        self.scrape_all_btn = _btn("🌐 Scrape All Sites", C["pink"])
        self.scrape_all_btn.clicked.connect(self._scrape_all)
        self.scrape_all_btn.setEnabled(SCRAPE_AVAILABLE)
        ab.addWidget(self.scrape_all_btn)
        self.seed_btn = _btn("🌱 Load Demo Data", C["peach"])
        self.seed_btn.clicked.connect(self._seed); ab.addWidget(self.seed_btn)
        self.img_dl_btn = _btn("🖼 Download Images", C["lavender"], small=True)
        self.img_dl_btn.setToolTip(
            "Download product photos for all scraped items.\n"
            "Pulls actual image data so they display offline.")
        self.img_dl_btn.clicked.connect(self._download_images)
        ab.addWidget(self.img_dl_btn)
        self.thumb_btn = _btn("🖼→🗂 Generate Thumbnails", C["peach"], small=True)
        self.thumb_btn.setToolTip(
            "Pre-generate small 200×200 thumbnails from downloaded images.\n"
            "Run this after Download Images for instant catalog loading.")
        self.thumb_btn.clicked.connect(self._generate_thumbnails)
        ab.addWidget(self.thumb_btn)
        self.ext_btn = _btn("🚀 External Process", C["sky"], small=True)
        self.ext_btn.setToolTip(
            "Run scrape_server.py as a separate OS process\n"
            "(no shared UI thread — safe for very long scrapes)")
        self.ext_btn.clicked.connect(self._launch_external)
        self.ext_btn.setEnabled(SCRAPE_AVAILABLE)
        ab.addWidget(self.ext_btn)
        cl = _btn("🗑 Clear Log", C["muted"], flat=True, small=True)
        cl.clicked.connect(self.log_box.clear); ab.addWidget(cl)
        rl.addLayout(ab)
        splitter.addWidget(right)
        splitter.setSizes([320, 580])
        root.addWidget(splitter, 1)
        root.addWidget(_label(
            f"ℹ  Sites refresh every 3 days automatically. "
            f"Up to {MAX_CONCURRENT} browsers run in parallel. "
            f"Scraping may take several minutes.",
            C["muted"], size=11))

    def _launch_external(self):
        """Launch scrape_server.py as a separate OS process via QProcess."""
        import sys as _sys
        from pathlib import Path as _Path
        script = _Path(__file__).parent / "scrape_server.py"
        if not script.exists():
            self._log(f"⚠ scrape_server.py not found at {script}"); return
        if hasattr(self, "_ext_proc") and self._ext_proc and \
                self._ext_proc.state() == QProcess.ProcessState.Running:
            self._log("⚠ External scraper already running"); return
        self._set_busy(True)
        self._ext_proc = QProcess(self)
        force = self.force_chk.isChecked()
        args  = [str(script)] + (["--force"] if force else [])
        self._ext_proc.setProgram(_sys.executable)
        self._ext_proc.setArguments(args)
        self._ext_proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._ext_proc.readyReadStandardOutput.connect(self._read_ext_output)
        self._ext_proc.finished.connect(self._ext_done)
        self._ext_proc.start()
        self._log(f"🚀 External scraper started (PID {self._ext_proc.processId()})  force={force}")

    def _read_ext_output(self):
        if not hasattr(self, "_ext_proc") or not self._ext_proc: return
        for line in bytes(self._ext_proc.readAllStandardOutput()).decode("utf-8", errors="replace").splitlines():
            if line.strip(): self._log(line)

    def _ext_done(self, exit_code, _):
        self._set_busy(False); self._refresh_sites(); self.refresh_catalog.emit()
        self._log(f"🏁 External scraper finished (exit code {exit_code})")

    def _refresh_sites(self):
        if not DB_OK: return
        try:
            from database import should_scrape_site, next_scrape_time
            sites = db.get_scrape_sites()
        except Exception as e:
            print(f"[_refresh_sites] {e}"); return
        self._sites = sites
        self.sites_table.setUpdatesEnabled(False)
        self.sites_table.setRowCount(len(sites))
        for r, s in enumerate(sites):
            enabled = s.get("scrape_enabled")
            due     = should_scrape_site(s) if enabled else False
            def cell(t, c=C["white"]):
                it = QTableWidgetItem(str(t))
                it.setForeground(QColor(c))
                it.setData(Qt.ItemDataRole.UserRole, s.get("id"))
                return it
            self.sites_table.setItem(r, 0, cell(s["name"], C["white"] if enabled else C["muted"]))
            self.sites_table.setItem(r, 1, cell((s.get("site_type") or "").upper(), _type_color(s.get("site_type",""))))
            status = "⏸ disabled" if not enabled else ("🔔 due now" if due else f"✓ {s.get('products_found',0)} products")
            sc = C["yellow"] if due else (C["muted"] if not enabled else C["mint"])
            self.sites_table.setItem(r, 2, cell(status, sc))
            self.sites_table.setItem(r, 3, cell(next_scrape_time(s), C["muted"]))
        self.sites_table.setUpdatesEnabled(True)

    def _log(self, msg):
        self.log_box.append(str(msg))
        # Auto-scroll to bottom
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _set_busy(self, busy):
        for b in [self.scrape_all_btn, self.scrape_one_btn]:
            b.setEnabled(not busy and SCRAPE_AVAILABLE)
        self.seed_btn.setEnabled(not busy)
        self.pbar.setVisible(busy)

    def _start_worker(self, worker):
        """Launch worker in a new QThread. Safe to call even if previous thread lingers."""
        if self._thread is not None and self._thread.isRunning():
            self._log("⚠ A scrape is already running — please wait for it to finish.")
            return False
        # Clean up previous thread
        _stop_thread(self._thread)
        self._thread = None

        self._set_busy(True)
        thread = QThread(self)
        self._thread = thread
        self._worker = worker

        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._log)
        # done signal → _on_done (only ONE connection)
        worker.done.connect(self._on_done)
        # Auto-cleanup: when thread finishes, schedule deletion
        thread.finished.connect(thread.deleteLater)
        thread.start()
        return True

    def _on_done(self, result_json):
        # _on_done runs on the MAIN thread (queued cross-thread signal).
        # worker.run() has already returned by the time this fires, so the
        # thread is naturally finishing.  Never block here with wait() —
        # that would freeze the UI.  thread.finished → deleteLater
        # (connected in _start_worker) handles final cleanup automatically.
        if self._thread:
            self._thread.quit()   # stop event loop (no-op if not running exec())
        self._thread  = None
        self._worker  = None
        self._set_busy(False)
        self._refresh_sites()
        self.refresh_catalog.emit()
        self._log("─" * 50)
        # Show summary if it's a scrape result
        try:
            results = json.loads(result_json)
            if isinstance(results, list):
                ok   = sum(1 for r in results if r.get("status") == "SUCCESS")
                skip = sum(1 for r in results if r.get("status") == "SKIPPED")
                err  = sum(1 for r in results if r.get("status") == "ERROR")
                total= sum(r.get("found",0) for r in results)
                self._log(f"✅ Done — {ok} scraped, {skip} skipped, {err} errors — {total} products total")
            elif isinstance(results, dict) and "seeded" in results:
                self._log(f"✅ Demo data loaded — {results['seeded']} products seeded")
            else:
                self._log("✅ Done.")
        except Exception:
            self._log("✅ Done.")

    def _scrape_all(self):
        force = self.force_chk.isChecked()
        self._log(f"▶ Scrape All Sites  (force={force}, max {MAX_CONCURRENT} browsers)")
        w = ScrapeWorker(site_id=None, force=force)
        self._start_worker(w)

    def _scrape_one(self):
        row = self.sites_table.currentRow()
        if row < 0:
            self._log("⚠ Select a site first."); return
        item = self.sites_table.item(row, 0)
        sid  = item.data(Qt.ItemDataRole.UserRole) if item else None
        if sid is None: return
        force = self.force_chk.isChecked()
        site_name = item.text() if item else str(sid)
        self._log(f"▶ Scraping: {site_name}  (force={force})")
        w = ScrapeWorker(site_id=sid, force=force)
        self._start_worker(w)

    def _seed(self):
        self._log("🌱 Loading demo data…")
        w = SeedWorker()
        self._start_worker(w)

    def _download_images(self):
        """Download pixel data for every product that has an image URL but no stored blob."""
        if not DB_OK:
            self._log("✗ Database not available")
            return

        self.img_dl_btn.setEnabled(False)
        self.img_dl_btn.setText("⏳ Downloading…")

        outer_self = self   # capture for inner class

        class _ImgWorker(QObject):
            progress = pyqtSignal(str)
            done     = pyqtSignal(int)

            @pyqtSlot()
            def run(self):
                try:
                    # -- Diagnostic: show DB state before starting --
                    try:
                        conn = db.get_connection()
                        prod_total = conn.execute(
                            "SELECT COUNT(*) FROM products"
                        ).fetchone()[0]
                        has_url = conn.execute(
                            "SELECT COUNT(*) FROM products "
                            "WHERE image_url IS NOT NULL AND image_url != ''"
                        ).fetchone()[0]

                        # Ensure product_images table exists
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS product_images ("
                            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                            "product_id INTEGER, image_url TEXT, image_data BLOB, "
                            "filename TEXT, mime_type TEXT DEFAULT 'image/jpeg', "
                            "width INTEGER, height INTEGER, file_size INTEGER, "
                            "is_primary INTEGER DEFAULT 0, label TEXT, "
                            "source TEXT DEFAULT 'upload', "
                            "added_at TEXT DEFAULT (datetime('now')))"
                        )
                        conn.commit()

                        pi_rows = conn.execute(
                            "SELECT COUNT(*) FROM product_images"
                        ).fetchone()[0]
                        pi_urls = conn.execute(
                            "SELECT COUNT(*) FROM product_images "
                            "WHERE image_url IS NOT NULL AND image_url != ''"
                        ).fetchone()[0]
                        pi_blobs = conn.execute(
                            "SELECT COUNT(*) FROM product_images "
                            "WHERE image_data IS NOT NULL"
                        ).fetchone()[0]
                        conn.close()

                        self.progress.emit(
                            f"📋 DB: {prod_total} products, {has_url} with image URL"
                        )
                        self.progress.emit(
                            f"📋 product_images: {pi_rows} rows, "
                            f"{pi_urls} with URL, {pi_blobs} with pixel data"
                        )
                    except Exception as diag_e:
                        self.progress.emit(f"  ⚠ DB check: {diag_e}")

                    # -- Run the download --
                    total = db.download_missing_images(
                        pcb=self.progress.emit,
                        limit=999_999
                    )
                    self.done.emit(total)

                except Exception as e:
                    import traceback
                    self.progress.emit(f"  ✗ Worker error: {e}")
                    self.progress.emit(f"  {traceback.format_exc().splitlines()[-1]}")
                    self.done.emit(0)

        def _on_done(n):
            self._log(f"{'✓' if n > 0 else '⚠'} Finished — {n} image(s) downloaded")
            self.img_dl_btn.setEnabled(True)
            self.img_dl_btn.setText("🖼 Download Images")
            if n > 0:
                self.refresh_catalog.emit()

        worker = _ImgWorker()
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._log)
        worker.done.connect(_on_done)                   # fixed: named fn, takes int
        worker.done.connect(lambda _n: thread.quit())   # fixed: lambda takes _n arg
        thread.finished.connect(thread.deleteLater)
        self._img_thread = thread
        self._img_worker = worker
        thread.start()

    def _generate_thumbnails(self):
        """Batch-generate thumbnails from all stored blobs."""
        if not DB_OK:
            self._log("✗ Database not available")
            return
        if not _THUMB_CACHE_OK:
            self._log("✗ thumbnail_cache.py not found — copy it to I:\\abdl\\")
            return

        self.thumb_btn.setEnabled(False)
        self.thumb_btn.setText("⏳ Generating…")
        self._log("🗂 Generating thumbnails from stored images…")

        outer = self

        class _ThumbWorker(QObject):
            progress = pyqtSignal(str)
            done     = pyqtSignal(int)

            @pyqtSlot()
            def run(self):
                try:
                    tc = _get_thumb_cache()
                    if not tc:
                        self.progress.emit("  ✗ Could not get thumbnail cache")
                        self.done.emit(0)
                        return
                    n = tc.generate_from_blobs(pcb=self.progress.emit)
                    self.done.emit(n)
                except Exception as e:
                    self.progress.emit(f"  ✗ Error: {e}")
                    self.done.emit(0)

        def _on_done(n):
            self._log(f"{'✓' if n > 0 else '⚠'} Done — {n} thumbnail(s) generated")
            self.thumb_btn.setEnabled(True)
            self.thumb_btn.setText("🖼→🗂 Generate Thumbnails")
            if n > 0:
                self.refresh_catalog.emit()

        worker = _ThumbWorker()
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._log)
        worker.done.connect(_on_done)
        worker.done.connect(lambda _n: thread.quit())
        thread.finished.connect(thread.deleteLater)
        self._thumb_thread = thread
        self._thumb_worker = worker
        thread.start()

    def _diagnose_playwright(self):
        """Show a dialog with the exact reason scraper is unavailable."""
        lines = []

        # Step 1: playwright package import
        if _PLAYWRIGHT_IMPORT_OK:
            lines.append("✓ playwright package — installed and importable")
        else:
            lines.append(f"✗ playwright package — NOT importable")
            lines.append(f"   Error: {_PLAYWRIGHT_ERR}")
            lines.append("")
            lines.append("Fix:  pip install playwright")
            lines.append("Then: playwright install chromium")
            self._show_diag_dialog(lines); return

        # Step 2: scraper.py import
        if _SCRAPER_ERR:
            lines.append(f"✗ scraper.py — failed to import")
            lines.append(f"   Error: {_SCRAPER_ERR}")
            lines.append("")
            lines.append("This is a code/dependency error — playwright is fine.")
            lines.append("Check that all required packages are installed:")
            lines.append("  pip install beautifulsoup4 lxml requests")
        elif SCRAPE_AVAILABLE:
            lines.append("✓ scraper.py — imported OK")
            lines.append("✓ Chromium — found and launchable")
            lines.append("")
            lines.append("Everything looks good! Try restarting the app.")
        else:
            # playwright imported, scraper imported, but SCRAPE_AVAILABLE=False
            # means playwright.sync_api raised at scraper.py import time
            lines.append("✓ scraper.py — imported OK")
            lines.append("✗ Chromium browser — NOT found")
            lines.append("")
            lines.append("Playwright is installed but Chromium needs to be downloaded.")
            lines.append("Run this command in a terminal:")
            lines.append("  playwright install chromium")

        # Step 3: try launching chromium right now
        if _PLAYWRIGHT_IMPORT_OK:
            lines.append("")
            lines.append("Testing Chromium launch…")
            try:
                from playwright.sync_api import sync_playwright as _sp
                with _sp() as p:
                    b = p.chromium.launch(headless=True)
                    ver = b.version
                    b.close()
                lines.append(f"✓ Chromium launched OK (version: {ver})")
                lines.append("")
                lines.append("Playwright is working! The issue is in scraper.py.")
                lines.append("Error from scraper import: " + (_SCRAPER_ERR or "none"))
            except Exception as e:
                lines.append(f"✗ Chromium launch failed: {e}")
                lines.append("")
                lines.append("Run: playwright install chromium")

        self._show_diag_dialog(lines)

    def _show_diag_dialog(self, lines):
        dlg = QDialog(self)
        dlg.setWindowTitle("🔍 Playwright Diagnostics")
        dlg.setMinimumWidth(560)
        dlg.setStyleSheet(BASE_SS)
        vl = QVBoxLayout(dlg); vl.setContentsMargins(18,16,18,16); vl.setSpacing(10)
        vl.addWidget(_label("Playwright Diagnostics", C["sky"], bold=True, size=14))
        vl.addWidget(_sep())
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText('\n'.join(lines))
        txt.setStyleSheet(
            f"background:{C['panel']};color:{C['white']};"
            f"font-family:Consolas,monospace;font-size:12px;"
            f"border:1px solid {C['border']};border-radius:4px;")
        txt.setMinimumHeight(220)
        vl.addWidget(txt)
        row = QHBoxLayout()
        copy_btn = _btn("📋 Copy", C["muted"], small=True)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(txt.toPlainText()))
        row.addWidget(copy_btn); row.addStretch()
        ok_btn = _btn("OK", C["lavender"], small=True)
        ok_btn.clicked.connect(dlg.accept); row.addWidget(ok_btn)
        vl.addLayout(row)
        dlg.exec()

    def reload(self):
        """Called when tab becomes active — refresh site list."""
        self._refresh_sites()


# ── Site Edit Dialog ───────────────────────────────────────────────────────

class SiteEditDialog(QDialog):
    def __init__(self, site=None, parent=None):
        """site=None → add new site; site=dict → edit existing."""
        super().__init__(parent)
        self._site = site
        self.setWindowTitle("Edit Site" if site else "Add Scrape Site")
        self.setMinimumWidth(520)
        self.setStyleSheet(BASE_SS)
        root = QVBoxLayout(self); root.setContentsMargins(20,20,20,20); root.setSpacing(10)
        root.addWidget(_label("Edit Scrape Site" if site else "Add New Scrape Site",
                              C["pink"], bold=True, size=15))
        root.addWidget(_sep())

        form = QGridLayout(); form.setSpacing(8)
        def row(r, label, widget):
            form.addWidget(_label(label, C["muted"]), r, 0)
            form.addWidget(widget, r, 1)

        self.name_e  = QLineEdit(site["name"]  if site else "")
        self.url_e   = QLineEdit(site["url"]   if site else "https://")
        self.type_cb = QComboBox()
        self.type_cb.addItems(["abdl","medical","both"])
        if site: self.type_cb.setCurrentText(site.get("site_type","abdl"))
        self.interval_sp = QDoubleSpinBox()
        self.interval_sp.setRange(0.5, 30); self.interval_sp.setSingleStep(0.5)
        self.interval_sp.setDecimals(1); self.interval_sp.setSuffix(" days")
        days = (site.get("scrape_interval") or 259200) / 86400 if site else 3.0
        self.interval_sp.setValue(days)
        self.enabled_chk = QCheckBox("Enabled")
        self.enabled_chk.setChecked(bool(site.get("scrape_enabled", 1)) if site else True)

        row(0, "Site Name:",      self.name_e)
        row(1, "URL:",            self.url_e)
        row(2, "Type:",           self.type_cb)
        row(3, "Scrape Interval:",self.interval_sp)
        row(4, "Status:",         self.enabled_chk)
        root.addLayout(form)
        root.addWidget(_sep())

        btns = QHBoxLayout()
        ok_btn  = _btn("💾 Save", C["mint"])
        ok_btn.clicked.connect(self.accept)
        cxl_btn = _btn("Cancel", C["muted"])
        cxl_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn); btns.addWidget(cxl_btn)
        root.addLayout(btns)

    def values(self):
        return {
            "name":     self.name_e.text().strip(),
            "url":      self.url_e.text().strip(),
            "type":     self.type_cb.currentText(),
            "interval": self.interval_sp.value(),
            "enabled":  self.enabled_chk.isChecked(),
        }


# ── Database Management Tab ────────────────────────────────────────────────

class DBManagementTab(QWidget):
    sites_changed = pyqtSignal()   # emitted when sites enable/disable changes

    def __init__(self):
        super().__init__()
        self._prod_page  = 0
        self._prod_total = 0
        self._PER_PAGE   = 200
        self._prod_ids   = []   # ids of currently shown rows
        self._build()
        self.reload_sites()

    def _build(self):
        root = QVBoxLayout(self); root.setContentsMargins(12,10,12,12); root.setSpacing(8)
        root.addWidget(_label("🗄 Database Management", C["pink"], bold=True, size=16))

        inner = QTabWidget()
        inner.setStyleSheet(
            f"QTabBar::tab{{padding:6px 14px;font-size:12px;}}"
            f"QTabBar::tab:selected{{color:{C['lavender']};border-bottom:2px solid {C['lavender']};}}")

        inner.addTab(self._build_sites_tab(),    "🌐  Sites")
        inner.addTab(self._build_products_tab(), "📦  Products")
        inner.addTab(self._build_images_tab(),   "🖼  Images")
        inner.addTab(self._build_health_tab(),   "🔧  Health")
        inner.addTab(self._build_advanced_tab(), "⚙  Advanced")
        inner.currentChanged.connect(self._on_inner_tab)
        self._inner = inner
        root.addWidget(inner, 1)

    # ── Sites sub-tab ──────────────────────────────────────────────────────

    def _build_sites_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8,8,8,8); lay.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.addWidget(_label("Scrape Sites", C["lavender"], bold=True))
        hdr.addStretch()
        hdr.addWidget(_label("Double-click a row to edit.", C["muted"], size=11))
        lay.addLayout(hdr)

        COLS = ["ID","Name","URL","Type","Enabled","Interval","Last Scraped","Products","Actions"]
        self.sites_tbl = QTableWidget(); self.sites_tbl.setColumnCount(len(COLS))
        self.sites_tbl.setHorizontalHeaderLabels(COLS)
        self.sites_tbl.setAlternatingRowColors(True)
        self.sites_tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sites_tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sites_tbl.verticalHeader().setVisible(False)
        self.sites_tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.sites_tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for i in [0,3,4,5,6,7,8]:
            self.sites_tbl.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.ResizeToContents)
        self.sites_tbl.doubleClicked.connect(self._edit_site_row)
        lay.addWidget(self.sites_tbl, 1)

        bot = QHBoxLayout()
        add_btn   = _btn("➕ Add Site",       C["mint"],     small=True)
        add_btn.clicked.connect(self._add_site)
        eall_btn  = _btn("✓ Enable All",      C["lavender"], small=True)
        eall_btn.clicked.connect(lambda: self._enable_all(True))
        dall_btn  = _btn("⊘ Disable All",     C["muted"],    small=True)
        dall_btn.clicked.connect(lambda: self._enable_all(False))
        ref_btn   = _btn("↺ Refresh",         C["sky"],      small=True)
        ref_btn.clicked.connect(self.reload_sites)
        bot.addWidget(add_btn); bot.addWidget(eall_btn); bot.addWidget(dall_btn)
        bot.addStretch(); bot.addWidget(ref_btn)
        lay.addLayout(bot)
        return w

    def reload_sites(self):
        if not DB_OK: return
        try:
            sites = db.get_scrape_sites()
        except Exception as e:
            print(f"[reload_sites] {e}"); return
        self._sites_data = sites
        CTR = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        self.sites_tbl.setUpdatesEnabled(False)
        self.sites_tbl.setRowCount(len(sites))
        for r, s in enumerate(sites):
            enabled  = bool(s.get("scrape_enabled"))
            ec       = C["mint"] if enabled else C["red"]
            int_days = round((s.get("scrape_interval") or 259200) / 86400, 1)
            def cell(t, c=C["white"], align=Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter):
                it = QTableWidgetItem(str(t) if t is not None else "")
                it.setForeground(QColor(c)); it.setTextAlignment(align)
                it.setData(Qt.ItemDataRole.UserRole, s.get("id"))
                return it
            self.sites_tbl.setItem(r, 0, cell(s["id"],  C["muted"], CTR))
            self.sites_tbl.setItem(r, 1, cell(s["name"]))
            self.sites_tbl.setItem(r, 2, cell(s["url"],  C["sky"]))
            self.sites_tbl.setItem(r, 3, cell((s.get("site_type") or "").upper(),
                                               _type_color(s.get("site_type","")), CTR))
            self.sites_tbl.setItem(r, 4, cell("✓ Yes" if enabled else "✗ No", ec, CTR))
            self.sites_tbl.setItem(r, 5, cell(f"{int_days}d", C["muted"], CTR))
            self.sites_tbl.setItem(r, 6, cell((s.get("last_scraped") or "Never")[:16], C["muted"]))
            self.sites_tbl.setItem(r, 7, cell(s.get("products_found", 0), C["lavender"], CTR))

            # Actions widget: Enable/Disable toggle + Reset + Delete
            act_w = QWidget(); act_l = QHBoxLayout(act_w)
            act_l.setContentsMargins(2,1,2,1); act_l.setSpacing(4)
            sid = s["id"]
            tog  = _btn("⊘ Disable" if enabled else "✓ Enable",
                        C["red"] if enabled else C["mint"], small=True)
            tog.setFixedWidth(76)
            tog.clicked.connect(lambda _, i=sid, e=enabled: self._toggle_site(i, not e))
            rst  = _btn("↺", C["yellow"], flat=True, small=True)
            rst.setFixedWidth(26); rst.setToolTip("Reset schedule (scrape on next run)")
            rst.clicked.connect(lambda _, i=sid: self._reset_schedule(i))
            del_ = _btn("🗑", C["red"], flat=True, small=True)
            del_.setFixedWidth(26); del_.setToolTip("Delete site record")
            del_.clicked.connect(lambda _, i=sid, n=s["name"]: self._delete_site(i, n))
            act_l.addWidget(tog); act_l.addWidget(rst); act_l.addWidget(del_)
            self.sites_tbl.setCellWidget(r, 8, act_w)
            self.sites_tbl.setRowHeight(r, 36)
        self.sites_tbl.setUpdatesEnabled(True)

    def _toggle_site(self, sid, enable):
        try:
            db.enable_site(sid, enable)
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e)); return
        self.reload_sites(); self.sites_changed.emit()

    def _reset_schedule(self, sid):
        try:
            db.reset_site_schedule(sid)
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e)); return
        self.reload_sites()

    def _delete_site(self, sid, name):
        r = QMessageBox.question(self, "Delete Site",
            f"Delete site record for:\n\n  {name}\n\n"
            "This removes the site from the scraper schedule.\n"
            "Products already scraped from this site are NOT deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Yes: return
        try:
            db.delete_site(sid)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return
        self.reload_sites(); self.sites_changed.emit()

    def _edit_site_row(self, idx):
        row = idx.row()
        it  = self.sites_tbl.item(row, 0)
        if not it: return
        sid  = it.data(Qt.ItemDataRole.UserRole)
        site = next((s for s in self._sites_data if s["id"] == sid), None)
        if not site: return
        dlg = SiteEditDialog(site, self)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        v = dlg.values()
        if not v["name"] or not v["url"]:
            QMessageBox.warning(self, "Invalid", "Name and URL are required."); return
        try:
            db.update_site(sid, v["name"], v["url"], v["enabled"], v["type"], v["interval"])
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return
        self.reload_sites(); self.sites_changed.emit()

    def _add_site(self):
        dlg = SiteEditDialog(None, self)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        v = dlg.values()
        if not v["name"] or not v["url"]:
            QMessageBox.warning(self, "Invalid", "Name and URL are required."); return
        try:
            db.add_site(v["name"], v["url"], v["enabled"], v["type"], v["interval"])
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return
        self.reload_sites(); self.sites_changed.emit()

    def _enable_all(self, enable):
        label = "enable" if enable else "disable"
        r = QMessageBox.question(self, f"{label.title()} All Sites",
            f"Are you sure you want to {label} ALL scrape sites?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Yes: return
        conn = db.get_connection()
        conn.execute("UPDATE scrape_sites SET scrape_enabled=?", (1 if enable else 0,))
        conn.commit(); conn.close()
        self.reload_sites(); self.sites_changed.emit()

    # ── Products sub-tab ───────────────────────────────────────────────────

    def _build_products_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8,8,8,8); lay.setSpacing(8)

        fbar = QHBoxLayout()
        self.prod_search = QLineEdit(); self.prod_search.setPlaceholderText("🔍 Search name / brand…")
        self.prod_search.setMinimumWidth(200)
        self._prod_stimer = QTimer(self); self._prod_stimer.setSingleShot(True)
        self._prod_stimer.setInterval(350)
        self._prod_stimer.timeout.connect(self._prod_reload_p0)
        self.prod_search.textChanged.connect(lambda: self._prod_stimer.start())

        self.prod_src_cb = QComboBox(); self.prod_src_cb.addItem("All Sources")
        self.prod_type_cb = QComboBox()
        self.prod_type_cb.addItems(["All Types","abdl","medical","both"])
        self.prod_src_cb.currentIndexChanged.connect(self._prod_reload_p0)
        self.prod_type_cb.currentIndexChanged.connect(self._prod_reload_p0)

        fbar.addWidget(self.prod_search, 2)
        fbar.addWidget(_label("Source:", C["muted"]))
        fbar.addWidget(self.prod_src_cb)
        fbar.addWidget(_label("Type:", C["muted"]))
        fbar.addWidget(self.prod_type_cb)
        ref_src = _btn("↺ Sources", C["sky"], small=True)
        ref_src.clicked.connect(self._refresh_sources)
        fbar.addWidget(ref_src)
        lay.addLayout(fbar)

        COLS = ["ID","Name","Brand","Source Site","Type","Price","Added","Actions"]
        self.prod_tbl = QTableWidget(); self.prod_tbl.setColumnCount(len(COLS))
        self.prod_tbl.setHorizontalHeaderLabels(COLS)
        self.prod_tbl.setAlternatingRowColors(True)
        self.prod_tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.prod_tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.prod_tbl.verticalHeader().setVisible(False)
        self.prod_tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in [0,2,3,4,5,6,7]:
            self.prod_tbl.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.prod_tbl, 1)

        # Pagination + bulk actions
        bot = QHBoxLayout()
        del_sel = _btn("🗑 Delete Selected", C["red"],    small=True)
        del_sel.clicked.connect(self._delete_selected_products)
        del_src = _btn("🗑 Delete All from Source", C["red"], small=True)
        del_src.clicked.connect(self._delete_all_from_source)
        del_all = _btn("⚠ Delete ALL Products", C["red"], small=True)
        del_all.clicked.connect(self._delete_all_products)
        bot.addWidget(del_sel); bot.addWidget(del_src); bot.addWidget(del_all)
        bot.addStretch()
        self.prod_status = _label("0 products", C["muted"], size=12)
        self.prev_btn = _btn("◀", C["muted"], small=True); self.prev_btn.setFixedWidth(30)
        self.next_btn = _btn("▶", C["muted"], small=True); self.next_btn.setFixedWidth(30)
        self.page_lbl = _label("Page 1", C["muted"], size=12)
        self.prev_btn.clicked.connect(self._prod_prev_page)
        self.next_btn.clicked.connect(self._prod_next_page)
        bot.addWidget(self.prod_status)
        bot.addWidget(self.prev_btn); bot.addWidget(self.page_lbl); bot.addWidget(self.next_btn)
        lay.addLayout(bot)
        return w

    def _refresh_sources(self):
        if not DB_OK: return
        try:
            sources = db.get_source_sites_list()  # {source_site, cnt} from products table
        except Exception as e:
            print(f"[_refresh_sources] {e}"); return
        cur = self.prod_src_cb.currentText()
        self.prod_src_cb.blockSignals(True)
        self.prod_src_cb.clear()
        self.prod_src_cb.addItem("All Sources")
        for s in sources:
            self.prod_src_cb.addItem(f"{s['source_site']} ({s['cnt']})", s['source_site'])
        # Restore selection
        idx = self.prod_src_cb.findText(cur)
        if idx >= 0: self.prod_src_cb.setCurrentIndex(idx)
        self.prod_src_cb.blockSignals(False)

    def _prod_reload_p0(self):
        self._prod_page = 0; self._reload_products()

    def _reload_products(self):
        if not DB_OK: return
        src  = self.prod_src_cb.currentData()
        btype = self.prod_type_cb.currentText()
        btype = None if btype == "All Types" else btype
        try:
            total, rows = db.get_products_paginated(
                page=self._prod_page, per_page=self._PER_PAGE,
                search=self.prod_search.text(),
                source_site=src, brand_type=btype)
        except Exception as e:
            print(f"[_reload_products] {e}"); return
        self._prod_total = total
        self._prod_ids   = [r["id"] for r in rows]
        pages = max(1, (total + self._PER_PAGE - 1) // self._PER_PAGE)
        CTR = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter

        self.prod_tbl.setUpdatesEnabled(False)
        self.prod_tbl.setRowCount(len(rows))
        for r, p in enumerate(rows):
            pid   = p["id"]
            price = p.get("price")
            def cell(t, c=C["white"], align=Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter):
                it = QTableWidgetItem(str(t) if t is not None else "")
                it.setForeground(QColor(c)); it.setTextAlignment(align)
                it.setData(Qt.ItemDataRole.UserRole, pid)
                return it
            self.prod_tbl.setItem(r, 0, cell(pid,  C["muted"], CTR))
            self.prod_tbl.setItem(r, 1, cell(p.get("name","")))
            self.prod_tbl.setItem(r, 2, cell(p.get("brand_name",""),   C["lavender"]))
            self.prod_tbl.setItem(r, 3, cell(p.get("source_site",""),  C["sky"]))
            self.prod_tbl.setItem(r, 4, cell((p.get("brand_type") or "").upper(),
                                              _type_color(p.get("brand_type","")), CTR))
            self.prod_tbl.setItem(r, 5, cell(f"${price:.2f}" if price else "–", C["mint"], CTR))
            self.prod_tbl.setItem(r, 6, cell((p.get("date_added") or "")[:10], C["muted"]))

            del_btn = _btn("🗑", C["red"], flat=True, small=True)
            del_btn.setFixedSize(28, 24)
            del_btn.clicked.connect(lambda _, i=pid: self._delete_one_product(i))
            dw = QWidget(); dl = QHBoxLayout(dw)
            dl.setContentsMargins(2,0,2,0); dl.addWidget(del_btn)
            self.prod_tbl.setCellWidget(r, 7, dw)
            self.prod_tbl.setRowHeight(r, 30)
        self.prod_tbl.setUpdatesEnabled(True)

        start = self._prod_page * self._PER_PAGE + 1
        end   = min(start + len(rows) - 1, total)
        self.prod_status.setText(f"Showing {start:,}–{end:,} of {total:,} products")
        self.page_lbl.setText(f"Page {self._prod_page+1}/{pages}")
        self.prev_btn.setEnabled(self._prod_page > 0)
        self.next_btn.setEnabled((self._prod_page + 1) < pages)

    def _prod_prev_page(self):
        if self._prod_page > 0: self._prod_page -= 1; self._reload_products()

    def _prod_next_page(self):
        pages = max(1, (self._prod_total + self._PER_PAGE - 1) // self._PER_PAGE)
        if (self._prod_page + 1) < pages: self._prod_page += 1; self._reload_products()

    def _delete_one_product(self, pid):
        try:
            db.delete_products_by_ids([pid])
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return
        self._reload_products()

    def _delete_selected_products(self):
        rows = self.prod_tbl.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "Nothing Selected", "Select rows to delete."); return
        ids = []
        for idx in rows:
            it = self.prod_tbl.item(idx.row(), 0)
            if it: ids.append(it.data(Qt.ItemDataRole.UserRole))
        if not ids: return
        r = QMessageBox.question(self, "Delete Products",
            f"Delete {len(ids)} selected product(s)? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Yes: return
        try:
            n = db.delete_products_by_ids(ids)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return
        QMessageBox.information(self, "Deleted", f"{n} product(s) deleted.")
        self._reload_products()

    def _delete_all_from_source(self):
        src = self.prod_src_cb.currentData()
        if not src:
            QMessageBox.information(self, "No Source Selected",
                "Select a source site from the dropdown first."); return
        r = QMessageBox.question(self, "Delete from Source",
            f"Delete ALL products from:\n\n  {src}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Yes: return
        try:
            n = db.delete_products_by_source(src)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return
        QMessageBox.information(self, "Deleted", f"{n} products deleted from {src}.")
        self._prod_page = 0; self._reload_products()

    def _delete_all_products(self):
        r = QMessageBox.question(self, "⚠ Delete ALL Products",
            "Are you absolutely sure?\n\n"
            "This will delete ALL products from the database\n"
            "AND clear your shopping list.\n\n"
            "This action CANNOT be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Yes: return
        try:
            n = db.delete_all_products()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return
        QMessageBox.information(self, "Done", f"{n} products deleted.")
        self._prod_page = 0; self._reload_products()

    # ── Health sub-tab ─────────────────────────────────────────────────────

    # ── Images sub-tab ────────────────────────────────────────────────────────

    def _build_images_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10); lay.setSpacing(8)

        # ── Stats row ──────────────────────────────────────────────────────
        stat_row = QHBoxLayout()
        self._img_stat_lbl = _label("", C["muted"], size=11)
        stat_row.addWidget(self._img_stat_lbl)
        stat_row.addStretch()
        ref_btn = _btn("↺ Refresh", C["muted"], small=True)
        ref_btn.clicked.connect(self._refresh_images_tab)
        stat_row.addWidget(ref_btn)
        lay.addLayout(stat_row)

        # ── Filters ────────────────────────────────────────────────────────
        filt_row = QHBoxLayout(); filt_row.setSpacing(6)
        filt_row.addWidget(_label("Source:", C["muted"], size=11))
        self._img_src_filter = QComboBox(); self._img_src_filter.setFixedHeight(28)
        self._img_src_filter.addItem("All sources")
        self._img_src_filter.currentIndexChanged.connect(self._refresh_images_tab)
        filt_row.addWidget(self._img_src_filter, 1)

        filt_row.addWidget(_label("Search:", C["muted"], size=11))
        self._img_search = QLineEdit(); self._img_search.setFixedHeight(28)
        self._img_search.setPlaceholderText("filename…")
        self._img_search.returnPressed.connect(self._refresh_images_tab)
        filt_row.addWidget(self._img_search, 2)

        filt_row.addWidget(_label("Sort:", C["muted"], size=11))
        self._img_sort = QComboBox(); self._img_sort.setFixedHeight(28)
        self._img_sort.addItems(["Newest", "Oldest", "Largest", "Smallest", "Name"])
        self._img_sort.currentIndexChanged.connect(self._refresh_images_tab)
        filt_row.addWidget(self._img_sort)
        lay.addLayout(filt_row)

        # ── Table ──────────────────────────────────────────────────────────
        self._img_tbl = QTableWidget()
        self._img_tbl.setColumnCount(7)
        self._img_tbl.setHorizontalHeaderLabels(
            ["ID", "Filename", "Size (KB)", "Dims", "Source", "Rating", "Added"])
        hh = self._img_tbl.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in [0, 2, 3, 4, 5, 6]:
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._img_tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._img_tbl.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._img_tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._img_tbl.setAlternatingRowColors(True)
        self._img_tbl.setStyleSheet(
            f"background:{C['panel']};color:{C['white']};"
            f"gridline-color:{C['border']};alternate-background-color:{C['panel2']};")
        self._img_tbl.verticalHeader().setVisible(False)
        lay.addWidget(self._img_tbl, 1)

        # ── Pagination ─────────────────────────────────────────────────────
        page_row = QHBoxLayout()
        self._img_prev = _btn("◀", C["muted"], small=True)
        self._img_prev.setFixedWidth(34)
        self._img_prev.clicked.connect(lambda: self._img_go_page(-1))
        self._img_next = _btn("▶", C["muted"], small=True)
        self._img_next.setFixedWidth(34)
        self._img_next.clicked.connect(lambda: self._img_go_page(1))
        self._img_page_lbl = _label("", C["muted"], size=11)
        page_row.addWidget(self._img_prev)
        page_row.addWidget(self._img_next)
        page_row.addWidget(self._img_page_lbl)
        page_row.addStretch()
        self._img_sel_lbl = _label("", C["amber"], size=11)
        page_row.addWidget(self._img_sel_lbl)
        lay.addLayout(page_row)

        # ── Danger zone ────────────────────────────────────────────────────
        dz = QFrame()
        dz.setStyleSheet(
            f"QFrame{{background:{C['panel']};border:1px solid {C['red']}44;"
            f"border-radius:5px;padding:4px;}}")
        dzl = QHBoxLayout(dz); dzl.setSpacing(8)
        dzl.addWidget(_label("⚠ Danger:", C["red"], bold=True, size=11))

        btn_del_sel = _btn("🗑 Delete Selected", C["red"], small=True)
        btn_del_sel.setToolTip("Delete selected rows from image_library")
        btn_del_sel.clicked.connect(self._img_delete_selected)
        dzl.addWidget(btn_del_sel)

        btn_del_src = _btn("🗑 Delete by Source…", C["red"], small=True)
        btn_del_src.setToolTip("Delete all images from the currently filtered source")
        btn_del_src.clicked.connect(self._img_delete_by_source)
        dzl.addWidget(btn_del_src)

        btn_del_untagged = _btn("🗑 Delete Untagged", C["peach"], small=True)
        btn_del_untagged.setToolTip("Delete all images that have no tags assigned")
        btn_del_untagged.clicked.connect(self._img_delete_untagged)
        dzl.addWidget(btn_del_untagged)

        btn_purge_all = _btn("☠ Purge ALL Images", C["red"], small=True)
        btn_purge_all.setToolTip("Delete every image from the library (cannot be undone)")
        btn_purge_all.clicked.connect(self._img_purge_all)
        dzl.addWidget(btn_purge_all)

        dzl.addStretch()
        lay.addWidget(dz)

        # Internal state
        self._img_offset   = 0
        self._img_total    = 0
        self._img_page_sz  = 200
        return w

    def _refresh_images_tab(self):
        if not DB_OK:
            return
        try:
            db.ensure_library_tables()
        except Exception:
            pass

        src_filter = self._img_src_filter.currentText()
        if src_filter == "All sources":
            src_filter = None
        search = self._img_search.text().strip() or None
        sort_map = {"Newest": "newest", "Oldest": "oldest",
                    "Largest": "size_desc", "Smallest": "size_asc", "Name": "name"}
        sort_key = sort_map.get(self._img_sort.currentText(), "newest")

        # Rebuild source dropdown while preserving selection
        cur_src = self._img_src_filter.currentText()
        try:
            conn = db.get_connection()
            src_rows = conn.execute(
                "SELECT DISTINCT source_name FROM image_library "
                "WHERE source_name IS NOT NULL ORDER BY source_name").fetchall()
            conn.close()
            sources = [r[0] for r in src_rows]
        except Exception:
            sources = []
        self._img_src_filter.blockSignals(True)
        self._img_src_filter.clear()
        self._img_src_filter.addItem("All sources")
        for s in sources:
            self._img_src_filter.addItem(s)
        idx = self._img_src_filter.findText(cur_src)
        self._img_src_filter.setCurrentIndex(max(0, idx))
        self._img_src_filter.blockSignals(False)

        # Fetch images — get_library_images doesn't support size sort so query direct
        try:
            conn = db.get_connection()
            where_parts = []
            params = []
            if src_filter:
                where_parts.append("source_name = ?")
                params.append(src_filter)
            if search:
                where_parts.append("(filename LIKE ? OR notes LIKE ?)")
                params.extend([f"%{search}%", f"%{search}%"])
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
            order = {
                "newest":    "date_added DESC",
                "oldest":    "date_added ASC",
                "size_desc": "file_size DESC",
                "size_asc":  "file_size ASC",
                "name":      "filename ASC",
            }.get(sort_key, "date_added DESC")

            total_row = conn.execute(
                f"SELECT COUNT(*) FROM image_library {where}", params).fetchone()
            self._img_total = total_row[0] if total_row else 0
            self._img_offset = min(self._img_offset,
                                   max(0, self._img_total - self._img_page_sz))

            rows = conn.execute(
                f"SELECT id, filename, file_size, width, height, "
                f"source_name, rating, date_added "
                f"FROM image_library {where} ORDER BY {order} "
                f"LIMIT ? OFFSET ?",
                params + [self._img_page_sz, self._img_offset]).fetchall()
            conn.close()
        except Exception as e:
            self._img_stat_lbl.setText(f"Error: {e}")
            return

        # Populate table
        self._img_tbl.setRowCount(len(rows))
        for r, row in enumerate(rows):
            iid, fname, fsz, w2, h2, src, rating, added = row
            kb   = f"{(fsz or 0)//1024:,}" if fsz else "?"
            dims = f"{w2}×{h2}" if w2 and h2 else "?"
            stars = "★" * (rating or 0) if rating else ""
            vals = [str(iid), fname or "", kb, dims,
                    src or "", stars, (added or "")[:16]]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(256, iid)   # UserRole = image id
                self._img_tbl.setItem(r, c, item)

        # Pagination labels
        page  = self._img_offset // self._img_page_sz + 1
        pages = max(1, (self._img_total + self._img_page_sz - 1) // self._img_page_sz)
        self._img_page_lbl.setText(f"Page {page}/{pages}  ({self._img_total:,} total)")
        self._img_prev.setEnabled(self._img_offset > 0)
        self._img_next.setEnabled(self._img_offset + self._img_page_sz < self._img_total)

        # Stats bar
        try:
            stats = db.get_library_stats()
            self._img_stat_lbl.setText(
                f"{stats.get('total',0):,} images  ·  "
                f"{stats.get('size_mb',0)} MB  ·  "
                f"{stats.get('total_tags',0):,} tags")
        except Exception:
            self._img_stat_lbl.setText(f"{self._img_total:,} images")

        self._img_tbl.selectionModel().selectionChanged.connect(self._img_update_sel_lbl)

    def _img_go_page(self, direction):
        self._img_offset = max(0, self._img_offset + direction * self._img_page_sz)
        self._refresh_images_tab()

    def _img_update_sel_lbl(self):
        n = len(set(i.row() for i in self._img_tbl.selectedItems()))
        self._img_sel_lbl.setText(f"{n} selected" if n else "")

    def _img_selected_ids(self):
        rows = sorted(set(i.row() for i in self._img_tbl.selectedItems()))
        ids  = []
        for r in rows:
            item = self._img_tbl.item(r, 0)
            if item:
                ids.append(int(item.text()))
        return ids

    def _img_delete_selected(self):
        ids = self._img_selected_ids()
        if not ids:
            QMessageBox.information(self, "No selection", "Select rows first.")
            return
        res = QMessageBox.question(
            self, "Delete images",
            f"Permanently delete {len(ids)} image{'s' if len(ids)!=1 else ''} "
            f"from the library?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if res != QMessageBox.StandardButton.Yes:
            return
        deleted = 0
        for iid in ids:
            try:
                db.delete_library_image(iid)
                deleted += 1
            except Exception as e:
                self._hlog(f"Error deleting #{iid}: {e}", C["red"])
        self._hlog(f"✓ Deleted {deleted} image(s)", C["mint"])
        self._refresh_images_tab()

    def _img_delete_by_source(self):
        src = self._img_src_filter.currentText()
        if src == "All sources":
            QMessageBox.information(self, "Select a source",
                                    "Choose a specific source in the filter first.")
            return
        try:
            conn = db.get_connection()
            count = conn.execute(
                "SELECT COUNT(*) FROM image_library WHERE source_name=?",
                (src,)).fetchone()[0]
            conn.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return
        res = QMessageBox.question(
            self, "Delete by source",
            f"Delete all {count:,} images from source '{src}'?\n\nCannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if res != QMessageBox.StandardButton.Yes:
            return
        try:
            conn = db.get_connection()
            ids = [r[0] for r in conn.execute(
                "SELECT id FROM image_library WHERE source_name=?", (src,)).fetchall()]
            conn.close()
            for iid in ids:
                db.delete_library_image(iid)
            self._hlog(f"✓ Deleted {len(ids)} images from '{src}'", C["mint"])
        except Exception as e:
            self._hlog(f"Error: {e}", C["red"])
        self._refresh_images_tab()

    def _img_delete_untagged(self):
        try:
            conn = db.get_connection()
            count = conn.execute(
                "SELECT COUNT(*) FROM image_library il "
                "WHERE NOT EXISTS (SELECT 1 FROM image_tags it WHERE it.image_id=il.id)"
            ).fetchone()[0]
            conn.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return
        if count == 0:
            QMessageBox.information(self, "Nothing to delete",
                                    "All images already have at least one tag."); return
        res = QMessageBox.question(
            self, "Delete untagged images",
            f"Delete {count:,} untagged images? Cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if res != QMessageBox.StandardButton.Yes:
            return
        try:
            conn = db.get_connection()
            ids = [r[0] for r in conn.execute(
                "SELECT il.id FROM image_library il "
                "WHERE NOT EXISTS (SELECT 1 FROM image_tags it WHERE it.image_id=il.id)"
            ).fetchall()]
            conn.close()
            for iid in ids:
                db.delete_library_image(iid)
            self._hlog(f"✓ Deleted {len(ids)} untagged images", C["mint"])
        except Exception as e:
            self._hlog(f"Error: {e}", C["red"])
        self._refresh_images_tab()

    def _img_purge_all(self):
        try:
            conn = db.get_connection()
            count = conn.execute("SELECT COUNT(*) FROM image_library").fetchone()[0]
            conn.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return
        # Double-confirm for destructive purge
        res = QMessageBox.question(
            self, "⚠ Purge ALL images",
            f"This will permanently delete ALL {count:,} images from the library.\n\n"
            f"Type YES in the next dialog to confirm.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        if res != QMessageBox.StandardButton.Ok:
            return
        from PyQt6.QtWidgets import QInputDialog
        txt, ok = QInputDialog.getText(self, "Confirm purge",
                                       f'Type  YES  to delete all {count:,} images:')
        if not ok or txt.strip().upper() != "YES":
            return
        try:
            conn = db.get_connection()
            conn.execute("DELETE FROM image_tags")
            conn.execute("DELETE FROM image_library")
            conn.commit()
            conn.close()
            self._hlog(f"☠ Purged all {count:,} images from library", C["red"])
        except Exception as e:
            self._hlog(f"Error during purge: {e}", C["red"])
        self._refresh_images_tab()

    # ── Health sub-tab ────────────────────────────────────────────────────────
    def _build_health_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(10,10,10,10); lay.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: info cards + action buttons
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(8)
        ll.addWidget(_label("📊 Database Info", C["lavender"], bold=True))

        info_card, icl = _card()
        self._info_grid = QGridLayout(); self._info_grid.setSpacing(4)
        icl.addLayout(self._info_grid)
        ll.addWidget(info_card)

        ll.addWidget(_label("⚙ Maintenance", C["lavender"], bold=True))

        # Busy indicator shown while a background op is running
        self._busy_lbl = QLabel("⏳ Running in background…")
        self._busy_lbl.setStyleSheet(
            f"color:{C['amber']};font-size:11px;font-weight:bold;background:transparent;")
        self._busy_lbl.setVisible(False)
        ll.addWidget(self._busy_lbl)

        actions = [
            ("🔍 Integrity Check",    C["sky"],      self._run_integrity),
            ("🔄 Rebuild FTS Index",  C["lavender"], self._run_rebuild_fts),
            ("💾 WAL Checkpoint",     C["yellow"],   self._run_checkpoint),
            ("🗜 VACUUM (defrag)",    C["peach"],    self._run_vacuum),
            ("📤 Backup to File…",    C["mint"],     self._run_backup),
            ("↺ Refresh Info",        C["muted"],    self._refresh_health),
        ]
        self._maint_btns = []
        for label, color, fn in actions:
            b = _btn(label, color, small=True); b.clicked.connect(fn)
            ll.addWidget(b); self._maint_btns.append(b)

        ll.addWidget(_sep())
        ll.addWidget(_label("⚠ Danger Zone", C["red"], bold=True, size=11))
        rebuild_btn = _btn("♻ Rebuild Database…", C["red"])
        rebuild_btn.setToolTip(
            "Wipe all products, images, and catalog data.\n"
            "Auto-backup is created first.\n"
            "Scrape sites and credentials are kept.")
        rebuild_btn.clicked.connect(self._run_rebuild)
        ll.addWidget(rebuild_btn)
        ll.addStretch()
        splitter.addWidget(left)

        # Right: log
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0)
        rl.addWidget(_label("Log", C["lavender"], bold=True))
        self.health_log = QTextEdit(); self.health_log.setReadOnly(True)
        self.health_log.setStyleSheet(
            f"background:{C['panel']};color:{C['white']};border:1px solid {C['border']};")
        rl.addWidget(self.health_log, 1)
        cl = _btn("🗑 Clear Log", C["muted"], flat=True, small=True)
        cl.clicked.connect(self.health_log.clear); rl.addWidget(cl)
        splitter.addWidget(right)
        splitter.setSizes([260, 560])
        lay.addWidget(splitter, 1)
        return w

    def _hlog(self, msg, color=None):
        ts = datetime.now().strftime("%H:%M:%S")
        c2 = color or C["mint"]; self.health_log.append(f"[{ts}] {msg}")
        sb = self.health_log.verticalScrollBar(); sb.setValue(sb.maximum())

    def _refresh_health(self):
        if not DB_OK: return
        def _work():
            return db.get_db_health()
        def _done(result):
            if isinstance(result, Exception):
                self._hlog(f"Error: {result}", C["red"]); return
            info = result
            # Clear and rebuild info grid
            while self._info_grid.count():
                item = self._info_grid.takeAt(0)
                if item.widget(): item.widget().deleteLater()

            rows_data = [
                ("DB Path",       info.get("path","?")),
                ("DB Size",       f"{info.get('size_mb',0)} MB"),
                ("WAL Size",      f"{info.get('wal_mb',0)} MB"),
                ("Journal Mode",  info.get("wal_mode","?")),
                ("── Products ──", ""),
                ("Products",      f"{info.get('rows_products',0):,}"),
                ("Brands",        f"{info.get('rows_brands',0):,}"),
                ("Categories",    f"{info.get('rows_categories',0):,}"),
                ("Scrape Sites",  f"{info.get('rows_scrape_sites',0):,}"),
                ("Scrape Log",    f"{info.get('rows_scrape_log',0):,}"),
                ("Shopping List", f"{info.get('rows_shopping_list',0):,}"),
                ("── Gallery ──",  ""),
                ("Images",        f"{info.get('rows_images',0):,}"),
                ("Tags",          f"{info.get('rows_tags',0):,}"),
                ("Image Tags",    f"{info.get('rows_image_tags',0):,}"),
                ("Image Blobs",   f"{info.get('img_blob_mb',0)} MB"),
            ]
            for r, (k, v) in enumerate(rows_data):
                if k.startswith("──"):
                    sep = _label(k, C["amber"], bold=True, size=10)
                    self._info_grid.addWidget(sep, r, 0, 1, 2)
                else:
                    self._info_grid.addWidget(_label(f"{k}:", C["muted"], size=11), r, 0)
                    lbl = _label(str(v), C["white"], size=11)
                    lbl.setWordWrap(True)
                    self._info_grid.addWidget(lbl, r, 1)
            self._hlog(
                f"Info refreshed — {info.get('rows_products',0):,} products, "
                f"{info.get('rows_images',0):,} images, "
                f"{info.get('size_mb',0)} MB")
        self._run_in_thread("Refreshing DB info…", _work, _done)

    # ── Maintenance helpers (ALL run off the main thread) ─────────────────────

    def _set_busy(self, busy: bool, label: str = ""):
        """Disable/re-enable all maintenance buttons and show status."""
        for btn in self._maint_btns:
            btn.setEnabled(not busy)
        if hasattr(self, '_busy_lbl'):
            self._busy_lbl.setVisible(busy)
            if busy and label:
                self._busy_lbl.setText(f"⏳ {label}")

    def _run_in_thread(self, label: str, fn, on_done):
        """Run `fn()` in a QThread; call `on_done(result_or_exception)` on the main thread."""
        self._set_busy(True, label)

        class _W(QObject):
            finished = pyqtSignal(object)
            def __init__(self, f): super().__init__(); self._f = f
            @pyqtSlot()
            def run(self):
                try:    self.finished.emit(self._f())
                except Exception as e: self.finished.emit(e)

        t = QThread(self)
        w = _W(fn); w.moveToThread(t)
        t.started.connect(w.run)

        def _done(result):
            t.quit()
            self._set_busy(False)
            on_done(result)

        w.finished.connect(_done)
        w.finished.connect(lambda *_: t.deleteLater())
        t.start()
        self._active_thread = t   # prevent GC

    def _run_integrity(self):
        def _work():
            return db.db_integrity_check()
        def _done(result):
            if isinstance(result, Exception):
                self._hlog(f"Error: {result}", C["red"]); return
            for m in result:
                color = C["mint"] if ("ok" in m.lower() or "✓" in m) else C["red"]
                self._hlog(m, color)
        self._run_in_thread("Running integrity check…", _work, _done)

    def _run_rebuild_fts(self):
        def _work():
            return db.rebuild_fts()
        def _done(result):
            if isinstance(result, Exception):
                self._hlog(f"Error: {result}", C["red"]); return
            self._hlog(f"✓ FTS rebuilt — {result} rows indexed", C["mint"])
        self._run_in_thread("Rebuilding FTS5 index…", _work, _done)

    def _run_checkpoint(self):
        def _work():
            return db.db_checkpoint()
        def _done(result):
            if isinstance(result, Exception):
                self._hlog(f"Error: {result}", C["red"]); return
            self._hlog(
                f"✓ Checkpoint done — log={result.get('log',0)} frames, "
                f"checkpointed={result.get('checkpointed',0)}", C["mint"])
            self._refresh_health()
        self._run_in_thread("Checkpointing WAL…", _work, _done)

    def _run_vacuum(self):
        self._hlog(
            "⚠ VACUUM on a 3 GB database can take several minutes. "
            "The UI stays responsive — other tabs still work.", C["yellow"])
        def _work():
            return db.db_vacuum()
        def _done(result):
            if isinstance(result, Exception):
                self._hlog(f"Error: {result}", C["red"]); return
            self._hlog(f"✓ VACUUM done — new DB size: {result} MB", C["mint"])
            self._refresh_health()
        self._run_in_thread("VACUUM running (background — UI stays live)…", _work, _done)

    def _run_backup(self):
        default = f"abdl_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        path, _ = QFileDialog.getSaveFileName(self, "Backup Database",
                    default, "SQLite DB (*.db)")
        if not path: return
        def _work():
            return db.db_backup(path)
        def _done(result):
            if isinstance(result, Exception):
                self._hlog(f"Error: {result}", C["red"]); return
            self._hlog(f"✓ Backup saved — {result} MB → {path}", C["mint"])
        self._run_in_thread(f"Backing up to {path}…", _work, _done)

    def _run_rebuild(self):
        """Confirm and run full database rebuild."""
        reply = QMessageBox.question(
            self,
            "♻ Rebuild Database?",
            "<b>This will permanently delete all products, images, and catalog data.</b><br><br>"
            "✅ A backup will be created automatically first.<br>"
            "✅ Your scrape sites and credentials are kept.<br><br>"
            "After rebuilding, run a scrape to repopulate the catalog.<br><br>"
            "<b>Are you sure you want to continue?</b>",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._hlog("♻ Starting database rebuild…", C["amber"])

        def _work():
            return db.db_rebuild(pcb=lambda m: None)

        def _done(result):
            if isinstance(result, Exception):
                self._hlog(f"✗ Rebuild failed: {result}", C["red"])
                return
            backup_path = result
            if backup_path:
                self._hlog(f"  💾 Backup: {backup_path}", C["sky"])
            self._hlog("✅ Rebuild complete — catalog is empty", C["mint"])
            self._hlog("   Run a scrape to repopulate.", C["muted"])
            self.reload_sites()

        self._run_in_thread("Rebuilding database…", _work, _done)

    # ── Advanced sub-tab ───────────────────────────────────────────────────

    def _build_advanced_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10); lay.setSpacing(8)

        inner = QTabWidget()
        inner.setStyleSheet(
            f"QTabBar::tab{{padding:5px 12px;font-size:11px;}}"
            f"QTabBar::tab:selected{{color:{C['amber']};border-bottom:2px solid {C['amber']};}}")
        inner.addTab(self._build_dupes_panel(),   "🔍  Duplicates")
        inner.addTab(self._build_null_panel(),    "📋  Null Audit")
        inner.addTab(self._build_site_stats_panel(), "📊  Site Stats")
        inner.addTab(self._build_import_panel(),  "📥  Import CSV")
        inner.addTab(self._build_backup_panel(),  "💾  Backups")
        inner.addTab(self._build_debug_logs_panel(), "🪲  Debug Logs")
        self._adv_inner = inner
        lay.addWidget(inner, 1)
        return w

    def _build_dupes_panel(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8); lay.setSpacing(6)
        lay.addWidget(_label("🔍  Duplicate Product Finder", C["lavender"], bold=True))

        btn_row = QHBoxLayout()
        btn_scan = _btn("🔍 Scan for Duplicates", C["sky"])
        btn_scan.clicked.connect(self._adv_scan_dupes)
        btn_row.addWidget(btn_scan)
        btn_dry = _btn("🧹 Deduplicate (dry run)", C["yellow"])
        btn_dry.clicked.connect(lambda: self._adv_dedup(dry_run=True))
        btn_row.addWidget(btn_dry)
        btn_do = _btn("⚠ Deduplicate (live)", C["red"])
        btn_do.clicked.connect(lambda: self._adv_dedup(dry_run=False))
        btn_row.addWidget(btn_do)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._dupe_tbl = QTableWidget()
        self._dupe_tbl.setColumnCount(4)
        self._dupe_tbl.setHorizontalHeaderLabels(["Product Name", "Brand ID", "Copies", "IDs"])
        hh = self._dupe_tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in [1, 2, 3]:
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._dupe_tbl.setAlternatingRowColors(True)
        self._dupe_tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._dupe_tbl.setStyleSheet(
            f"background:{C['panel']};color:{C['white']};"
            f"gridline-color:{C['border']};alternate-background-color:{C['panel2']};")
        lay.addWidget(self._dupe_tbl, 1)

        self._dupe_log = QTextEdit(); self._dupe_log.setReadOnly(True)
        self._dupe_log.setMaximumHeight(80)
        self._dupe_log.setStyleSheet(f"background:{C['panel']};color:{C['white']};border:1px solid {C['border']};font-size:11px;")
        lay.addWidget(self._dupe_log)
        return w

    def _adv_scan_dupes(self):
        if not (_MGMT_OK and DB_OK): return
        def _work(): return _mgmt.find_duplicate_products()
        def _done(result):
            if isinstance(result, Exception):
                self._dupe_log.append(f"Error: {result}"); return
            dupes = result
            self._dupe_tbl.setRowCount(len(dupes))
            for r, d in enumerate(dupes):
                self._dupe_tbl.setItem(r, 0, QTableWidgetItem(d["name"] or ""))
                self._dupe_tbl.setItem(r, 1, QTableWidgetItem(str(d["brand_id"] or "")))
                self._dupe_tbl.setItem(r, 2, QTableWidgetItem(str(d["count"])))
                self._dupe_tbl.setItem(r, 3, QTableWidgetItem(", ".join(str(x) for x in d["ids"])))
            self._dupe_log.append(
                f"Found {len(dupes)} duplicate groups "
                f"({sum(d['count']-1 for d in dupes)} extra rows)")
        self._run_in_thread("Scanning for duplicates…", _work, _done)

    def _adv_dedup(self, dry_run=True):
        if not (_MGMT_OK and DB_OK): return
        if not dry_run:
            r = QMessageBox.warning(self, "Confirm Deduplication",
                "This will DELETE duplicate product rows, keeping only the newest.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            if r != QMessageBox.StandardButton.Yes: return
        def _work(): return _mgmt.deduplicate_products(dry_run=dry_run)
        def _done(result):
            if isinstance(result, Exception):
                self._dupe_log.append(f"Error: {result}"); return
            verb = "Would delete" if dry_run else "Deleted"
            self._dupe_log.append(f"{'🔍' if dry_run else '✓'} {verb} {result} rows.")
            if not dry_run: self._adv_scan_dupes()
        self._run_in_thread(
            f"{'Simulating' if dry_run else 'Running'} deduplication…", _work, _done)

    def _build_null_panel(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8); lay.setSpacing(6)
        lay.addWidget(_label("📋  Column Null Audit (products table)", C["lavender"], bold=True))

        btn_row = QHBoxLayout()
        btn_run = _btn("▶ Run Null Audit", C["sky"])
        btn_run.clicked.connect(self._adv_run_null_audit)
        btn_row.addWidget(btn_run)
        btn_fix_price = _btn("⚡ Fix Missing Prices", C["mint"])
        btn_fix_price.clicked.connect(self._adv_fix_prices)
        btn_row.addWidget(btn_fix_price)
        btn_fix_brand = _btn("⚡ Fix Missing Brands", C["lavender"])
        btn_fix_brand.clicked.connect(self._adv_fix_brands)
        btn_row.addWidget(btn_fix_brand)
        btn_orphans = _btn("🗑 Purge Orphan Images (dry)", C["yellow"])
        btn_orphans.clicked.connect(self._adv_purge_orphans)
        btn_row.addWidget(btn_orphans)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._null_tbl = QTableWidget()
        self._null_tbl.setColumnCount(4)
        self._null_tbl.setHorizontalHeaderLabels(["Column", "Null %", "Nulls", "Filled"])
        hh = self._null_tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in [1, 2, 3]:
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._null_tbl.setAlternatingRowColors(True)
        self._null_tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._null_tbl.setStyleSheet(
            f"background:{C['panel']};color:{C['white']};"
            f"gridline-color:{C['border']};alternate-background-color:{C['panel2']};")
        lay.addWidget(self._null_tbl, 1)

        self._null_log = QTextEdit(); self._null_log.setReadOnly(True)
        self._null_log.setMaximumHeight(70)
        self._null_log.setStyleSheet(
            f"background:{C['panel']};color:{C['white']};border:1px solid {C['border']};font-size:11px;")
        lay.addWidget(self._null_log)
        return w

    def _adv_run_null_audit(self):
        if not (_MGMT_OK and DB_OK): return
        def _work(): return _mgmt.get_null_audit()
        def _done(result):
            if isinstance(result, Exception):
                self._null_log.append(f"Error: {result}"); return
            audit = result
            self._null_tbl.setRowCount(len(audit))
            for r, row in enumerate(audit):
                pct = row["pct_null"]
                color = C["red"] if pct > 50 else (C["yellow"] if pct > 20 else C["white"])
                items = [row["column"], f"{pct}%", str(row["nulls"]), str(row["filled"])]
                for c, txt in enumerate(items):
                    item = QTableWidgetItem(txt)
                    item.setForeground(QColor(color))
                    self._null_tbl.setItem(r, c, item)
            self._null_log.append(f"Audit complete — {len(audit)} columns checked.")
        self._run_in_thread("Running null audit…", _work, _done)

    def _adv_fix_prices(self):
        if not (_MGMT_OK and DB_OK): return
        def _work(): return _mgmt.fix_missing_prices()
        def _done(result):
            if isinstance(result, Exception):
                self._null_log.append(f"Error: {result}"); return
            self._null_log.append(f"✓ Fixed {result} price rows.")
        self._run_in_thread("Fixing missing prices…", _work, _done)

    def _adv_fix_brands(self):
        if not (_MGMT_OK and DB_OK): return
        def _work(): return _mgmt.fix_missing_brands()
        def _done(result):
            if isinstance(result, Exception):
                self._null_log.append(f"Error: {result}"); return
            self._null_log.append(f"✓ Fixed {result} brand assignments.")
        self._run_in_thread("Fixing missing brands…", _work, _done)

    def _adv_purge_orphans(self):
        if not (_MGMT_OK and DB_OK): return
        def _work(): return _mgmt.purge_orphan_images(dry_run=True)
        def _done(result):
            if isinstance(result, Exception):
                self._null_log.append(f"Error: {result}"); return
            self._null_log.append(f"Found {result} orphan image rows (dry run — not deleted).")
        self._run_in_thread("Checking orphan images…", _work, _done)

    def _build_site_stats_panel(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8); lay.setSpacing(6)
        lay.addWidget(_label("📊  Site Performance Stats", C["lavender"], bold=True))

        btn_row = QHBoxLayout()
        btn_refresh = _btn("↺ Refresh Stats", C["sky"])
        btn_refresh.clicked.connect(self._adv_load_site_stats)
        btn_row.addWidget(btn_refresh)
        btn_reset_all = _btn("↺ Reset All Schedules", C["yellow"])
        btn_reset_all.clicked.connect(self._adv_reset_all_schedules)
        btn_row.addWidget(btn_reset_all)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._sstat_tbl = QTableWidget()
        self._sstat_tbl.setColumnCount(7)
        self._sstat_tbl.setHorizontalHeaderLabels(
            ["Site Name", "Type", "En", "DB Products", "Total Added", "Successes", "Errors"])
        hh = self._sstat_tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in [1, 2, 3, 4, 5, 6]:
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._sstat_tbl.setAlternatingRowColors(True)
        self._sstat_tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._sstat_tbl.setStyleSheet(
            f"background:{C['panel']};color:{C['white']};"
            f"gridline-color:{C['border']};alternate-background-color:{C['panel2']};")
        lay.addWidget(self._sstat_tbl, 1)
        return w

    def _adv_load_site_stats(self):
        if not (_MGMT_OK and DB_OK): return
        def _work(): return _mgmt.get_site_stats()
        def _done(result):
            if isinstance(result, Exception): return
            stats = result
            self._sstat_tbl.setRowCount(len(stats))
            for r, s in enumerate(stats):
                en_color = C["mint"] if s.get("scrape_enabled") else C["red"]
                cells = [
                    (s.get("name", ""), C["white"]),
                    (s.get("site_type", ""), _type_color(s.get("site_type", ""))),
                    ("●" if s.get("scrape_enabled") else "○", en_color),
                    (str(s.get("db_product_count", 0)), C["sky"]),
                    (str(s.get("total_added_all_time") or 0), C["mint"]),
                    (str(s.get("success_runs") or 0), C["mint"]),
                    (str(s.get("error_runs") or 0), C["red"] if (s.get("error_runs") or 0) > 0 else C["muted"]),
                ]
                for c, (txt, col) in enumerate(cells):
                    item = QTableWidgetItem(txt)
                    item.setForeground(QColor(col))
                    self._sstat_tbl.setItem(r, c, item)
        self._run_in_thread("Loading site stats…", _work, _done)

    def _adv_reset_all_schedules(self):
        if not (_MGMT_OK and DB_OK): return
        r = QMessageBox.question(self, "Reset Schedules",
            "Clear last_scraped for all enabled sites so they run on next pass?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Yes: return
        def _work(): return _mgmt.reset_all_schedules()
        def _done(result):
            if isinstance(result, Exception): return
            QMessageBox.information(self, "Done", f"Reset {result} site schedules.")
        self._run_in_thread("Resetting schedules…", _work, _done)

    def _build_import_panel(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8); lay.setSpacing(8)
        lay.addWidget(_label("📥  Import / Export Products", C["lavender"], bold=True))

        # ── Export ────────────────────────────────────────────────────────────
        exp_box = QFrame()
        exp_box.setStyleSheet(
            f"QFrame{{background:{C['card']};border:1px solid {C['border']};"
            f"border-radius:6px;padding:4px;}}")
        ebl = QVBoxLayout(exp_box); ebl.setSpacing(6)
        ebl.addWidget(_label("Export", C["amber"], bold=True, size=12))
        exp_btn_row = QHBoxLayout()
        btn_exp_csv  = _btn("📤 Export CSV",   C["mint"])
        btn_exp_json = _btn("📤 Export JSONL", C["sky"])
        btn_exp_csv.clicked.connect(lambda: self._adv_export("csv"))
        btn_exp_json.clicked.connect(lambda: self._adv_export("jsonl"))
        exp_btn_row.addWidget(btn_exp_csv)
        exp_btn_row.addWidget(btn_exp_json)
        exp_btn_row.addStretch()
        ebl.addLayout(exp_btn_row)
        lay.addWidget(exp_box)

        # ── Import CSV ────────────────────────────────────────────────────────
        csv_box = QFrame()
        csv_box.setStyleSheet(
            f"QFrame{{background:{C['card']};border:1px solid {C['border']};"
            f"border-radius:6px;padding:4px;}}")
        cbl = QVBoxLayout(csv_box); cbl.setSpacing(6)
        cbl.addWidget(_label("Import from CSV", C["amber"], bold=True, size=12))
        cbl.addWidget(_label(
            "Columns: name, brand, category, brand_type, price_usd, url, source_site",
            C["muted"], size=11))
        imp_row = QHBoxLayout()
        self._imp_path_lbl = _label("No file selected", C["muted"], size=11)
        btn_browse = _btn("📂 Browse…", C["lavender"], small=True)
        btn_browse.clicked.connect(self._adv_browse_csv)
        self._btn_import_csv = _btn("📥 Import", C["mint"], small=True)
        self._btn_import_csv.setEnabled(False)
        self._btn_import_csv.clicked.connect(self._adv_import_csv)
        imp_row.addWidget(btn_browse)
        imp_row.addWidget(self._imp_path_lbl, 1)
        imp_row.addWidget(self._btn_import_csv)
        cbl.addLayout(imp_row)
        lay.addWidget(csv_box)

        # ── Import JSON ───────────────────────────────────────────────────────
        json_box = QFrame()
        json_box.setStyleSheet(
            f"QFrame{{background:{C['card']};border:1px solid {C['border']};"
            f"border-radius:6px;padding:4px;}}")
        jbl = QVBoxLayout(json_box); jbl.setSpacing(6)
        jbl.addWidget(_label("Import from JSON", C["amber"], bold=True, size=12))
        jbl.addWidget(_label(
            "Auto-detects Shopify, WooCommerce, or flat JSON. "
            "Imports products, prices, descriptions, and all images.",
            C["muted"], size=11))

        # File picker row
        jrow1 = QHBoxLayout()
        self._json_path_lbl = _label("No file selected", C["muted"], size=11)
        btn_json_browse = _btn("📂 Browse JSON…", C["lavender"], small=True)
        btn_json_browse.clicked.connect(self._browse_json)
        jrow1.addWidget(btn_json_browse)
        jrow1.addWidget(self._json_path_lbl, 1)
        jbl.addLayout(jrow1)

        # Source site + brand type + preview row
        jrow2 = QHBoxLayout(); jrow2.setSpacing(8)
        jrow2.addWidget(_label("Source name:", C["muted"], size=11))
        self._json_source = QLineEdit()
        self._json_source.setPlaceholderText("e.g. Tykables Store")
        self._json_source.setFixedWidth(180)
        jrow2.addWidget(self._json_source)
        jrow2.addSpacing(8)
        jrow2.addWidget(_label("Type:", C["muted"], size=11))
        self._json_btype = QComboBox()
        self._json_btype.addItems(["abdl", "medical", "regression", "both"])
        self._json_btype.setFixedWidth(110)
        jrow2.addWidget(self._json_btype)
        jrow2.addStretch()
        self._btn_json_preview = _btn("🔍 Preview", C["sky"], small=True)
        self._btn_json_preview.setEnabled(False)
        self._btn_json_preview.clicked.connect(self._preview_json)
        jrow2.addWidget(self._btn_json_preview)
        self._btn_json_import = _btn("📥 Import All", C["mint"], small=True)
        self._btn_json_import.setEnabled(False)
        self._btn_json_import.clicked.connect(self._import_json)
        jrow2.addWidget(self._btn_json_import)
        jbl.addLayout(jrow2)

        lay.addWidget(json_box)

        # Shared log for both import types
        self._imp_log = QTextEdit(); self._imp_log.setReadOnly(True)
        self._imp_log.setStyleSheet(
            f"background:{C['panel']};color:{C['white']};"
            f"border:1px solid {C['border']};font-size:11px;")
        lay.addWidget(self._imp_log, 1)

        self._csv_path  = None
        self._json_path = None
        return w

    def _browse_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select JSON file", "",
            "JSON files (*.json *.jsonl);;All files (*)")
        if not path:
            return
        self._json_path = path
        self._json_path_lbl.setText(Path(path).name)
        self._btn_json_preview.setEnabled(True)
        self._btn_json_import.setEnabled(True)
        # Auto-fill source name from filename if empty
        if not self._json_source.text():
            stem = Path(path).stem.replace("_", " ").replace("-", " ").title()
            self._json_source.setText(stem)

    def _preview_json(self):
        if not self._json_path:
            return
        path  = self._json_path
        btype = self._json_btype.currentText()
        source = self._json_source.text().strip() or Path(path).stem
        self._imp_log.clear()
        self._imp_log.append(f"🔍 Previewing {Path(path).name}…")

        def _work():
            return db.parse_product_json(path, source_site=source, brand_type=btype,
                                          dry_run=True)

        def _done(result):
            if isinstance(result, Exception):
                self._imp_log.append(f"✗ Error: {result}")
                return
            products, fmt, warnings = result
            self._imp_log.append(
                f"  Format detected: {fmt}")
            self._imp_log.append(
                f"  Products found: {len(products)}")
            with_img = sum(1 for p in products if p.get("image_url"))
            with_price = sum(1 for p in products if p.get("price_usd"))
            self._imp_log.append(
                f"  With image URL: {with_img} / {len(products)}")
            self._imp_log.append(
                f"  With price: {with_price} / {len(products)}")
            if products:
                self._imp_log.append("")
                self._imp_log.append("  First 5 products:")
                for p in products[:5]:
                    price_str = f"${p['price_usd']:.2f}" if p.get("price_usd") else "no price"
                    img_str   = "🖼" if p.get("image_url") else "no img"
                    self._imp_log.append(
                        f"    • {p.get('name','?')[:50]}  {price_str}  {img_str}")
            for w in warnings[:5]:
                self._imp_log.append(f"  ⚠ {w}")

        self._run_in_thread("Previewing JSON…", _work, _done)

    def _import_json(self):
        if not self._json_path:
            return
        path   = self._json_path
        btype  = self._json_btype.currentText()
        source = self._json_source.text().strip() or Path(path).stem
        self._imp_log.clear()
        self._imp_log.append(f"📥 Importing {Path(path).name}…")

        def _work():
            return db.parse_product_json(path, source_site=source, brand_type=btype,
                                          dry_run=False,
                                          pcb=lambda m: None)

        def _done(result):
            if isinstance(result, Exception):
                self._imp_log.append(f"✗ Error: {result}")
                return
            products, fmt, warnings = result
            self._imp_log.append(
                f"✓ Done — {len(products)} products imported from {fmt} file")
            with_img = sum(1 for p in products if p.get("image_url"))
            self._imp_log.append(
                f"  {with_img} products have images (run 🖼 Download Images to fetch them)")
            for w in warnings[:10]:
                self._imp_log.append(f"  ⚠ {w}")

        self._run_in_thread("Importing JSON…", _work, _done)



    def _adv_export(self, fmt):
        if not (_MGMT_OK and DB_OK): return
        ext  = ".csv" if fmt == "csv" else ".jsonl"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Products", f"abdl_products{ext}", f"*{ext}")
        if not path: return
        def _work():
            if fmt == "csv":   return _mgmt.export_products_csv(path)
            else:              return _mgmt.export_products_jsonl(path)
        def _done(result):
            if isinstance(result, Exception):
                self._imp_log.append(f"Error: {result}"); return
            p, cnt = result
            self._imp_log.append(f"✓ Exported {cnt} rows → {p}")
        self._run_in_thread(f"Exporting {fmt.upper()}…", _work, _done)

    def _adv_browse_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select CSV", "", "CSV files (*.csv)")
        if not path: return
        self._csv_path = path
        self._imp_path_lbl.setText(Path(path).name)
        self._btn_import_csv.setEnabled(True)

    def _adv_import_csv(self):
        if not self._csv_path or not (_MGMT_OK and DB_OK): return
        path = self._csv_path
        def _work():
            def log(m): pass
            return _mgmt.import_products_csv(path, dry_run=False, pcb=log)
        def _done(result):
            if isinstance(result, Exception):
                self._imp_log.append(f"Error: {result}"); return
            added, updated, skipped, errors = result
            self._imp_log.append(
                f"✓ Import done — added={added} skipped={skipped} errors={errors}")
        self._run_in_thread(f"Importing {Path(path).name}…", _work, _done)

    def _build_backup_panel(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8); lay.setSpacing(6)
        lay.addWidget(_label("💾  Automated Backup Manager", C["lavender"], bold=True))
        lay.addWidget(_label("Keeps the last 10 backups. All backups are stored in ./backups/",
                             C["muted"], size=11))

        btn_row = QHBoxLayout()
        btn_backup = _btn("💾 Create Backup Now", C["mint"])
        btn_backup.clicked.connect(self._adv_create_backup)
        btn_row.addWidget(btn_backup)
        btn_refresh = _btn("↺ Refresh List", C["sky"], small=True)
        btn_refresh.clicked.connect(self._adv_load_backups)
        btn_row.addWidget(btn_refresh)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._backup_tbl = QTableWidget()
        self._backup_tbl.setColumnCount(3)
        self._backup_tbl.setHorizontalHeaderLabels(["Filename", "Created", "Size (MB)"])
        hh = self._backup_tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in [1, 2]:
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._backup_tbl.setAlternatingRowColors(True)
        self._backup_tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._backup_tbl.setStyleSheet(
            f"background:{C['panel']};color:{C['white']};"
            f"gridline-color:{C['border']};alternate-background-color:{C['panel2']};")
        lay.addWidget(self._backup_tbl, 1)

        self._backup_log = QTextEdit(); self._backup_log.setReadOnly(True)
        self._backup_log.setMaximumHeight(60)
        self._backup_log.setStyleSheet(
            f"background:{C['panel']};color:{C['white']};border:1px solid {C['border']};font-size:11px;")
        lay.addWidget(self._backup_log)
        return w

    def _adv_create_backup(self):
        if not (_MGMT_OK and DB_OK): return
        def _work(): return _mgmt.create_backup()
        def _done(result):
            if isinstance(result, Exception):
                self._backup_log.append(f"Error: {result}"); return
            path, size_mb = result
            self._backup_log.append(f"✓ Backup created — {size_mb} MB → {Path(path).name}")
            self._adv_load_backups()
        self._run_in_thread("Creating backup…", _work, _done)

    def _adv_load_backups(self):
        if not _MGMT_OK: return
        backups = _mgmt.list_backups()
        self._backup_tbl.setRowCount(len(backups))
        for r, b in enumerate(backups):
            self._backup_tbl.setItem(r, 0, QTableWidgetItem(b["filename"]))
            self._backup_tbl.setItem(r, 1, QTableWidgetItem(b["created"]))
            self._backup_tbl.setItem(r, 2, QTableWidgetItem(str(b["size_mb"])))

    # ── Debug Logs panel ──────────────────────────────────────────────────

    def _build_debug_logs_panel(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8); lay.setSpacing(8)

        lay.addWidget(_label("🪲  Debug Logs", C["lavender"], bold=True))
        lay.addWidget(_label(
            "These files record every scraper error and timeout.  "
            "Send errors.txt + timeouts.txt to the developer when reporting a problem.",
            C["muted"], size=11))

        # ── File status row ───────────────────────────────────────────────
        status_row = QHBoxLayout()
        self._dbg_errors_lbl   = _label("errors.txt: —", C["red"],   size=11)
        self._dbg_timeout_lbl  = _label("timeouts.txt: —", C["amber"], size=11)
        status_row.addWidget(self._dbg_errors_lbl)
        status_row.addSpacing(16)
        status_row.addWidget(self._dbg_timeout_lbl)
        status_row.addStretch()
        lay.addLayout(status_row)

        # ── Action buttons ────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_open_errors = _btn("📂 Open errors.txt", C["red"], small=True)
        btn_open_errors.clicked.connect(lambda: self._dbg_open("errors"))
        btn_open_timeouts = _btn("📂 Open timeouts.txt", C["amber"], small=True)
        btn_open_timeouts.clicked.connect(lambda: self._dbg_open("timeouts"))
        btn_refresh = _btn("↺ Refresh", C["sky"], small=True)
        btn_refresh.clicked.connect(self._dbg_refresh)
        btn_clear = _btn("🗑 Clear Both Logs", C["red"], small=True)
        btn_clear.clicked.connect(self._dbg_clear)
        btn_row.addWidget(btn_open_errors)
        btn_row.addWidget(btn_open_timeouts)
        btn_row.addWidget(btn_refresh)
        btn_row.addStretch()
        btn_row.addWidget(btn_clear)
        lay.addLayout(btn_row)

        # ── Tab viewer ────────────────────────────────────────────────────
        viewer_tabs = QTabWidget()
        viewer_tabs.setStyleSheet(
            f"QTabBar::tab{{padding:4px 10px;font-size:11px;}}"
            f"QTabBar::tab:selected{{color:{C['amber']};border-bottom:2px solid {C['amber']};}}")

        self._dbg_errors_view = QPlainTextEdit()
        self._dbg_errors_view.setReadOnly(True)
        self._dbg_errors_view.setStyleSheet(
            f"background:{C['panel']};color:{C['red']};font-family:monospace;font-size:11px;"
            f"border:1px solid {C['border']};")
        viewer_tabs.addTab(self._dbg_errors_view, "❌  errors.txt")

        self._dbg_timeout_view = QPlainTextEdit()
        self._dbg_timeout_view.setReadOnly(True)
        self._dbg_timeout_view.setStyleSheet(
            f"background:{C['panel']};color:{C['amber']};font-family:monospace;font-size:11px;"
            f"border:1px solid {C['border']};")
        viewer_tabs.addTab(self._dbg_timeout_view, "⏱  timeouts.txt")

        lay.addWidget(viewer_tabs, 1)

        # Auto-refresh when tab is shown
        self._dbg_refresh()
        return w

    def _dbg_refresh(self):
        try:
            from abdl_logger import get_recent_errors, get_recent_timeouts, get_log_sizes, get_log_paths
        except ImportError:
            self._dbg_errors_view.setPlainText("abdl_logger.py not found in project folder.")
            return

        sizes = get_log_sizes()
        paths = get_log_paths()
        self._dbg_errors_lbl.setText(
            f"errors.txt: {sizes['errors']}  ({paths['errors']})")
        self._dbg_timeout_lbl.setText(
            f"timeouts.txt: {sizes['timeouts']}  ({paths['timeouts']})")

        err_lines = get_recent_errors(200)
        self._dbg_errors_view.setPlainText(
            "\n".join(err_lines) if err_lines else "(no errors logged yet)")
        sb = self._dbg_errors_view.verticalScrollBar(); sb.setValue(sb.maximum())

        to_lines = get_recent_timeouts(200)
        self._dbg_timeout_view.setPlainText(
            "\n".join(to_lines) if to_lines else "(no timeouts logged yet)")
        sb2 = self._dbg_timeout_view.verticalScrollBar(); sb2.setValue(sb2.maximum())

    def _dbg_open(self, which):
        try:
            from abdl_logger import get_log_paths
        except ImportError:
            return
        paths = get_log_paths()
        p = paths[which]
        if not p.exists():
            QMessageBox.information(self, "No log yet",
                f"{p.name} does not exist yet — no {which} have been recorded.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _dbg_clear(self):
        try:
            from abdl_logger import clear_logs, get_log_paths
        except ImportError:
            return
        paths = get_log_paths()
        names = "  •  ".join(p.name for p in paths.values())
        r = QMessageBox.question(self, "Clear Debug Logs",
            f"Delete the contents of:\n\n  {names}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Yes: return
        clear_logs()
        self._dbg_refresh()

    def _on_inner_tab(self, idx):
        # 0=Sites  1=Products  2=Images  3=Health  4=Advanced
        if   idx == 0: self.reload_sites()
        elif idx == 1: self._refresh_sources(); self._reload_products()
        elif idx == 2: self._refresh_images_tab()
        elif idx == 3: self._refresh_health()
        elif idx == 4: pass   # Advanced loads on demand

    def reload(self):
        """Called when tab becomes active."""
        self._on_inner_tab(0)


# ── Main Window ────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🐻 CrinkleDen — CDN")
        self.setMinimumSize(1280, 820)
        self.setStyleSheet(BASE_SS)

        # ── Title bar ─────────────────────────────────────────────────────────
        title_bar = QWidget()
        title_bar.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']};")
        tbl = QHBoxLayout(title_bar); tbl.setContentsMargins(16,8,16,8)
        tbl.addWidget(_label("🐻", size=22))
        tbl.addWidget(_label("CrinkleDen", C["amber"], bold=True, size=18))
        tbl.addSpacing(10)
        tbl.addWidget(_label("CDN v2.0", C["teal"], size=11))
        tbl.addStretch()

        # 🌙 / ☀ Theme toggle
        self._theme_btn = QPushButton("☀ Light" if _CURRENT_THEME == "dark" else "🌙 Dark")
        self._theme_btn.setFlat(True)
        self._theme_btn.setStyleSheet(
            f"QPushButton{{color:{C['muted']};font-size:11px;background:transparent;"
            f"border:1px solid {C['border']};border-radius:4px;padding:3px 8px;}}"
            f"QPushButton:hover{{color:{C['amber']};border-color:{C['amber']};}}")
        self._theme_btn.clicked.connect(self._toggle_theme)
        tbl.addWidget(self._theme_btn)
        tbl.addSpacing(8)

        # Update badge (hidden until checker fires)
        self._update_lbl = QLabel()
        self._update_lbl.setVisible(False)
        self._update_lbl.setStyleSheet(
            f"color:{C['bg']};background:{C['mint']};border-radius:8px;"
            f"padding:2px 8px;font-size:11px;font-weight:bold;")
        self._update_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        tbl.addWidget(self._update_lbl)
        tbl.addSpacing(8)

        self.status_lbl = _label("Loading…", C["muted"], size=12)
        tbl.addWidget(self.status_lbl)

        # ── Tabs ──────────────────────────────────────────────────────────────
        self.tabs         = QTabWidget()
        # ── Tabs — lazy loading ───────────────────────────────────────────────
        # Catalog tab is built immediately (it's the landing tab).
        # All other tabs are built on first click to cut startup time.
        self.catalog_tab  = CatalogTab()
        self.shopping_tab = None   # lazy
        self.scraper_tab  = None   # lazy
        self.db_tab       = None   # lazy
        self.dl_tab       = None   # lazy
        self.talker_tab   = None   # lazy

        self.tabs.addTab(self.catalog_tab,  "📦  Catalog")
        self.tabs.addTab(QWidget(),         "🛒  Shopping List")
        self.tabs.addTab(QWidget(),         "🌐  Scraper")
        self.tabs.addTab(QWidget(),         "🗄  Database")
        self.tabs.addTab(QWidget(),         "📥  Downloader")
        self.tabs.addTab(QWidget(),         "🍼  Talker")

        self.catalog_tab.request_add_to_list.connect(self._add_to_list)
        self.tabs.currentChanged.connect(self._on_tab)

        if DB_OK:
            _run_startup_hooks()

        central = QWidget()
        cl = QVBoxLayout(central); cl.setContentsMargins(0,0,0,0); cl.setSpacing(0)
        cl.addWidget(title_bar); cl.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self._update_status()
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(60_000)

        # ── Keyboard shortcuts ────────────────────────────────────────────────
        self._setup_shortcuts()

        # ── Auto-update check (non-blocking, 3s delay) ────────────────────────
        QTimer.singleShot(3000, self._check_for_updates)

        # ── Wishlist alert check on startup ───────────────────────────────────
        QTimer.singleShot(5000, self._check_wishlist_alerts)

    # ── Theme toggle ──────────────────────────────────────────────────────────

    def _toggle_theme(self):
        global C, _CURRENT_THEME, BASE_SS
        _CURRENT_THEME = "light" if _CURRENT_THEME == "dark" else "dark"
        C = C_LIGHT if _CURRENT_THEME == "light" else C_DARK
        _save_settings({**_load_settings(), "theme": _CURRENT_THEME})
        self._theme_btn.setText("☀ Light" if _CURRENT_THEME == "dark" else "🌙 Dark")
        # Rebuild stylesheet with new palette and apply
        new_ss = _build_stylesheet()
        QApplication.instance().setStyleSheet(new_ss)
        self.status_lbl.setText("🎨 Theme changed — restart for full effect")
        QTimer.singleShot(3000, self._update_status)

    # ── Auto-update checker ───────────────────────────────────────────────────

    def _check_for_updates(self):
        def _fetch():
            try:
                from urllib.request import urlopen, Request
                import json as _json
                req = Request(GITHUB_RELEASES, headers={
                    "User-Agent": "CrinkleDen-CDN/2.0",
                    "Accept": "application/vnd.github+json",
                })
                with urlopen(req, timeout=5) as r:
                    data = _json.loads(r.read())
                tag = data.get("tag_name", "").lstrip("v")
                url = data.get("html_url", "")
                return tag, url
            except Exception:
                return None, None

        def _done(result):
            tag, url = result
            if not tag: return
            try:
                remote = tuple(int(x) for x in tag.split(".")[:2])
                local  = tuple(int(x) for x in APP_VERSION.split(".")[:2])
                if remote > local:
                    self._update_lbl.setText(f"⬆ v{tag} available")
                    self._update_lbl.setVisible(True)
                    self._update_lbl.setToolTip(f"CrinkleDen v{tag} is available.\n{url}")
                    self._update_lbl.mousePressEvent = lambda e: (
                        __import__("webbrowser").open(url) if url else None
                    )
            except Exception:
                pass

        from concurrent.futures import ThreadPoolExecutor as _TPE
        _TPE(max_workers=1).submit(_fetch).add_done_callback(
            lambda f: QTimer.singleShot(0, lambda: _done(f.result()))
        )

    # ── Wishlist alert check ──────────────────────────────────────────────────

    def _check_wishlist_alerts(self):
        if not DB_OK: return
        try:
            alerts = db.get_wishlist_alerts()
        except Exception:
            return
        if not alerts:
            return
        names = [a["name"][:35] for a in alerts[:5]]
        msg = "\n".join(f"🔥 {n}" for n in names)
        if len(alerts) > 5:
            msg += f"\n…and {len(alerts)-5} more"
        box = QMessageBox(self)
        box.setWindowTitle("💰 Wishlist Price Alerts!")
        box.setText(f"<b>{len(alerts)} item(s) on your wishlist are on sale or hit your target price:</b>")
        box.setInformativeText(msg)
        box.setIcon(QMessageBox.Icon.Information)
        btn_view = box.addButton("❤️ View Wishlist", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Dismiss", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == btn_view:
            # Switch to catalog with wishlist filter on
            self.tabs.setCurrentIndex(0)
            self.catalog_tab.wishlist_chk.setChecked(True)
        # Mark all as notified
        for a in alerts:
            try:
                db.mark_wishlist_notified(a["wishlist_id"])
            except Exception:
                pass

    # ── Keyboard shortcuts ────────────────────────────────────────────────────

    def _setup_shortcuts(self):
        from PyQt6.QtGui import QShortcut, QKeySequence

        # / or Ctrl+F → focus search bar
        for seq in ("Ctrl+F", "/"):
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(lambda: (
                self.tabs.setCurrentIndex(0),
                self.catalog_tab.search.setFocus(),
                self.catalog_tab.search.selectAll(),
            ))

        # Ctrl+R → refresh catalog
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(
            self.catalog_tab.reload
        )

        # Ctrl+L → clear search
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(
            lambda: self.catalog_tab.search.clear()
        )

        # Ctrl+1-6 → switch tabs
        for i, seq in enumerate(["Ctrl+1","Ctrl+2","Ctrl+3","Ctrl+4","Ctrl+5","Ctrl+6"]):
            QShortcut(QKeySequence(seq), self).activated.connect(
                lambda idx=i: self.tabs.setCurrentIndex(idx)
            )

        # Escape → clear search if focused, else deselect
        QShortcut(QKeySequence("Escape"), self).activated.connect(
            lambda: self.catalog_tab.search.clear()
            if self.catalog_tab.search.hasFocus()
            else None
        )



    def _on_tab(self, idx):
        """Build the tab on first click (lazy), then reload."""
        # 0=Catalog  1=Shopping  2=Scraper  3=Database  4=Downloader  5=Talker

        if idx == 1 and self.shopping_tab is None:
            self.shopping_tab = ShoppingListTab()
            self.tabs.removeTab(1)
            self.tabs.insertTab(1, self.shopping_tab, "🛒  Shopping List")
            self.tabs.setCurrentIndex(1)
            # Wire scraper refresh signal if scraper already built
            if self.scraper_tab:
                self.scraper_tab.refresh_catalog.connect(self.shopping_tab.reload)

        elif idx == 2 and self.scraper_tab is None:
            self.scraper_tab = ScraperTab()
            self.tabs.removeTab(2)
            self.tabs.insertTab(2, self.scraper_tab, "🌐  Scraper")
            self.tabs.setCurrentIndex(2)
            # Wire all cross-tab signals
            self.scraper_tab.refresh_catalog.connect(self.catalog_tab.reload)
            self.scraper_tab.refresh_catalog.connect(self._update_status)
            self.scraper_tab.refresh_catalog.connect(self._check_wishlist_alerts)
            if self.shopping_tab:
                self.scraper_tab.refresh_catalog.connect(self.shopping_tab.reload)
            if self.db_tab:
                self.scraper_tab.refresh_catalog.connect(self.db_tab.reload_sites)
                self.db_tab.sites_changed.connect(self.scraper_tab._refresh_sites)
            if self.dl_tab:
                self.scraper_tab.refresh_catalog.connect(self.dl_tab.reload)

        elif idx == 3 and self.db_tab is None:
            self.db_tab = DBManagementTab()
            self.tabs.removeTab(3)
            self.tabs.insertTab(3, self.db_tab, "🗄  Database")
            self.tabs.setCurrentIndex(3)
            if self.scraper_tab:
                self.scraper_tab.refresh_catalog.connect(self.db_tab.reload_sites)
                self.db_tab.sites_changed.connect(self.scraper_tab._refresh_sites)

        elif idx == 4 and self.dl_tab is None:
            self.dl_tab = DownloaderTab()
            self.tabs.removeTab(4)
            self.tabs.insertTab(4, self.dl_tab, "📥  Downloader")
            self.tabs.setCurrentIndex(4)
            if self.scraper_tab:
                self.scraper_tab.refresh_catalog.connect(self.dl_tab.reload)

        elif idx == 5 and self.talker_tab is None:
            self.talker_tab = TalkerTab()
            self.tabs.removeTab(5)
            self.tabs.insertTab(5, self.talker_tab, "🍼  Talker")
            self.tabs.setCurrentIndex(5)

        # Call reload on already-built tabs
        tab_map = {
            1: self.shopping_tab,
            2: self.scraper_tab,
            3: self.db_tab,
            4: self.dl_tab,
            5: self.talker_tab,
        }
        tab = tab_map.get(idx)
        if tab and hasattr(tab, 'reload'):
            tab.reload()

    def _add_to_list(self, pid):
        # Ensure shopping tab is built before adding
        if self.shopping_tab is None:
            self._on_tab(1)
        self.shopping_tab.add_product(pid)
        self.tabs.setTabText(1, "🛒  Shopping List ✓")
        QTimer.singleShot(2000, lambda: self.tabs.setTabText(1, "🛒  Shopping List"))
        self._update_status()

    def _update_status(self):
        if not DB_OK:
            self.status_lbl.setText("⚠ DB error"); return
        try:
            s        = db.get_quick_status()
            due_txt  = f"  🔔{s['due']}"  if s['due']  else ""
            cart_txt = f"  🛒{s['cart']}" if s['cart'] else ""
            self.status_lbl.setText(
                f"📦{s['total']:,}  "
                f"🌟{s['abdl']}  "
                f"💊{s['medical']}"
                f"{due_txt}{cart_txt}")
        except Exception:
            pass

    def closeEvent(self, event):
        """Make sure scraper thread is stopped before the window closes."""
        if hasattr(self.scraper_tab, '_thread') and self.scraper_tab._thread:
            _stop_thread(self.scraper_tab._thread)
        event.accept()


# ══════════════════════════════════════════════════════════════════════════════
class DownloaderTab(QWidget):
    """
    Multi-site image downloader: e621, e926, Rule34, Danbooru, Gelbooru,
    Kemono, Pixiv — all free/open APIs.
    Downloads go directly into the image_library with auto-tagging.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self); root.setContentsMargins(12, 12, 12, 8); root.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.addWidget(_label("📥  Image Downloader", C["amber"], bold=True, size=15))
        hdr.addWidget(_label("— e621 · e926 · Rule34 · Danbooru · Gelbooru · Kemono · Pixiv",
                              C["muted"], size=11))
        hdr.addStretch()
        root.addLayout(hdr)

        body = QSplitter(Qt.Orientation.Horizontal)

        # ── left: site config ──────────────────────────────────────────────
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 4, 0)

        ll.addWidget(_label("Site", C["amber"], bold=True, size=12))
        self._site_cb = QComboBox()
        self._site_keys = list(DL_SITES.keys())
        for key, (label, _) in DL_SITES.items():
            self._site_cb.addItem(label, key)
        self._site_cb.currentIndexChanged.connect(self._on_site_change)
        ll.addWidget(self._site_cb)

        ll.addWidget(_label("Search / Tags", C["amber"], bold=True, size=12))
        self._query = QLineEdit()
        self._query.setPlaceholderText("e.g. diaper abdl rating:s")
        ll.addWidget(self._query)

        grid = QGridLayout(); grid.setSpacing(6)
        grid.addWidget(_label("Limit:", C["muted"], size=11), 0, 0)
        self._limit = QSpinBox(); self._limit.setRange(1, 500); self._limit.setValue(20)
        grid.addWidget(self._limit, 0, 1)
        grid.addWidget(_label("Page:", C["muted"], size=11), 1, 0)
        self._page = QSpinBox(); self._page.setRange(1, 100); self._page.setValue(1)
        grid.addWidget(self._page, 1, 1)
        ll.addLayout(grid)

        # credential section (shown/hidden by site)
        self._cred_box = QWidget()
        cl = QVBoxLayout(self._cred_box); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(4)
        cl.addWidget(_label("Credentials (optional)", C["muted"], bold=True, size=11))
        self._login_e   = QLineEdit(); self._login_e.setPlaceholderText("Username / login")
        self._apikey_e  = QLineEdit(); self._apikey_e.setPlaceholderText("API key")
        self._apikey_e.setEchoMode(QLineEdit.EchoMode.Password)
        self._token_e   = QLineEdit(); self._token_e.setPlaceholderText("Refresh token (Pixiv)")
        self._token_e.setEchoMode(QLineEdit.EchoMode.Password)
        btn_save_creds  = _btn("💾 Save Creds", C["muted"], small=True)
        btn_save_creds.clicked.connect(self._save_creds)
        for w in [self._login_e, self._apikey_e, self._token_e, btn_save_creds]:
            cl.addWidget(w)
        ll.addWidget(self._cred_box)
        ll.addStretch()

        # Kemono creator search
        self._kemono_box = QWidget()
        kl = QVBoxLayout(self._kemono_box); kl.setContentsMargins(0, 0, 0, 0)
        kl.addWidget(_label("Kemono Creator Search", C["teal"], bold=True, size=11))
        self._kemono_search = QLineEdit(); self._kemono_search.setPlaceholderText("Search creator name…")
        kl.addWidget(self._kemono_search)
        btn_ks = _btn("🔍 Find", C["teal"], small=True)
        btn_ks.clicked.connect(self._kemono_find)
        kl.addWidget(btn_ks)
        self._kemono_list = QListWidget(); self._kemono_list.setMaximumHeight(120)
        kl.addWidget(self._kemono_list)
        self._kemono_box.setVisible(False)
        ll.addWidget(self._kemono_box)

        btn_dl = _btn("⬇  Download to Library", C["mint"])
        btn_dl.setFixedHeight(36); btn_dl.clicked.connect(self._start_download)
        ll.addWidget(btn_dl)
        body.addWidget(left)

        # ── right: log + history ───────────────────────────────────────────
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(4, 0, 0, 0)
        rl.addWidget(_label("Download Log", C["amber"], bold=True, size=12))
        self._log = QPlainTextEdit(); self._log.setReadOnly(True)
        rl.addWidget(self._log, 1)
        self._prog = QProgressBar(); self._prog.setFixedHeight(5)
        self._prog.setTextVisible(False)
        rl.addWidget(self._prog)

        rl.addWidget(_label("Recent Jobs", C["amber"], bold=True, size=12))
        self._hist = QTableWidget(0, 6)
        self._hist.setHorizontalHeaderLabels(["Site","Query","Limit","Status","DL","At"])
        self._hist.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._hist.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._hist.setMaximumHeight(160)
        rl.addWidget(self._hist)
        body.addWidget(right)
        body.setSizes([300, 500])
        root.addWidget(body, 1)

        self._on_site_change(0)
        self._load_history()

    def _on_site_change(self, idx):
        site = self._site_cb.currentData()
        self._kemono_box.setVisible(site == "kemono")
        is_pixiv = site == "pixiv"
        self._token_e.setVisible(is_pixiv)
        self._login_e.setVisible(site not in ("rule34","kemono","gelbooru"))
        self._apikey_e.setVisible(site not in ("rule34","kemono","pixiv"))
        # load saved creds
        if DB_OK:
            try:
                creds = db.get_site_credentials(site)
                self._login_e.setText(creds.get("login") or "")
                self._apikey_e.setText(creds.get("api_key") or "")
                import json
                extra = json.loads(creds.get("extra") or "{}")
                self._token_e.setText(extra.get("refresh_token") or "")
            except Exception: pass

    def _save_creds(self):
        site = self._site_cb.currentData()
        if not DB_OK: return
        import json
        extra = {}
        if self._token_e.text().strip():
            extra["refresh_token"] = self._token_e.text().strip()
        db.save_site_credentials(
            site,
            login=self._login_e.text().strip() or None,
            api_key=self._apikey_e.text().strip() or None,
            extra=extra or None)
        self._log.appendPlainText(f"✓ Credentials saved for {site}")

    def _kemono_find(self):
        q = self._kemono_search.text().strip()
        if not q: return
        self._kemono_list.clear()
        self._log.appendPlainText(f"Searching Kemono creators for '{q}'…")

        class _W(QObject):
            done = pyqtSignal(list)
            def __init__(self, q): super().__init__(); self.q = q
            def run(self):
                try:
                    r = _KemonoClient().get_creators(self.q, limit=30)
                    self.done.emit(r)
                except Exception as e:
                    self.done.emit([])
        t = QThread(); w = _W(q); w.moveToThread(t); t.started.connect(w.run)
        w.done.connect(lambda r: [
            self._kemono_list.addItem(
                f"{c.get('service','')} / {c.get('name','')} [{c.get('id','')}]")
            for c in r] or self._kemono_list.addItem("No results"))
        w.done.connect(lambda *_: t.quit()); t.start()

    def _start_download(self):
        site  = self._site_cb.currentData()
        query = self._query.text().strip()
        if not query and site != "kemono":
            QMessageBox.information(self, "Empty", "Enter search tags first."); return

        # Kemono: get creator from list
        kemono_service = kemono_cid = None
        if site == "kemono":
            sel = self._kemono_list.currentItem()
            if not sel:
                QMessageBox.information(self, "Kemono", "Select a creator from the list first."); return
            parts = sel.text().split("/")
            kemono_service = parts[0].strip()
            kemono_cid     = parts[-1].strip().strip("]").strip()
            query = f"{kemono_service}/{kemono_cid}"

        limit = self._limit.value()
        creds = {
            "login":         self._login_e.text().strip() or None,
            "api_key":       self._apikey_e.text().strip() or None,
            "refresh_token": self._token_e.text().strip() or None,
        }
        creds = {k: v for k, v in creds.items() if v}

        job_id = db.create_download_job(site, query, limit) if DB_OK else None
        self._log.clear()
        self._log.appendPlainText(f"⬇ Starting: {site} | {query} | limit {limit}")
        self._prog.setRange(0, limit); self._prog.setValue(0)

        class _DLWorker(QObject):
            progress = pyqtSignal(str)
            done     = pyqtSignal(int, int, int)   # downloaded, dupes, errors

            def __init__(self, site, query, limit, creds, ks, kcid):
                super().__init__()
                self.site=site; self.query=query; self.limit=limit
                self.creds=creds; self.ks=ks; self.kcid=kcid

            def run(self):
                from downloader import make_client
                downloaded = dupes = errors = 0
                try:
                    client = make_client(self.site, self.creds)
                    if self.site == "kemono" and self.ks and self.kcid:
                        results = client.download_all(self.ks, self.kcid,
                                                      limit=self.limit,
                                                      callback=self.progress.emit)
                    else:
                        results = client.download_all(self.query, limit=self.limit,
                                                      callback=self.progress.emit)
                    for r in results:
                        if r.error:
                            errors += 1
                            self.progress.emit(f"  ✗ {r.post_id}: {r.error}"); continue
                        if not r.image_data:
                            errors += 1; continue
                        fname = f"{r.site}_{r.post_id}.{r.file_ext or 'jpg'}"
                        iid, status = db.add_library_image(
                            image_data=r.image_data,
                            image_url=r.file_url,
                            filename=fname,
                            mime_type=_mime("."+r.file_ext) if r.file_ext else "image/jpeg",
                            width=r.width, height=r.height,
                            source_url=r.source_url,
                            source_name=r.site,
                            notes=f"artist:{r.artist}" if r.artist else None)
                        if status == "added":
                            downloaded += 1
                            # auto-tag from API tags
                            if r.tags and DB_OK:
                                tag_words = r.tags.split()[:30]
                                for tag_w in tag_words:
                                    if len(tag_w) > 1:
                                        tid = db.get_or_create_tag(tag_w.lower())
                                        if tid: db.add_image_tag(iid, tid)
                        else:
                            dupes += 1
                except Exception as e:
                    self.progress.emit(f"✗ Fatal: {e}")
                    errors += 1
                self.done.emit(downloaded, dupes, errors)

        t = QThread()
        w = _DLWorker(site, query, limit, creds, kemono_service, kemono_cid)
        w.moveToThread(t); t.started.connect(w.run)
        w.progress.connect(self._log.appendPlainText)
        _dl_count = [0]
        def _on_prog(msg):
            if "⬇" in msg: _dl_count[0] += 1; self._prog.setValue(_dl_count[0])
        w.progress.connect(_on_prog)
        w.done.connect(lambda a, d, e: (
            self._log.appendPlainText(f"\n✓ Downloaded:{a}  Dupes:{d}  Errors:{e}"),
            db.update_download_job(job_id, status="done", downloaded=a,
                                   duplicates=d, errors=e) if job_id else None,
            self._load_history()))
        w.done.connect(lambda *_: t.quit())
        t.finished.connect(lambda: setattr(self, '_thread', None))
        self._thread = t; t.start()

    def _load_history(self):
        if not DB_OK: return
        try: jobs = db.get_download_jobs(20)
        except Exception: return
        self._hist.setRowCount(len(jobs))
        for i, j in enumerate(jobs):
            for c, k in enumerate(["site","query","limit_n","status","downloaded","started_at"]):
                v = str(j.get(k, ""))[:30]
                self._hist.setItem(i, c, QTableWidgetItem(v))

    def reload(self):
        self._load_history()


# ══════════════════════════════════════════════════════════════════════════════
#  TODDLER TALKER TAB
# ══════════════════════════════════════════════════════════════════════════════
class TalkerTab(QWidget):
    """
    🍼 Toddler Talker — converts adult text into littlespace / age-regression speech.
    Powered by talker.py (6 modes, 200+ rules). Saves history + presets to DB.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self._load_history()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.addWidget(_label("🍼 Toddler Talker", C["pink"], bold=True, size=15))
        hdr.addWidget(_label("— powered by talker.py", C["muted"], size=10))
        hdr.addStretch()
        if not _TALKER_OK:
            warn = _label("⚠ talker.py not found — using fallback", C["red"], size=10)
            hdr.addWidget(warn)
        root.addLayout(hdr)

        # ── Controls row ──────────────────────────────────────────────────────
        ctrl = QHBoxLayout(); ctrl.setSpacing(8)

        ctrl.addWidget(_label("Mode:", C["amber"], size=12))
        self._mode_cb = QComboBox()
        self._mode_cb.setMinimumWidth(280)
        self._mode_cb.setFixedHeight(30)
        if _TALKER_OK:
            for key, label, desc in _talker_modes():
                self._mode_cb.addItem(f"{label}  —  {desc}", key)
        else:
            for key, lbl in [("little","🍼 Little Space"),("tiny","👶 Tiny Baby"),
                              ("sweet","🌸 Sweet & Soft"),("uwu","🐾 UwU / OwO"),
                              ("lisped","😛 Lisped"),("babble","🐣 Baby Babble")]:
                self._mode_cb.addItem(lbl, key)
        self._mode_cb.currentIndexChanged.connect(self._on_mode_changed)
        ctrl.addWidget(self._mode_cb)

        ctrl.addSpacing(8)
        self._endings_cb   = QCheckBox("Endings~")
        self._starters_cb  = QCheckBox("Starters")
        self._endings_cb.setChecked(True)
        self._starters_cb.setChecked(True)
        self._endings_cb.setToolTip("Add tilde/uwu/~ endings to sentences")
        self._starters_cb.setToolTip("Randomly add *giggles* / hehe~ starters")
        ctrl.addWidget(self._endings_cb)
        ctrl.addWidget(self._starters_cb)

        ctrl.addSpacing(8)
        self._auto_cb = QCheckBox("Live")
        self._auto_cb.setToolTip("Transform as you type (600ms debounce)")
        self._auto_cb.toggled.connect(self._on_auto_toggle)
        ctrl.addWidget(self._auto_cb)

        ctrl.addStretch()

        btn_tf = _btn("✨ Transform!", C["pink"])
        btn_tf.setFixedHeight(32)
        btn_tf.clicked.connect(self._transform)
        ctrl.addWidget(btn_tf)
        root.addLayout(ctrl)

        # ── Main splitter: left=editor, right=sidebar ─────────────────────────
        main_split = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: input / output ──────────────────────────────────────────────
        edit_w = QWidget()
        el = QVBoxLayout(edit_w); el.setContentsMargins(0,0,4,0); el.setSpacing(6)

        io_split = QSplitter(Qt.Orientation.Vertical)

        in_w = QWidget(); il = QVBoxLayout(in_w); il.setContentsMargins(0,0,0,0); il.setSpacing(4)
        in_hdr = QHBoxLayout()
        in_hdr.addWidget(_label("✏ Input", C["amber"], bold=True, size=12))
        in_hdr.addStretch()
        btn_clear_in = _btn("🗑", C["muted"], flat=True, small=True)
        btn_clear_in.setFixedWidth(28)
        btn_clear_in.setToolTip("Clear input")
        btn_clear_in.clicked.connect(lambda: (self._input.clear(), self._output.clear()))
        in_hdr.addWidget(btn_clear_in)
        il.addLayout(in_hdr)
        self._input = QTextEdit()
        self._input.setPlaceholderText(
            "Type or paste text here…\n\n"
            "Example: I really love wearing diapers and feeling safe.")
        self._input.textChanged.connect(self._on_input_change)
        il.addWidget(self._input, 1)
        io_split.addWidget(in_w)

        out_w = QWidget(); ol = QVBoxLayout(out_w); ol.setContentsMargins(0,0,0,0); ol.setSpacing(4)
        out_hdr = QHBoxLayout()
        out_hdr.addWidget(_label("🍼 Output", C["pink"], bold=True, size=12))
        out_hdr.addStretch()
        btn_copy = _btn("📋 Copy", C["teal"], small=True)
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(
            self._output.toPlainText()))
        btn_save_hist = _btn("💾 Save", C["lavender"], small=True)
        btn_save_hist.setToolTip("Save this transform to history")
        btn_save_hist.clicked.connect(self._save_to_history)
        out_hdr.addWidget(btn_copy); out_hdr.addWidget(btn_save_hist)
        ol.addLayout(out_hdr)
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet(
            f"background:{C['panel']};color:{C['pink']};font-size:14px;"
            f"border:1px solid {C['pink']}44;border-radius:6px;padding:10px;")
        ol.addWidget(self._output, 1)
        io_split.addWidget(out_w)

        io_split.setSizes([250, 250])
        el.addWidget(io_split, 1)

        # Quick examples
        ex_row = QHBoxLayout(); ex_row.setSpacing(4)
        ex_row.addWidget(_label("Try:", C["muted"], size=10))
        for lbl, txt in [
            ("Shopping",  "I need to buy more diapers and wipes. I am running low on powder too."),
            ("Feelings",  "I feel anxious today and really need comfort. I want to curl up with my blanket and stuffed animal."),
            ("Activity",  "I want to play video games and watch cartoons all day. I am very excited and happy."),
            ("Needy",     "Please hold me and do not let go. I need you to take care of me and keep me safe."),
        ]:
            b = _btn(lbl, C["lavender"], flat=True, small=True)
            b.clicked.connect(lambda _, t=txt: self._input.setPlainText(t))
            ex_row.addWidget(b)
        ex_row.addStretch()
        el.addLayout(ex_row)
        main_split.addWidget(edit_w)

        # ── Right sidebar: presets + history ─────────────────────────────────
        sidebar = QWidget()
        sl = QVBoxLayout(sidebar); sl.setContentsMargins(4,0,0,0); sl.setSpacing(6)

        # Presets
        sl.addWidget(_label("📌 Presets", C["amber"], bold=True, size=12))
        self._preset_list = QListWidget()
        self._preset_list.setMaximumHeight(140)
        self._preset_list.setStyleSheet(
            f"background:{C['panel2']};border:1px solid {C['border']};"
            f"color:{C['white']};font-size:11px;")
        self._preset_list.itemDoubleClicked.connect(self._load_preset)
        sl.addWidget(self._preset_list)

        preset_btns = QHBoxLayout(); preset_btns.setSpacing(4)
        btn_save_preset = _btn("💾 Save Preset", C["mint"], small=True)
        btn_save_preset.clicked.connect(self._save_preset)
        btn_del_preset = _btn("🗑 Delete", C["red"], flat=True, small=True)
        btn_del_preset.clicked.connect(self._delete_preset)
        preset_btns.addWidget(btn_save_preset)
        preset_btns.addWidget(btn_del_preset)
        preset_btns.addStretch()
        sl.addLayout(preset_btns)

        sl.addWidget(_sep())

        # History
        hist_hdr = QHBoxLayout()
        hist_hdr.addWidget(_label("🕐 History", C["amber"], bold=True, size=12))
        hist_hdr.addStretch()
        btn_clear_hist = _btn("🗑 Clear", C["red"], flat=True, small=True)
        btn_clear_hist.clicked.connect(self._clear_history)
        hist_hdr.addWidget(btn_clear_hist)
        sl.addLayout(hist_hdr)

        self._hist_list = QListWidget()
        self._hist_list.setStyleSheet(
            f"background:{C['panel2']};border:1px solid {C['border']};"
            f"color:{C['white']};font-size:10px;")
        self._hist_list.itemDoubleClicked.connect(self._load_from_history)
        sl.addWidget(self._hist_list, 1)

        # Stats
        self._stats_lbl = _label("", C["muted"], size=9)
        sl.addWidget(self._stats_lbl)

        main_split.addWidget(sidebar)
        main_split.setSizes([680, 280])
        root.addWidget(main_split, 1)

        # Mode description label
        self._mode_desc = _label("", C["muted"], size=10)
        self._mode_desc.setWordWrap(True)
        root.addWidget(self._mode_desc)
        self._on_mode_changed()

        # Timer for live mode
        self._auto_timer = QTimer()
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._transform)

    # ── Mode change ───────────────────────────────────────────────────────────

    def _on_mode_changed(self):
        mode = self._mode_cb.currentData() or "little"
        if _TALKER_OK:
            try:
                info = __import__("talker").mode_info(mode)
                self._mode_desc.setText(
                    f"{info.get('label','')}  —  {info.get('description','')}")
            except Exception:
                pass

    # ── Transform ─────────────────────────────────────────────────────────────

    def _on_auto_toggle(self, checked):
        if checked:
            self._transform()

    def _on_input_change(self):
        if self._auto_cb.isChecked():
            self._auto_timer.start(600)

    def _transform(self):
        text = self._input.toPlainText().strip()
        if not text:
            return
        mode = self._mode_cb.currentData() or "little"
        add_endings  = self._endings_cb.isChecked()
        add_starters = self._starters_cb.isChecked()

        if _TALKER_OK:
            result = _talker_transform(
                text, mode,
                add_endings=add_endings,
                add_starters=add_starters,
            )
        else:
            result = self._fallback_transform(text)

        self._output.setPlainText(result)

        # Auto-save to DB history
        if DB_OK and text and result:
            try:
                db.talker_save_history(mode, text, result)
                self._load_history()
            except Exception:
                pass

    def _fallback_transform(self, text: str) -> str:
        """Minimal built-in fallback if talker.py is missing."""
        subs = [
            (r'\blittle\b','wittle'),(r'\blove\b','wuv'),(r'\breally\b','weally'),
            (r'\bplease\b','pwease'),(r'\bdiaper(s)?\b','diapies'),
            (r'\bbathroom\b','potty'),(r'\byes\b','yesh!'),(r'\bvery\b','vewy'),
            (r'\bwant\b','wan'),(r'\bfeel\b','feew'),(r'\bsafe\b','safies'),
            (r'\bcomfort(able)?\b','comfies'),(r'\bhug(s)?\b','huggieeees'),
            (r'\bsorry\b','sowwy'),(r'\bthank(s)?\b','fanks'),
        ]
        import re as _re
        for pat, rep in subs:
            text = _re.sub(pat, rep, text, flags=_re.IGNORECASE)
        return text + "~"

    # ── History ───────────────────────────────────────────────────────────────

    def _load_history(self):
        if not DB_OK:
            return
        try:
            rows = db.talker_get_history(limit=60)
        except Exception:
            return
        self._hist_list.clear()
        for row in rows:
            preview_in  = row["input_text"][:30].replace("\n"," ")
            preview_out = row["output_text"][:30].replace("\n"," ")
            item = QListWidgetItem(
                f"[{row['mode']}]  {preview_in}…\n  → {preview_out}…")
            item.setData(Qt.ItemDataRole.UserRole, row)
            item.setToolTip(
                f"Mode: {row['mode']}\n"
                f"IN:  {row['input_text'][:200]}\n"
                f"OUT: {row['output_text'][:200]}")
            self._hist_list.addItem(item)
        # Update stats
        try:
            stats = db.talker_get_stats()
            by_mode = "  ".join(f"{m}:{n}" for m,n in stats["by_mode"].items())
            self._stats_lbl.setText(
                f"Total: {stats['total_transforms']}  |  {by_mode}  |  Presets: {stats['saved_presets']}")
        except Exception:
            pass

    def _load_from_history(self, item):
        row = item.data(Qt.ItemDataRole.UserRole)
        if not row:
            return
        self._input.setPlainText(row["input_text"])
        self._output.setPlainText(row["output_text"])
        # Set mode in dropdown
        for i in range(self._mode_cb.count()):
            if self._mode_cb.itemData(i) == row["mode"]:
                self._mode_cb.setCurrentIndex(i)
                break

    def _save_to_history(self):
        text = self._input.toPlainText().strip()
        out  = self._output.toPlainText().strip()
        if not text or not out:
            return
        mode = self._mode_cb.currentData() or "little"
        if DB_OK:
            try:
                db.talker_save_history(mode, text, out)
                self._load_history()
            except Exception:
                pass

    def _clear_history(self):
        if not DB_OK:
            return
        reply = QMessageBox.question(
            self, "Clear History?",
            "Delete all saved transform history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            db.talker_clear_history()
            self._load_history()
        except Exception:
            pass

    # ── Presets ───────────────────────────────────────────────────────────────

    def _load_presets(self):
        if not DB_OK:
            return
        try:
            presets = db.talker_get_presets()
        except Exception:
            return
        self._preset_list.clear()
        for p in presets:
            preview = p["input_text"][:40].replace("\n", " ")
            item = QListWidgetItem(f"[{p['mode']}] {p['name']}\n  {preview}…")
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p["input_text"][:300])
            self._preset_list.addItem(item)

    def _save_preset(self):
        text = self._input.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "No Input", "Type some input text first.")
            return
        name, ok = QInputDialog.getText(
            self, "Save Preset", "Preset name:",
            text=text[:30].replace("\n", " "))
        if not ok or not name.strip():
            return
        mode = self._mode_cb.currentData() or "little"
        if DB_OK:
            try:
                db.talker_save_preset(name.strip(), text, mode)
                self._load_presets()
                self._load_history()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _load_preset(self, item):
        p = item.data(Qt.ItemDataRole.UserRole)
        if not p:
            return
        self._input.setPlainText(p["input_text"])
        for i in range(self._mode_cb.count()):
            if self._mode_cb.itemData(i) == p.get("mode", "little"):
                self._mode_cb.setCurrentIndex(i)
                break
        self._transform()

    def _delete_preset(self):
        item = self._preset_list.currentItem()
        if not item:
            return
        p = item.data(Qt.ItemDataRole.UserRole)
        if not p or not DB_OK:
            return
        try:
            db.talker_delete_preset(p["id"])
            self._load_presets()
        except Exception:
            pass

    def reload(self):
        self._load_history()
        self._load_presets()


# ── Entry point ────────────────────────────────────────────────────────────


class PlaywrightInstallDialog(QDialog):
    """
    Shown on startup when running as a bundled exe and Playwright/Chromium
    is missing.  Lets the user install it without leaving the app.
    """
    def __init__(self, reason="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌐 Scraper Setup Required")
        self.setMinimumWidth(520)
        self.setStyleSheet(BASE_SS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        lay.addWidget(_label("Scraper Not Ready", C["amber"], bold=True, size=16))
        lay.addWidget(_sep())

        msg = (
            "The product scraper requires a Chromium browser, which was not "
            "found on this computer.\n\n"
            f"Reason: {reason or 'playwright or Chromium not installed'}\n\n"
            "You can install it now (requires an internet connection and Python "
            "to be in your PATH), or skip and use the app without the scraper."
        )
        lbl = QLabel(msg)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{C['white']};font-size:13px;background:transparent;")
        lay.addWidget(lbl)

        # Install command display
        cmd_frame = QFrame()
        cmd_frame.setStyleSheet(
            f"background:{C['panel']};border:1px solid {C['amber']}44;border-radius:5px;")
        cfl = QVBoxLayout(cmd_frame); cfl.setContentsMargins(12, 8, 12, 8)
        cfl.addWidget(_label("Installation commands (open a Command Prompt and run):",
                             C["muted"], size=11))
        for cmd in ["pip install playwright", "playwright install chromium"]:
            code = QLabel(cmd)
            code.setStyleSheet(
                f"color:{C['mint']};font-family:Consolas,monospace;font-size:12px;"
                f"background:{C['panel2']};padding:4px 8px;border-radius:3px;")
            code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cfl.addWidget(code)
        lay.addWidget(cmd_frame)

        # Auto-install button (tries to run pip in background)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setVisible(False)
        self._log.setStyleSheet(
            f"background:{C['panel']};color:{C['mint']};font-family:Consolas,monospace;"
            f"font-size:11px;border:1px solid {C['border']};")
        lay.addWidget(self._log)

        btn_row = QHBoxLayout()
        self._btn_install = _btn("⬇  Auto-Install Playwright", C["mint"])
        self._btn_install.clicked.connect(self._do_install)
        btn_row.addWidget(self._btn_install)
        btn_row.addStretch()
        btn_skip = _btn("Skip — Continue Without Scraper", C["muted"], flat=True)
        btn_skip.clicked.connect(self.accept)
        btn_row.addWidget(btn_skip)
        lay.addLayout(btn_row)

        self._worker = None

    def _do_install(self):
        self._log.setVisible(True)
        self._btn_install.setEnabled(False)
        self._btn_install.setText("⏳ Installing…")
        self._log.append("Starting installation…\n")

        class _Worker(QObject):
            line   = pyqtSignal(str)
            done   = pyqtSignal(bool, str)

            @pyqtSlot()
            def run(self):
                import subprocess, sys
                steps = [
                    [sys.executable, "-m", "pip", "install", "playwright"],
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                ]
                for cmd in steps:
                    self.line.emit(f"$ {' '.join(cmd)}\n")
                    try:
                        proc = subprocess.Popen(
                            cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
                        for out_line in proc.stdout:
                            self.line.emit(out_line)
                        proc.wait()
                        if proc.returncode != 0:
                            self.done.emit(False, f"Command failed: {' '.join(cmd)}")
                            return
                    except Exception as e:
                        self.done.emit(False, str(e))
                        return
                self.done.emit(True, "")

        worker = _Worker()
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.line.connect(lambda l: (self._log.insertPlainText(l),
                                       self._log.verticalScrollBar().setValue(
                                           self._log.verticalScrollBar().maximum())))
        worker.done.connect(self._on_done)
        worker.done.connect(lambda _ok, _msg: thread.quit())
        thread.finished.connect(thread.deleteLater)
        self._worker = worker
        self._thread = thread
        thread.start()

    def _on_done(self, success, msg):
        if success:
            self._btn_install.setText("✓ Playwright Installed!")
            self._log.append("\n✓ Done — please restart the app to enable the scraper.")
            _btn_ok = _btn("Restart Now", C["mint"])
            _btn_ok.clicked.connect(lambda: (self.accept(),
                                             QProcess.startDetached(sys.executable, sys.argv)))
            self.layout().addWidget(_btn_ok)
        else:
            self._btn_install.setEnabled(True)
            self._btn_install.setText("⬇  Retry Install")
            self._log.append(f"\n✗ Failed: {msg}\nTry installing manually (see commands above).")


def _check_frozen_playwright():
    """
    In a bundled exe, check the env var set by runtime_hook_playwright.py.
    Returns (ready: bool, reason: str).
    """
    import os
    ready  = os.environ.get("ABDL_PLAYWRIGHT_READY", "1") == "1"
    reason = os.environ.get("ABDL_PLAYWRIGHT_REASON", "")
    return ready, reason


def main():
    if DB_OK:
        try:
            db.init_db()
        except Exception as e:
            print(f"[init_db] {e}")
        # Guarantee image_library tables exist even if init_db had a hiccup
        try:
            db.ensure_library_tables()
        except Exception as e:
            print(f"[ensure_library_tables] {e}")

    app = QApplication(sys.argv)
    app.setApplicationName("CrinkleDen")
    app.setStyle("Fusion")

    pal = QPalette()
    for role, color in [
        (QPalette.ColorRole.Window,           C["bg"]),
        (QPalette.ColorRole.WindowText,       C["white"]),
        (QPalette.ColorRole.Base,             C["panel"]),
        (QPalette.ColorRole.Text,             C["white"]),
        (QPalette.ColorRole.Button,           C["panel2"]),
        (QPalette.ColorRole.ButtonText,       C["white"]),
        (QPalette.ColorRole.Highlight,        C["lavender"]),
        (QPalette.ColorRole.HighlightedText,  C["bg"]),
    ]:
        pal.setColor(role, QColor(color))
    app.setPalette(pal)

    # In bundled exe: show Playwright install dialog if scraper is broken
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        pw_ready, pw_reason = _check_frozen_playwright()
        if not pw_ready:
            dlg = PlaywrightInstallDialog(reason=pw_reason)
            dlg.exec()   # non-blocking — user can skip

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
