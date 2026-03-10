"""
ABDL Catalog System — ui.py
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

try:
    import database as db
    DB_OK = True
except Exception as _e:
    print(f"[WARN] database: {_e}")
    DB_OK = False

try:
    from scraper import (seed_demo_data, scrape_all, scrape_site_by_id,
                         SCRAPE_AVAILABLE, PLAYWRIGHT_AVAILABLE, MAX_CONCURRENT)
except Exception as _e:
    print(f"[WARN] scraper: {_e}")
    SCRAPE_AVAILABLE = PLAYWRIGHT_AVAILABLE = False
    MAX_CONCURRENT = 4
    def seed_demo_data(pcb=None, force=False): return 0
    def scrape_all(**kw): return []
    def scrape_site_by_id(sid, **kw): return {}

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QTextEdit, QDialog, QFrame, QSplitter, QProgressBar,
    QAbstractItemView, QSlider, QSpinBox, QFileDialog,
    QMessageBox, QDoubleSpinBox
)
from PyQt6.QtCore  import Qt, QThread, QObject, pyqtSignal, pyqtSlot, QTimer, QUrl, QProcess
from PyQt6.QtGui   import QColor, QPalette, QDesktopServices

# ── Palette ────────────────────────────────────────────────────────────────
C = {
    "bg":"#130d1e","panel":"#1e1030","panel2":"#271540","card":"#2a1845",
    "border":"#3d2060","pink":"#FF9DC4","lavender":"#C8A8FF","mint":"#7FFFD4",
    "sky":"#87CEEB","yellow":"#FFE47A","peach":"#FFCBA4","white":"#F0E6FF",
    "muted":"#8070A0","green":"#5DADE2","red":"#FF6B6B",
    "abdl_c":"#C8A8FF","med_c":"#87CEEB","both_c":"#7FFFD4","gold":"#FFD700",
}

BASE_SS = (
    f"QMainWindow,QDialog{{background:{C['bg']};}}"
    f"QWidget{{background:{C['bg']};color:{C['white']};font-family:'Segoe UI',sans-serif;font-size:13px;}}"
    f"QTabWidget::pane{{border:1px solid {C['border']};background:{C['panel']};border-radius:6px;}}"
    f"QTabBar::tab{{background:{C['panel2']};color:{C['muted']};padding:8px 18px;border-radius:4px 4px 0 0;margin-right:2px;}}"
    f"QTabBar::tab:selected{{background:{C['panel']};color:{C['pink']};border-bottom:2px solid {C['pink']};}}"
    f"QTabBar::tab:hover{{color:{C['white']};}}"
    f"QLineEdit{{background:{C['panel2']};border:1px solid {C['border']};border-radius:6px;color:{C['white']};padding:6px 10px;}}"
    f"QLineEdit:focus{{border-color:{C['lavender']};}}"
    f"QComboBox{{background:{C['panel2']};border:1px solid {C['border']};border-radius:6px;color:{C['white']};padding:5px 10px;min-width:110px;}}"
    f"QComboBox::drop-down{{border:none;width:22px;}}"
    f"QComboBox QAbstractItemView{{background:{C['panel2']};color:{C['white']};selection-background-color:{C['border']};}}"
    f"QSpinBox,QDoubleSpinBox{{background:{C['panel2']};border:1px solid {C['border']};border-radius:6px;color:{C['white']};padding:4px 8px;}}"
    f"QSpinBox::up-button,QSpinBox::down-button,QDoubleSpinBox::up-button,QDoubleSpinBox::down-button{{background:{C['border']};border-radius:3px;width:18px;}}"
    f"QCheckBox{{color:{C['white']};spacing:6px;}}"
    f"QCheckBox::indicator{{width:15px;height:15px;border:1px solid {C['border']};border-radius:3px;background:{C['panel2']};}}"
    f"QCheckBox::indicator:checked{{background:{C['lavender']};border-color:{C['lavender']};}}"
    f"QTableWidget{{background:{C['panel']};gridline-color:{C['border']};color:{C['white']};border:1px solid {C['border']};border-radius:4px;alternate-background-color:{C['panel2']};}}"
    f"QTableWidget::item{{padding:4px 8px;}}"
    f"QTableWidget::item:selected{{background:{C['border']};color:{C['white']};}}"
    f"QHeaderView::section{{background:{C['panel2']};color:{C['lavender']};padding:6px 8px;border:none;border-right:1px solid {C['border']};border-bottom:1px solid {C['border']};font-weight:bold;}}"
    f"QScrollBar:vertical{{background:{C['panel2']};width:10px;border-radius:5px;}}"
    f"QScrollBar::handle:vertical{{background:{C['border']};border-radius:5px;min-height:30px;}}"
    f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
    f"QScrollBar:horizontal{{background:{C['panel2']};height:10px;border-radius:5px;}}"
    f"QScrollBar::handle:horizontal{{background:{C['border']};border-radius:5px;}}"
    f"QTextEdit{{background:{C['panel2']};border:1px solid {C['border']};border-radius:6px;color:{C['mint']};font-family:'Consolas','Courier New',monospace;font-size:12px;padding:6px;}}"
    f"QProgressBar{{background:{C['panel2']};border:1px solid {C['border']};border-radius:4px;height:8px;}}"
    f"QProgressBar::chunk{{background:{C['lavender']};border-radius:4px;}}"
    f"QSplitter::handle{{background:{C['border']};}}"
)

def _btn(text, color=None, flat=False, small=False):
    b = QPushButton(text); fg = color or C["pink"]
    pad = "6px 14px" if small else "8px 20px"; fs = "12px" if small else "13px"
    b.setStyleSheet(
        f"QPushButton{{background:{'transparent' if flat else C['panel2']};color:{fg};"
        f"border:{'none' if flat else f'1px solid {fg}'};"
        f"border-radius:6px;padding:{pad};font-size:{fs};font-weight:bold;}}"
        f"QPushButton:hover{{background:{C['border']};color:{C['white']};}}"
        f"QPushButton:pressed{{background:{fg};color:{C['bg']};}}"
        f"QPushButton:disabled{{color:{C['muted']};border-color:{C['muted']};}}")
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
        self.setWindowTitle(p.get("name","Product"))
        self.setMinimumSize(620, 480)
        self.setStyleSheet(BASE_SS)
        root = QVBoxLayout(self); root.setContentsMargins(20,20,20,20); root.setSpacing(10)

        hdr = QHBoxLayout()
        hdr.addWidget(_label(p.get("name",""), C["pink"], bold=True, size=16))
        hdr.addStretch()
        btype = (p.get("brand_type") or "abdl").upper(); tc = _type_color(btype.lower())
        badge = _label(f"  {btype}  ","")
        badge.setStyleSheet(f"color:{C['bg']};background:{tc};border-radius:10px;padding:2px 8px;font-weight:bold;")
        hdr.addWidget(badge); root.addLayout(hdr); root.addWidget(_sep())

        pr = QHBoxLayout()
        price = p.get("display_price") or p.get("price_usd") or p.get("price")
        if price: pr.addWidget(_label(f"${price:.2f}", C["mint"], bold=True, size=22))
        pr.addSpacing(16)
        if p.get("brand_name"):    pr.addWidget(_label(f"🏷 {p['brand_name']}", C["lavender"]))
        if p.get("category_name"): pr.addWidget(_label(f"  {p.get('category_icon','')} {p['category_name']}", C["yellow"]))
        pr.addStretch(); root.addLayout(pr)

        fl = QHBoxLayout()
        if p.get("discreet_shipping") or p.get("b_discreet"):
            b = _label("  📦 Discreet Shipping  ","")
            b.setStyleSheet(f"background:{C['green']};color:{C['bg']};border-radius:10px;padding:2px 10px;font-weight:bold;")
            fl.addWidget(b)
        if p.get("free_sample") or p.get("b_free_sample"):
            b = _label("  🎁 Free Sample  ","")
            b.setStyleSheet(f"background:{C['mint']};color:{C['bg']};border-radius:10px;padding:2px 10px;font-weight:bold;")
            fl.addWidget(b)
        fl.addWidget(_label("● In Stock" if p.get("in_stock") else "● Out of Stock",
                             C["mint"] if p.get("in_stock") else C["red"], bold=True))
        fl.addStretch(); root.addLayout(fl)

        sizes_avail = [l for k,l in [("size_xs","XS"),("size_s","S"),("size_m","M"),
                        ("size_l","L"),("size_xl","XL"),("size_xxl","XXL"),("size_xxxl","XXXL")] if p.get(k)]
        if p.get("size_range"): root.addWidget(_label(f"📏 {p['size_range']}", C["peach"]))
        if sizes_avail:
            sr = QHBoxLayout(); sr.addWidget(_label("Sizes:", C["muted"]))
            for s in sizes_avail:
                sl = QLabel(s); sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                sl.setStyleSheet(f"background:{C['lavender']};color:{C['bg']};border-radius:8px;"
                                 "padding:2px 10px;font-weight:bold;font-size:12px;margin:2px;")
                sr.addWidget(sl)
            sr.addStretch(); root.addLayout(sr)

        grid = QGridLayout(); grid.setSpacing(6); row = 0
        def grow(k, v, c=None):
            nonlocal row
            if not v: return
            grid.addWidget(_label(k, C["muted"]), row, 0)
            grid.addWidget(_label(str(v), c or C["white"]), row, 1)
            row += 1
        abs_txt = p.get("absorbency_label") or (f"{p['absorbency_ml']} ml" if p.get("absorbency_ml") else None)
        grow("Absorbency:", abs_txt)
        grow("Tab count:",  p.get("tab_count"))
        grow("Colors:",     p.get("colors"),   C["pink"])
        grow("Patterns:",   p.get("patterns"), C["lavender"])
        grow("Source:",     p.get("source_site"), C["muted"])
        grow("Last update:",(p.get("last_updated") or "")[:10])
        if row: root.addLayout(grid)
        if p.get("tags"): root.addWidget(_label(f"🏷 {p['tags']}", C["muted"], size=12))
        if p.get("description"):
            root.addWidget(_sep())
            desc = QTextEdit(p["description"][:800]); desc.setReadOnly(True); desc.setMaximumHeight(100)
            root.addWidget(desc)

        brow = QHBoxLayout()
        if p.get("url"):
            ob = _btn("🌐 Open in Browser", C["sky"]); url = p["url"]
            ob.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
            brow.addWidget(ob)
        pid = p.get("id")
        if pid:
            ab = _btn("🛒 Add to Shopping List", C["gold"])
            ab.clicked.connect(lambda: (self.add_to_list.emit(pid), self.accept()))
            brow.addWidget(ab)
        brow.addStretch()
        cb = _btn("Close", C["muted"]); cb.clicked.connect(self.accept); brow.addWidget(cb)
        root.addLayout(brow)


# ── Catalog Tab ────────────────────────────────────────────────────────────

class CatalogTab(QWidget):
    request_add_to_list = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._products = []
        # Debounce timer: search waits 300ms after last keystroke before querying
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self.reload)
        # Price slider debounce: 400ms
        self._price_timer = QTimer(self)
        self._price_timer.setSingleShot(True)
        self._price_timer.setInterval(400)
        self._price_timer.timeout.connect(self.reload)
        self._build()
        self.reload()

    def _build(self):
        root = QVBoxLayout(self); root.setContentsMargins(12,12,12,12); root.setSpacing(8)
        fbar = QWidget()
        fbar.setStyleSheet(f"background:{C['panel']};border-radius:8px;border:1px solid {C['border']};")
        fl = QVBoxLayout(fbar); fl.setContentsMargins(12,10,12,10); fl.setSpacing(8)

        r1 = QHBoxLayout(); r1.setSpacing(8)
        self.search = QLineEdit(); self.search.setPlaceholderText("🔍  Search products…")
        self.search.setMinimumWidth(220)
        # Debounced: start timer on each keystroke; timer fires reload after 300ms quiet
        self.search.textChanged.connect(lambda: self._search_timer.start())
        r1.addWidget(self.search, 3)

        self.type_cb = QComboBox(); self.type_cb.addItems(["All Types","ABDL","Medical","Both"])
        self.type_cb.currentIndexChanged.connect(self._on_type_change); r1.addWidget(self.type_cb)
        self.brand_cb = QComboBox(); self.brand_cb.addItem("All Brands")
        self.brand_cb.currentIndexChanged.connect(self.reload); r1.addWidget(self.brand_cb, 2)
        self.cat_cb = QComboBox(); self.cat_cb.addItem("All Categories")
        self.cat_cb.currentIndexChanged.connect(self.reload); r1.addWidget(self.cat_cb, 2)
        self.sort_cb = QComboBox(); self.sort_cb.addItems(["Name ↑","Price ↑","Newest","Rating"])
        self.sort_cb.currentIndexChanged.connect(self.reload); r1.addWidget(self.sort_cb)
        fl.addLayout(r1)

        r2 = QHBoxLayout(); r2.setSpacing(12)
        self.in_stock_chk = QCheckBox("In Stock Only")
        self.discreet_chk = QCheckBox("📦 Discreet Only")
        self.sample_chk   = QCheckBox("🎁 Free Sample")
        for chk in [self.in_stock_chk, self.discreet_chk, self.sample_chk]:
            chk.stateChanged.connect(self.reload); r2.addWidget(chk)

        r2.addSpacing(8); r2.addWidget(_label("Size:", C["muted"]))
        self.size_cb = QComboBox()
        self.size_cb.addItems(["All Sizes","XS","S","M","L","XL","XXL","XXXL"])
        self.size_cb.currentIndexChanged.connect(self.reload); r2.addWidget(self.size_cb)

        r2.addSpacing(8); r2.addWidget(_label("Max $:", C["muted"]))
        self.price_sl = QSlider(Qt.Orientation.Horizontal)
        self.price_sl.setRange(0, 200); self.price_sl.setValue(0); self.price_sl.setFixedWidth(110)
        self.price_lbl = _label("Any", C["mint"])
        # Only update label instantly; reload is debounced via timer
        self.price_sl.valueChanged.connect(self._on_price_changed)
        r2.addWidget(self.price_sl); r2.addWidget(self.price_lbl)
        r2.addStretch()
        self.result_lbl = _label("", C["muted"], size=12); r2.addWidget(self.result_lbl)
        fl.addLayout(r2)
        root.addWidget(fbar)

        COLS = ["Name","Brand","Category","Price","Type","Size Range","📦","🎁","Stock"]
        self.table = QTableWidget(); self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in [1, 2]:
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        for i in range(3, len(COLS)):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(self._open_row)
        root.addWidget(self.table, 1)

        bot = QHBoxLayout()
        ob = _btn("🔍 Open Selected", C["lavender"], small=True); ob.clicked.connect(self._open_selected); bot.addWidget(ob)
        al = _btn("🛒 Add to List",   C["gold"],     small=True); al.clicked.connect(self._add_selected_to_list); bot.addWidget(al)
        bot.addStretch()
        rb = _btn("↺ Refresh", C["mint"], small=True); rb.clicked.connect(self.reload); bot.addWidget(rb)
        root.addLayout(bot)
        self._populate_dropdowns()

    def _on_price_changed(self, v):
        self.price_lbl.setText("Any" if v == 0 else f"${v}")
        self._price_timer.start()   # debounced reload

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
        for c in cats: self.cat_cb.addItem(f"{c.get('icon','')} {c['name']}", c["id"])
        self.cat_cb.blockSignals(False)

    def _on_type_change(self):
        self._populate_dropdowns(); self.reload()

    def reload(self):
        if not DB_OK: return
        btype = self.type_cb.currentText().lower()
        btype = "all" if btype == "all types" else btype
        sort  = ["name","price","newest","rating"][self.sort_cb.currentIndex()]
        size_txt = self.size_cb.currentText()
        try:
            self._products = db.get_all_products(
                search           = self.search.text(),
                brand_id         = self.brand_cb.currentData(),
                category_id      = self.cat_cb.currentData(),
                in_stock_only    = self.in_stock_chk.isChecked(),
                sort             = sort,
                brand_type       = btype,
                size_filter      = None if size_txt == "All Sizes" else size_txt.lower(),
                discreet_only    = self.discreet_chk.isChecked(),
                free_sample_only = self.sample_chk.isChecked(),
                max_price        = self.price_sl.value() if self.price_sl.value() > 0 else None,
            )
        except Exception as e:
            print(f"[CatalogTab.reload] {e}")
            self._products = []
        self._fill_table()

    def _fill_table(self):
        prods = self._products
        CTR   = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        LEFT  = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        # cell() defined once outside the row loop — takes pid explicitly
        def cell(pid, txt, color=C["white"], align=LEFT):
            it = QTableWidgetItem(str(txt) if txt is not None else "")
            it.setForeground(QColor(color))
            it.setTextAlignment(align)
            it.setData(Qt.ItemDataRole.UserRole, pid)
            return it

        # Suspend repaints while rebuilding — prevents incremental repaint
        # stuttering on large catalogs (1300+ rows)
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(prods))
        for r, p in enumerate(prods):
            pid   = p.get("id")
            price = p.get("display_price") or p.get("price_usd") or p.get("price")
            btype = (p.get("brand_type") or "abdl").lower()
            tc    = _type_color(btype)
            self.table.setItem(r, 0, cell(pid, p.get("name","")))
            self.table.setItem(r, 1, cell(pid, p.get("brand_name",""),  C["lavender"]))
            self.table.setItem(r, 2, cell(pid, f"{p.get('category_icon','')} {p.get('category_name','')}".strip(), C["yellow"]))
            self.table.setItem(r, 3, cell(pid, f"${price:.2f}" if price else "–", C["mint"], CTR))
            self.table.setItem(r, 4, cell(pid, btype.upper(), tc, CTR))
            self.table.setItem(r, 5, cell(pid, p.get("size_range",""),  C["peach"]))
            self.table.setItem(r, 6, cell(pid, "📦" if p.get("discreet_shipping") or p.get("b_discreet") else "", C["white"], CTR))
            self.table.setItem(r, 7, cell(pid, "🎁" if p.get("free_sample") or p.get("b_free_sample") else "", C["white"], CTR))
            sc = C["mint"] if p.get("in_stock") else C["red"]
            self.table.setItem(r, 8, cell(pid, "✓" if p.get("in_stock") else "✗", sc, CTR))
        self.table.setSortingEnabled(True)
        self.table.setUpdatesEnabled(True)
        self.result_lbl.setText(f"{len(prods):,} products")

    def _pid_from_row(self, row):
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _open_row(self, idx):
        pid = self._pid_from_row(idx.row())
        if pid is None: return
        try:
            p = db.get_product_by_id(pid)
        except Exception: return
        if not p: return
        dlg = ProductDialog(p, self)
        dlg.add_to_list.connect(self.request_add_to_list)
        dlg.exec()

    def _open_selected(self):
        row = self.table.currentRow()
        if row < 0: return
        self._open_row(self.table.currentIndex())

    def _add_selected_to_list(self):
        row = self.table.currentRow()
        if row < 0: return
        pid = self._pid_from_row(row)
        if pid: self.request_add_to_list.emit(pid)


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

        # Right: tax/shipping/total
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(8)

        tx_card, txl = _card()
        txl.addWidget(_label("🏛 Sales Tax", C["lavender"], bold=True))
        txl.addWidget(_label("Select your state (state rate only; local tax may vary):", C["muted"], size=11))
        self.state_cb = QComboBox()
        for label, _ in STATE_TAXES: self.state_cb.addItem(label)
        self.state_cb.setStyleSheet(
            f"background:{C['panel2']};border:1px solid {C['border']};border-radius:6px;color:{C['white']};padding:5px 8px;")
        self.state_cb.currentIndexChanged.connect(self._recalc)
        txl.addWidget(self.state_cb)
        self.tax_note = _label("", C["muted"], size=11); self.tax_note.setWordWrap(True)
        txl.addWidget(self.tax_note)
        rl.addWidget(tx_card)

        sh_card, shl = _card()
        shl.addWidget(_label("📦 Shipping Estimate", C["lavender"], bold=True))
        self.free_ship_chk = QCheckBox("Free / no shipping fee")
        self.free_ship_chk.stateChanged.connect(self._on_free_ship)
        shl.addWidget(self.free_ship_chk)
        sh_row = QHBoxLayout(); sh_row.addWidget(_label("Flat shipping fee: $", C["muted"]))
        self.ship_spin = QDoubleSpinBox()
        self.ship_spin.setRange(0, 999.99); self.ship_spin.setDecimals(2)
        self.ship_spin.setSingleStep(0.50); self.ship_spin.setValue(9.99)
        self.ship_spin.valueChanged.connect(self._recalc)
        sh_row.addWidget(self.ship_spin); sh_row.addStretch(); shl.addLayout(sh_row)
        shl.addWidget(_label("Tip: most sites offer free shipping over $50–$75.", C["muted"], size=11))
        rl.addWidget(sh_card)

        tot_card, tol = _card()
        tol.addWidget(_label("💰 Cost Summary", C["gold"], bold=True))
        tol.addWidget(_sep())
        grid = QGridLayout(); grid.setColumnStretch(1, 1)
        self._tot_sub = _label("$0.00", C["white"], bold=True, size=14)
        self._tot_tax = _label("$0.00", C["yellow"], bold=True, size=14)
        self._tot_ship= _label("$0.00", C["sky"],    bold=True, size=14)
        for r, (lbl, val) in enumerate([("Subtotal:", self._tot_sub),
                                         ("Sales Tax:", self._tot_tax),
                                         ("Shipping:",  self._tot_ship)]):
            grid.addWidget(_label(lbl, C["muted"]), r, 0)
            grid.addWidget(val, r, 1)
        tol.addLayout(grid)
        tol.addWidget(_sep())
        grand_row = QHBoxLayout()
        grand_row.addWidget(_label("ESTIMATED TOTAL:", C["gold"], bold=True, size=15))
        grand_row.addStretch()
        self._tot_grand = _label("$0.00", C["gold"], bold=True, size=20)
        grand_row.addWidget(self._tot_grand)
        tol.addLayout(grand_row)
        tol.addWidget(_label(
            "⚠ Estimates only. Tax & shipping vary by address and final cart.",
            C["muted"], size=10))
        rl.addWidget(tot_card)

        self.export_btn = _btn("💾 Export shop.txt", C["gold"])
        self.export_btn.clicked.connect(self._export)
        rl.addWidget(self.export_btn)
        rl.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([620, 340])
        root.addWidget(splitter, 1)

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

    def _recalc_from_table(self):
        """Recalculate totals from what's currently shown in the table (no DB query)."""
        subtotal = 0.0
        for r in range(self.table.rowCount()):
            sub_item = self.table.item(r, 6)
            if sub_item:
                try: subtotal += float(sub_item.text().replace("$",""))
                except: pass
        tax_rate = STATE_TAXES[self.state_cb.currentIndex()][1]
        tax_amt  = round(subtotal * tax_rate, 2)
        ship_amt = 0.0 if self.free_ship_chk.isChecked() else self.ship_spin.value()
        grand    = round(subtotal + tax_amt + ship_amt, 2)
        self._tot_sub.setText(f"${subtotal:.2f}")
        self._tot_tax.setText(f"${tax_amt:.2f}")
        self._tot_ship.setText(f"${ship_amt:.2f}")
        self._tot_grand.setText(f"${grand:.2f}")

    def _recalc(self):
        subtotal = sum((it.get("unit_price") or 0) * it.get("quantity",1) for it in self._items)
        tax_rate = STATE_TAXES[self.state_cb.currentIndex()][1]
        tax_amt  = round(subtotal * tax_rate, 2)
        ship_amt = 0.0 if self.free_ship_chk.isChecked() else self.ship_spin.value()
        grand    = round(subtotal + tax_amt + ship_amt, 2)
        self._tot_sub.setText(f"${subtotal:.2f}")
        self._tot_tax.setText(f"${tax_amt:.2f}")
        self._tot_ship.setText(f"${ship_amt:.2f}")
        self._tot_grand.setText(f"${grand:.2f}")
        if tax_rate > 0:
            self.tax_note.setText(f"Applying {tax_rate*100:.3g}% state tax = ${tax_amt:.2f}")
        else:
            self.tax_note.setText("No state sales tax for the selected state.")

    def _clear_all(self):
        if not self._items: return
        try: db.clear_shopping_list()
        except Exception as e: print(f"[clear] {e}")
        self.reload()

    def _on_free_ship(self, state):
        self.ship_spin.setEnabled(not bool(state)); self._recalc()

    def _export(self):
        if not self._items:
            QMessageBox.information(self, "Empty List", "Your shopping list is empty."); return
        path, _ = QFileDialog.getSaveFileName(self, "Save Shopping List", "shop.txt", "Text Files (*.txt)")
        if not path: return

        tax_rate  = STATE_TAXES[self.state_cb.currentIndex()][1]
        tax_label = STATE_TAXES[self.state_cb.currentIndex()][0]
        subtotal  = sum((it.get("unit_price") or 0) * it.get("quantity",1) for it in self._items)
        tax_amt   = round(subtotal * tax_rate, 2)
        ship_amt  = 0.0 if self.free_ship_chk.isChecked() else self.ship_spin.value()
        grand     = round(subtotal + tax_amt + ship_amt, 2)
        ship_label= "Free" if self.free_ship_chk.isChecked() else f"${ship_amt:.2f} (flat)"
        W = 68; line = "─" * W

        lines = [
            "╔" + "═"*W + "╗",
            "║" + "  ABDL CATALOG — SHOPPING LIST".center(W) + "║",
            "║" + f"  Generated: {datetime.now().strftime('%Y-%m-%d  %H:%M')}".ljust(W) + "║",
            "╚" + "═"*W + "╝", "",
            "ITEMS", line,
        ]
        by_site = {}
        for it in self._items:
            by_site.setdefault(it.get("source_site") or "Unknown", []).append(it)

        item_num = 1
        for site, siteitems in sorted(by_site.items()):
            lines.append(f"  ┌─ {site}")
            for it in siteitems:
                name   = it.get("name","")[:38]
                brand  = it.get("brand_name","")
                qty    = it.get("quantity",1)
                uprice = it.get("unit_price") or 0.0
                sub    = round(uprice * qty, 2)
                url    = it.get("url","")
                lines.append(f"  │  {item_num:2d}. {name:<40} x{qty:<3}  ${uprice:7.2f}  =  ${sub:8.2f}")
                if brand: lines.append(f"  │      Brand: {brand}")
                if url:   lines.append(f"  │      URL:   {url}")
                lines.append("  │")
                item_num += 1
            if lines and lines[-1] == "  │": lines[-1] = "  └─"
            lines.append("")

        lines += [
            line,
            f"  {'Subtotal:':<30} ${subtotal:>10.2f}",
            f"  {'Shipping (' + ship_label + '):':<30} ${ship_amt:>10.2f}",
            f"  {'Sales Tax (' + tax_label + '):':<30} ${tax_amt:>10.2f}",
            line,
            f"  {'ESTIMATED TOTAL:':<30} ${grand:>10.2f}",
            line, "",
            "  NOTE: Prices are estimates from last catalog update.",
            "  Verify current prices and availability before purchasing.",
            "  Local/county tax may increase the sales tax amount.", "",
            "  Generated by ABDL Catalog — Baby Bear 🐻",
        ]
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            QMessageBox.information(self, "Exported",
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
        else:
            badge = _label("  ⚠ Install Playwright  ","")
            badge.setStyleSheet(f"background:{C['red']};color:white;border-radius:10px;padding:2px 10px;font-weight:bold;")
        hdr.addWidget(badge); hdr.addStretch()
        self.force_chk = QCheckBox("Force re-scrape (ignore schedule)")
        self.force_chk.setStyleSheet(f"color:{C['yellow']};"); hdr.addWidget(self.force_chk)
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


# ── Stats Tab ──────────────────────────────────────────────────────────────

class StatsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build()
        self.reload()

    def _build(self):
        root = QVBoxLayout(self); root.setContentsMargins(16,16,16,16); root.setSpacing(14)
        hdr = QHBoxLayout()
        hdr.addWidget(_label("📊 Catalog Statistics", C["pink"], bold=True, size=16))
        hdr.addStretch()
        rb = _btn("↺ Refresh", C["mint"], small=True); rb.clicked.connect(self.reload); hdr.addWidget(rb)
        root.addLayout(hdr)

        cards_row = QHBoxLayout(); cards_row.setSpacing(10); self._stat_labels = {}
        for key, icon, label, color in [
            ("total_products",    "📦","Total",     C["pink"]),
            ("abdl_products",     "🌟","ABDL",      C["abdl_c"]),
            ("medical_products",  "💊","Medical",   C["med_c"]),
            ("total_brands",      "🏷","Brands",    C["lavender"]),
            ("in_stock",          "✅","In Stock",  C["mint"]),
            ("discreet_count",    "📦","Discreet",  C["green"]),
            ("free_sample_count", "🎁","Samples",   C["peach"]),
            ("shopping_list_count","🛒","In Cart",  C["gold"]),
        ]:
            card, cl = _card()
            cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(_label(icon, color, size=20))
            v = _label("–", color, bold=True, size=24)
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(v); cl.addWidget(_label(label, C["muted"], size=11))
            self._stat_labels[key] = v; cards_row.addWidget(card)
        root.addLayout(cards_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        bc, bcl = _card(); bcl.addWidget(_label("Top Brands by Products", C["lavender"], bold=True))
        self.brands_table = QTableWidget(); self.brands_table.setColumnCount(2)
        self.brands_table.setHorizontalHeaderLabels(["Brand","Products"])
        self.brands_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.brands_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.brands_table.verticalHeader().setVisible(False)
        self.brands_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.brands_table.setStyleSheet(f"background:{C['panel2']};border:none;")
        bcl.addWidget(self.brands_table); splitter.addWidget(bc)

        hc, hcl = _card(); hcl.addWidget(_label("Recent Scrape History", C["lavender"], bold=True))
        self.hist_table = QTableWidget(); self.hist_table.setColumnCount(4)
        self.hist_table.setHorizontalHeaderLabels(["Site","Found","Status","When"])
        self.hist_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1,4):
            self.hist_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.hist_table.verticalHeader().setVisible(False)
        self.hist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hist_table.setStyleSheet(f"background:{C['panel2']};border:none;")
        hcl.addWidget(self.hist_table); splitter.addWidget(hc)
        root.addWidget(splitter, 1)
        self.last_lbl = _label("", C["muted"], size=11); root.addWidget(self.last_lbl)

    def reload(self):
        if not DB_OK: return
        try:
            s = db.get_stats()
        except Exception as e:
            print(f"[StatsTab.reload] {e}"); return
        for key, lbl in self._stat_labels.items():
            lbl.setText(str(s.get(key, "–")))
        top = s.get("top_brands", [])
        self.brands_table.setUpdatesEnabled(False)
        self.brands_table.setRowCount(len(top))
        for r, b in enumerate(top):
            self.brands_table.setItem(r, 0, QTableWidgetItem(b.get("name","")))
            cnt = QTableWidgetItem(str(b.get("cnt",0)))
            cnt.setForeground(QColor(C["mint"]))
            cnt.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.brands_table.setItem(r, 1, cnt)
        self.brands_table.setUpdatesEnabled(True)
        log_rows = db.get_scrape_log(25)
        self.hist_table.setUpdatesEnabled(False)
        self.hist_table.setRowCount(len(log_rows))
        for r, row in enumerate(log_rows):
            sc = C["mint"] if row.get("status") == "SUCCESS" else C["red"]
            self.hist_table.setItem(r, 0, QTableWidgetItem(row.get("site_name","")))
            fn = QTableWidgetItem(str(row.get("products_found",0)))
            fn.setForeground(QColor(C["mint"]))
            fn.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.hist_table.setItem(r, 1, fn)
            st = QTableWidgetItem(row.get("status",""))
            st.setForeground(QColor(sc))
            self.hist_table.setItem(r, 2, st)
            self.hist_table.setItem(r, 3, QTableWidgetItem((row.get("started_at") or "")[:16]))
        self.hist_table.setUpdatesEnabled(True)
        self.last_lbl.setText(
            f"Last scrape: {s.get('last_scrape','Never')}   |   Sites due: {s.get('sites_due',0)}")


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
        inner.addTab(self._build_health_tab(),   "🔧  Health")
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
            sources = db.get_source_sites_list()   # [{source_site, cnt}, ...]
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
        actions = [
            ("🔍 Integrity Check",     C["sky"],    self._run_integrity),
            ("🔄 Rebuild FTS Index",   C["lavender"],self._run_rebuild_fts),
            ("💾 WAL Checkpoint",      C["yellow"], self._run_checkpoint),
            ("🗜 VACUUM (defrag)",     C["peach"],  self._run_vacuum),
            ("📤 Backup to File…",     C["mint"],   self._run_backup),
            ("↺ Refresh Info",         C["muted"],  self._refresh_health),
        ]
        for label, color, fn in actions:
            b = _btn(label, color, small=True); b.clicked.connect(fn); ll.addWidget(b)
        ll.addStretch()
        splitter.addWidget(left)

        # Right: log
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0)
        rl.addWidget(_label("Log", C["lavender"], bold=True))
        self.health_log = QTextEdit(); self.health_log.setReadOnly(True)
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
        try:
            info = db.get_db_health()
        except Exception as e:
            self._hlog(f"Error: {e}", C["red"]); return

        # Clear and rebuild info grid
        while self._info_grid.count():
            item = self._info_grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        rows_data = [
            ("DB Path",       info.get("path","?")),
            ("DB Size",       f"{info.get('size_mb',0)} MB"),
            ("WAL Size",      f"{info.get('wal_mb',0)} MB"),
            ("Products",      str(info.get("rows_products","?"))),
            ("Brands",        str(info.get("rows_brands","?"))),
            ("Categories",    str(info.get("rows_categories","?"))),
            ("Scrape Sites",  str(info.get("rows_scrape_sites","?"))),
            ("Scrape Log",    str(info.get("rows_scrape_log","?"))),
            ("Shopping List", str(info.get("rows_shopping_list","?"))),
        ]
        for r, (k, v) in enumerate(rows_data):
            self._info_grid.addWidget(_label(f"{k}:", C["muted"], size=11), r, 0)
            lbl = _label(v, C["white"], size=11)
            lbl.setWordWrap(True)
            self._info_grid.addWidget(lbl, r, 1)
        self._hlog(f"Info refreshed — {info.get('rows_products','?')} products, "
                   f"{info.get('size_mb',0)} MB")

    def _run_integrity(self):
        self._hlog("Running integrity check…", C["yellow"])
        try:
            msgs = db.db_integrity_check()
            for m in msgs:
                color = C["mint"] if "ok" in m.lower() or "✓" in m else C["red"]
                self._hlog(m, color)
        except Exception as e:
            self._hlog(f"Error: {e}", C["red"])

    def _run_rebuild_fts(self):
        self._hlog("Rebuilding FTS5 index…", C["yellow"])
        try:
            n = db.rebuild_fts()
            self._hlog(f"✓ FTS rebuilt — {n} rows indexed", C["mint"])
        except Exception as e:
            self._hlog(f"Error: {e}", C["red"])

    def _run_checkpoint(self):
        self._hlog("Checkpointing WAL…", C["yellow"])
        try:
            cp = db.db_checkpoint()
            self._hlog(f"✓ Checkpoint done — log={cp.get('log',0)} frames, "
                       f"checkpointed={cp.get('checkpointed',0)}", C["mint"])
            self._refresh_health()
        except Exception as e:
            self._hlog(f"Error: {e}", C["red"])

    def _run_vacuum(self):
        self._hlog("Running VACUUM… (may take a moment)", C["yellow"])
        try:
            new_mb = db.db_vacuum()
            self._hlog(f"✓ VACUUM done — new DB size: {new_mb} MB", C["mint"])
            self._refresh_health()
        except Exception as e:
            self._hlog(f"Error: {e}", C["red"])

    def _run_backup(self):
        default = f"abdl_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        path, _ = QFileDialog.getSaveFileName(self, "Backup Database",
                    default, "SQLite DB (*.db)")
        if not path: return
        self._hlog(f"Backing up to {path}…", C["yellow"])
        try:
            mb = db.db_backup(path)
            self._hlog(f"✓ Backup saved — {mb} MB → {path}", C["mint"])
        except Exception as e:
            self._hlog(f"Error: {e}", C["red"])

    def _on_inner_tab(self, idx):
        if idx == 0: self.reload_sites()
        elif idx == 1: self._refresh_sources(); self._reload_products()
        elif idx == 2: self._refresh_health()


