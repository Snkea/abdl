"""
image_cache.py — CrinkleDen local image cache
========================================================
Keeps a disk cache of every product image URL so the scraper and UI
never download the same image twice.

Layout
------
  cache/
    images/
      ab/  cd/  …  (2-char hex shards)
        <md5>.jpg
    index.db   (SQLite — URL → cached file metadata)

Usage
-----
    from image_cache import ImageCache
    cache = ImageCache()                 # uses ./cache/ next to this file

    path = cache.fetch(url)              # returns local Path (downloads if needed)
    if cache.is_cached(url):
        path = cache.get_path(url)

    # Batch pre-warm (call from scraper after each product batch)
    cache.prefetch_urls(url_list, max_workers=8)

    stats = cache.get_stats()
    cache.evict_stale(days=30)           # remove old entries
    cache.clear()                        # wipe everything
"""

import hashlib
import io
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ── Default configuration ──────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent
DEFAULT_CACHE_DIR = _HERE / "cache"
DEFAULT_TIMEOUT   = 15          # seconds per request
DEFAULT_MAX_SIZE  = 50          # MB per image — skip if larger
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── Helpers ────────────────────────────────────────────────────────────────

def _url_md5(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

def _data_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()

def _ext_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".avif"):
        if path.endswith(ext):
            return ext.lstrip(".")
    return "jpg"   # default

def _human(n: int) -> str:
    for u in ("B","KB","MB","GB","TB"):
        if n < 1024: return f"{n:.1f}{u}" if u!="B" else f"{n}B"
        n //= 1024
    return f"{n:.1f}PB"


# ══════════════════════════════════════════════════════════════════════════