# ── Main Window ────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🐻 ABDL Catalog — Baby Bear")
        self.setMinimumSize(1280, 820)
        self.setStyleSheet(BASE_SS)

        title_bar = QWidget()
        title_bar.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']};")
        tbl = QHBoxLayout(title_bar); tbl.setContentsMargins(16,8,16,8)
        tbl.addWidget(_label("🐻", size=22))
        tbl.addWidget(_label("ABDL Catalog", C["pink"], bold=True, size=18))
        tbl.addSpacing(10)
        tbl.addWidget(_label("Baby Bear LCARS", C["muted"], size=12))
        tbl.addStretch()
        self.status_lbl = _label("Loading…", C["muted"], size=12)
        tbl.addWidget(self.status_lbl)

        self.tabs         = QTabWidget()
        self.catalog_tab  = CatalogTab()
        self.shopping_tab = ShoppingListTab()
        self.scraper_tab  = ScraperTab()
        self.stats_tab    = StatsTab()
        self.db_tab       = DBManagementTab()
        self.tabs.addTab(self.catalog_tab,  "📦  Catalog")
        self.tabs.addTab(self.shopping_tab, "🛒  Shopping List")
        self.tabs.addTab(self.scraper_tab,  "🌐  Scraper")
        self.tabs.addTab(self.stats_tab,    "📊  Stats")
        self.tabs.addTab(self.db_tab,       "🗄  Database")

        self.catalog_tab.request_add_to_list.connect(self._add_to_list)
        self.scraper_tab.refresh_catalog.connect(self.catalog_tab.reload)
        self.scraper_tab.refresh_catalog.connect(self.shopping_tab.reload)
        self.scraper_tab.refresh_catalog.connect(self.stats_tab.reload)
        self.scraper_tab.refresh_catalog.connect(self.db_tab.reload_sites)
        self.scraper_tab.refresh_catalog.connect(self._update_status)
        self.db_tab.sites_changed.connect(self.scraper_tab._refresh_sites)
        self.tabs.currentChanged.connect(self._on_tab)

        central = QWidget()
        cl = QVBoxLayout(central); cl.setContentsMargins(0,0,0,0); cl.setSpacing(0)
        cl.addWidget(title_bar); cl.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self._update_status()
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(60_000)

    def _on_tab(self, idx):
        if idx == 1: self.shopping_tab.reload()
        if idx == 3: self.stats_tab.reload()

    def _add_to_list(self, pid):
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


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    if DB_OK:
        try: db.init_db()
        except Exception as e: print(f"[init_db] {e}")

    app = QApplication(sys.argv)
    app.setApplicationName("ABDL Catalog")
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

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