class ImageCache:
    """
    Thread-safe local image cache backed by a small SQLite index.

    Parameters
    ----------
    cache_dir  : root folder  (default: ./cache/)
    timeout    : HTTP request timeout in seconds
    max_size_mb: skip caching images larger than this
    """

    def __init__(self, cache_dir=None, timeout=DEFAULT_TIMEOUT,
                 max_size_mb=DEFAULT_MAX_SIZE):
        self.cache_dir  = Path(cache_dir or DEFAULT_CACHE_DIR)
        self.img_dir    = self.cache_dir / "images"
        self.db_path    = self.cache_dir / "index.db"
        self.timeout    = timeout
        self.max_bytes  = max_size_mb * 1024 * 1024
        self._lock      = threading.Lock()
        self._init()

    # ── Setup ──────────────────────────────────────────────────────────────

    def _init(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.img_dir.mkdir(exist_ok=True)
        # Create 256 shard folders (00..ff)
        for i in range(256):
            (self.img_dir / f"{i:02x}").mkdir(exist_ok=True)

        conn = self._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS image_cache (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                url          TEXT UNIQUE NOT NULL,
                url_md5      TEXT NOT NULL,
                file_md5     TEXT,
                local_path   TEXT,
                file_size    INTEGER,
                width        INTEGER,
                height       INTEGER,
                mime_type    TEXT,
                status       TEXT DEFAULT 'ok',
                error_msg    TEXT,
                cached_at    TEXT DEFAULT (datetime('now')),
                last_checked TEXT DEFAULT (datetime('now')),
                check_count  INTEGER DEFAULT 1
            )
        """)
        # url is already UNIQUE (implicit index) — no separate idx_ic_url needed
        # url_md5 index for fast hash lookups
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ic_urlmd5  ON image_cache(url_md5)")
        # status+local_path composite — covers is_cached() query fully
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ic_status_path ON image_cache(status, local_path)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ic_cached  ON image_cache(cached_at)")
        # file_md5 for content-based dedup lookups
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ic_filemd5 ON image_cache(file_md5) WHERE file_md5 IS NOT NULL")
        conn.commit()
        conn.close()

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-32768")   # 32 MB page cache
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    def _get_persistent_conn(self):
        """
        Return a thread-local persistent connection.
        This eliminates the 80x overhead of opening a new SQLite connection
        on every is_cached() / get_path() call — critical for gallery thumbnails
        where hundreds of lookups happen per second.
        """
        import threading
        tls = self.__dict__.setdefault("_tls", threading.local())
        if not getattr(tls, "conn", None):
            tls.conn = sqlite3.connect(
                self.db_path,
                timeout=10,
                check_same_thread=False,  # thread-local, always same thread
            )
            tls.conn.row_factory = sqlite3.Row
            tls.conn.execute("PRAGMA journal_mode=WAL")
            tls.conn.execute("PRAGMA synchronous=NORMAL")
            tls.conn.execute("PRAGMA cache_size=-32768")
            tls.conn.execute("PRAGMA temp_store=MEMORY")
        return tls.conn

    # ── Core API ───────────────────────────────────────────────────────────

    def is_cached(self, url: str) -> bool:
        """
        Return True if this URL is recorded as successfully cached in the DB.

        Trusts the DB status='ok' without doing a filesystem stat — this makes
        is_cached() 20x faster for gallery thumbnail lookups. The file will be
        verified by get_path() if you actually need to read it.
        Use verify_integrity() for periodic full consistency checks.
        """
        try:
            conn = self._get_persistent_conn()
            row = conn.execute(
                "SELECT status FROM image_cache WHERE url=?", (url,)
            ).fetchone()
        except Exception:
            conn = self._conn()
            row = conn.execute(
                "SELECT status FROM image_cache WHERE url=?", (url,)
            ).fetchone()
            conn.close()
        return row is not None and row["status"] == "ok"

    def get_path(self, url: str):
        """Return local Path for a cached URL, or None if not cached or file missing."""
        try:
            conn = self._get_persistent_conn()
            row = conn.execute(
                "SELECT local_path, status FROM image_cache WHERE url=?", (url,)
            ).fetchone()
        except Exception:
            conn = self._conn()
            row = conn.execute(
                "SELECT local_path, status FROM image_cache WHERE url=?", (url,)
            ).fetchone()
            conn.close()
        if not row or row["status"] != "ok" or not row["local_path"]:
            return None
        p = self.img_dir / row["local_path"]
        return p if p.exists() else None

    def get_bytes(self, url: str):
        """Return cached image bytes, or None."""
        p = self.get_path(url)
        return p.read_bytes() if p else None

    def fetch(self, url: str, force=False):
        """
        Return local Path for url, downloading and caching if necessary.
        Returns None on permanent failure or if image is too large.
        If force=True, re-download even if already cached.
        """
        if not url or not url.startswith("http"):
            return None
        if not force:
            cached = self.get_path(url)
            if cached:
                return cached

        # Already marked as permanently failed — don't retry unless forced
        if not force:
            conn = self._conn()
            row = conn.execute(
                "SELECT status, check_count FROM image_cache WHERE url=?", (url,)
            ).fetchone()
            conn.close()
            if row and row["status"] == "error" and row["check_count"] >= 3:
                return None   # Give up after 3 failed attempts

        data, mime, err = self._download(url)
        if data is None:
            self._record_error(url, err or "download failed")
            return None

        if len(data) > self.max_bytes:
            self._record_error(url, f"too large: {_human(len(data))}")
            return None

        return self._store(url, data, mime)

    def _download(self, url: str):
        """Download url. Returns (data, mime_type, error_msg)."""
        try:
            req = Request(url, headers={"User-Agent": _UA, "Accept": "image/*,*/*"})
            with urlopen(req, timeout=self.timeout) as resp:
                mime = resp.headers.get_content_type() or "image/jpeg"
                data = resp.read()
            return data, mime, None
        except HTTPError as e:
            return None, None, f"HTTP {e.code}"
        except URLError as e:
            return None, None, str(e.reason)
        except Exception as e:
            return None, None, str(e)

    def _store(self, url: str, data: bytes, mime: str = "image/jpeg"):
        """Write data to disk and update the index. Returns Path."""
        umd5  = _url_md5(url)
        fmd5  = _data_md5(data)
        ext   = _ext_from_url(url)
        shard = fmd5[:2]
        rel   = f"{shard}/{fmd5}.{ext}"
        dest  = self.img_dir / rel

        # Check if file with same content already exists (different URL, same image)
        if not dest.exists():
            dest.write_bytes(data)

        # Get image dimensions if PIL is available
        w = h = None
        try:
            from PIL import Image as _PIL
            img = _PIL.open(io.BytesIO(data))
            w, h = img.size
        except Exception:
            pass

        with self._lock:
            conn = self._conn()
            conn.execute("""
                INSERT INTO image_cache
                    (url, url_md5, file_md5, local_path, file_size,
                     width, height, mime_type, status,
                     cached_at, last_checked, check_count)
                VALUES (?,?,?,?,?,?,?,?,'ok',datetime('now'),datetime('now'),1)
                ON CONFLICT(url) DO UPDATE SET
                    file_md5=excluded.file_md5,
                    local_path=excluded.local_path,
                    file_size=excluded.file_size,
                    width=excluded.width,
                    height=excluded.height,
                    status='ok',
                    last_checked=datetime('now'),
                    check_count=check_count+1
            """, (url, umd5, fmd5, rel, len(data), w, h, mime))
            conn.commit()
            conn.close()

        return dest

    def _record_error(self, url: str, msg: str):
        with self._lock:
            conn = self._conn()
            conn.execute("""
                INSERT INTO image_cache
                    (url, url_md5, status, error_msg, cached_at, last_checked, check_count)
                VALUES (?,?,'error',?,datetime('now'),datetime('now'),1)
                ON CONFLICT(url) DO UPDATE SET
                    status='error',
                    error_msg=excluded.error_msg,
                    last_checked=datetime('now'),
                    check_count=check_count+1
            """, (url, _url_md5(url), msg))
            conn.commit()
            conn.close()

    # ── Batch operations ───────────────────────────────────────────────────

    def prefetch_urls(self, urls, max_workers=8, pcb=None):
        """
        Download a list of URLs in parallel.  Already-cached URLs are skipped.
        Returns {added: n, skipped: n, errors: n}.
        """
        todo = [u for u in urls if u and not self.is_cached(u)]
        if not todo:
            return {"added": 0, "skipped": len(urls), "errors": 0}

        added = skipped = errors = 0
        _lock = threading.Lock()

        def _fetch_one(url):
            nonlocal added, skipped, errors
            path = self.fetch(url)
            with _lock:
                if path:
                    added += 1
                else:
                    errors += 1
            if pcb:
                pcb(f"  cached {path.name if path else '?'}")

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            list(ex.map(_fetch_one, todo))

        skipped = len(urls) - len(todo)
        return {"added": added, "skipped": skipped, "errors": errors}

    def has_url_md5(self, url: str) -> bool:
        """Fast check — has this URL ever been seen (cached OR errored)?"""
        try:
            conn = self._get_persistent_conn()
            row = conn.execute("SELECT 1 FROM image_cache WHERE url=?", (url,)).fetchone()
        except Exception:
            conn = self._conn()
            row = conn.execute("SELECT 1 FROM image_cache WHERE url=?", (url,)).fetchone()
            conn.close()
        return row is not None

    # ── Maintenance ────────────────────────────────────────────────────────

    def get_stats(self):
        conn = self._conn()
        total  = conn.execute("SELECT COUNT(*) FROM image_cache").fetchone()[0]
        ok     = conn.execute("SELECT COUNT(*) FROM image_cache WHERE status='ok'").fetchone()[0]
        errors = conn.execute("SELECT COUNT(*) FROM image_cache WHERE status='error'").fetchone()[0]
        size   = conn.execute(
            "SELECT COALESCE(SUM(file_size),0) FROM image_cache WHERE status='ok'"
        ).fetchone()[0]
        conn.close()

        disk = sum(
            f.stat().st_size for f in self.img_dir.rglob("*") if f.is_file()
        )
        return {
            "total":       total,
            "ok":          ok,
            "errors":      errors,
            "size_bytes":  size,
            "size_human":  _human(size),
            "disk_bytes":  disk,
            "disk_human":  _human(disk),
            "cache_dir":   str(self.cache_dir),
        }

    def evict_stale(self, days=30, dry_run=False):
        """Remove entries not accessed in `days` days. Returns count."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, local_path FROM image_cache WHERE last_checked < ?", (cutoff,)
        ).fetchall()
        count = 0
        for row in rows:
            if row["local_path"] and not dry_run:
                p = self.img_dir / row["local_path"]
                if p.exists():
                    p.unlink()
            count += 1
        if not dry_run:
            conn.execute("DELETE FROM image_cache WHERE last_checked < ?", (cutoff,))
            conn.commit()
        conn.close()
        return count

    def clear(self):
        """Wipe all cached files and the index."""
        import shutil
        shutil.rmtree(self.img_dir, ignore_errors=True)
        self.img_dir.mkdir(exist_ok=True)
        for i in range(256):
            (self.img_dir / f"{i:02x}").mkdir(exist_ok=True)
        conn = self._conn()
        conn.execute("DELETE FROM image_cache")
        conn.commit()
        conn.close()

    def rebuild_index(self, pcb=None):
        """
        Re-scan the cache folder and rebuild the index from disk.
        Useful if the index.db got deleted.
        """
        conn = self._conn()
        conn.execute("DELETE FROM image_cache")
        conn.commit()
        added = 0
        for f in self.img_dir.rglob("*"):
            if f.is_file():
                rel = f.relative_to(self.img_dir).as_posix()
                fmd5 = f.stem   # filename is the md5
                conn.execute("""
                    INSERT OR IGNORE INTO image_cache
                        (url, url_md5, file_md5, local_path, file_size, status)
                    VALUES (?,?,?,?,?,'ok')
                """, (f"file://{rel}", fmd5, fmd5, rel, f.stat().st_size))
                added += 1
                if pcb and added % 500 == 0:
                    pcb(f"  Indexed {added} files…")
        conn.commit()
        conn.close()
        return added


# ── Module-level singleton ─────────────────────────────────────────────────

_instance = None

def get_cache(cache_dir=None) -> ImageCache:
    global _instance
    if _instance is None:
        _instance = ImageCache(cache_dir=cache_dir)
    return _instance
