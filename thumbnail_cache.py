"""
thumbnail_cache.py — CrinkleDen (CDN)

Hydrus-style on-disk thumbnail store.

Layout on disk:
    thumbnails/
        00/  <md5[:2]>/<md5[2:]>.jpg   150×150 JPEG, quality 75
        01/  ...
        ff/  ...

Every thumbnail is a pre-generated 200×200 JPEG (keeping aspect ratio,
padded with the app background colour so the card always fills cleanly).
Stored by MD5 of the source URL so lookup is instant — just hash the URL
and check whether the file exists.  No database, no index, no locking.

Usage:
    cache = get_thumb_cache()
    path  = cache.get(url)          # returns Path or None
    path  = cache.store(url, data)  # saves thumbnail, returns Path
    cache.generate_from_blobs(pcb)  # batch-generate for all DB blobs
"""

import hashlib, io, os, threading
from pathlib import Path

# ── Defaults ────────────────────────────────────────────────────────────────
THUMB_SIZE    = (200, 200)      # max dimensions; aspect ratio kept
THUMB_QUALITY = 78              # JPEG quality — good balance of size vs clarity
THUMB_BG      = (7, 16, 31)     # C["bg"] dark navy — matches app background
DEFAULT_DIR   = Path(__file__).resolve().parent / "thumbnails"

# ── Module-level singleton ───────────────────────────────────────────────────
_cache_instance = None
_cache_lock     = threading.Lock()

def get_thumb_cache(cache_dir=None) -> "ThumbnailCache":
    global _cache_instance
    with _cache_lock:
        if _cache_instance is None:
            _cache_instance = ThumbnailCache(cache_dir or DEFAULT_DIR)
        return _cache_instance


def _url_key(url: str) -> str:
    """MD5 hex of the URL — used as filename."""
    return hashlib.md5(url.encode("utf-8", errors="replace")).hexdigest()


# ── ThumbnailCache ────────────────────────────────────────────────────────────

class ThumbnailCache:
    """
    Fast on-disk thumbnail store.  Thread-safe — multiple Qt worker threads
    can call get/store concurrently.  No shared mutable state beyond the
    filesystem itself (which handles concurrent writes fine).
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self._init_dirs()

    # ── Filesystem setup ──────────────────────────────────────────────────────

    def _init_dirs(self):
        """Create 256 shard directories (00 … ff)."""
        self.root.mkdir(parents=True, exist_ok=True)
        for i in range(256):
            (self.root / f"{i:02x}").mkdir(exist_ok=True)

    def _path_for(self, url: str) -> Path:
        key   = _url_key(url)
        shard = key[:2]
        return self.root / shard / f"{key[2:]}.jpg"

    # ── Public API ────────────────────────────────────────────────────────────

    def exists(self, url: str) -> bool:
        """Return True if a thumbnail is already stored for this URL."""
        return self._path_for(url).exists()

    def get(self, url: str) -> "Path | None":
        """Return the thumbnail Path if it exists, else None."""
        p = self._path_for(url)
        return p if p.exists() else None

    def get_by_product_id(self, product_id: int) -> "Path | None":
        """
        Look up thumbnail by product_id using the products.image_url.
        Requires a database connection.  Returns Path or None.
        """
        try:
            from database import get_connection
            conn = get_connection()
            r = conn.execute(
                "SELECT image_url FROM products WHERE id=? LIMIT 1",
                (product_id,)
            ).fetchone()
            conn.close()
            if r and r[0]:
                return self.get(r[0])
        except Exception:
            pass
        return None

    def store(self, url: str, image_data: bytes) -> "Path | None":
        """
        Generate a thumbnail from raw image bytes and save to disk.
        Returns the thumbnail Path on success, None on failure.
        Silently no-ops if the thumbnail already exists.
        """
        dest = self._path_for(url)
        if dest.exists():
            return dest
        thumb = _make_thumb(image_data)
        if not thumb:
            return None
        try:
            dest.write_bytes(thumb)
            return dest
        except Exception:
            return None

    def store_from_db_blob(self, url: str, blob: bytes) -> "Path | None":
        """Same as store() — alias kept for clarity."""
        return self.store(url, blob)

    def delete(self, url: str):
        """Remove a cached thumbnail (e.g. after re-download)."""
        try:
            self._path_for(url).unlink(missing_ok=True)
        except Exception:
            pass

    def stats(self) -> dict:
        """Count files and total size."""
        total = size = 0
        for p in self.root.rglob("*.jpg"):
            total += 1
            try:
                size += p.stat().st_size
            except Exception:
                pass
        return {"count": total, "size_mb": round(size / 1024 / 1024, 2)}

    def generate_from_blobs(self, pcb=None, limit=999_999):
        """
        Batch-generate thumbnails for every product_images row that has
        a blob stored but no thumbnail on disk yet.

        Called from the UI after a download session so future catalog
        loads are instant.  Runs synchronously — call in a thread.
        Returns count of thumbnails generated.
        """
        try:
            from database import get_connection
        except ImportError:
            if pcb: pcb("  ✗ database.py not importable")
            return 0

        conn = get_connection()
        try:
            rows = conn.execute("""
                SELECT pi.id, pi.image_url, pi.image_data
                FROM   product_images pi
                WHERE  pi.image_data IS NOT NULL
                  AND  pi.image_url  IS NOT NULL
                  AND  pi.image_url  != ''
                ORDER  BY pi.is_primary DESC, pi.id
                LIMIT  ?
            """, (limit,)).fetchall()
        except Exception as e:
            if pcb: pcb(f"  ✗ Query failed: {e}")
            conn.close()
            return 0
        finally:
            conn.close()

        generated = 0
        skipped   = 0
        failed    = 0

        for row in rows:
            url  = row["image_url"]
            data = row["image_data"]
            if not url or not data:
                continue
            if self.exists(url):
                skipped += 1
                continue
            path = self.store(url, bytes(data))
            if path:
                generated += 1
                if pcb and generated % 50 == 0:
                    pcb(f"  ✓ {generated} thumbnails generated…")
            else:
                failed += 1

        if pcb:
            pcb(f"  ✓ Done — {generated} generated, {skipped} already existed, "
                f"{failed} failed")
        return generated


# ── Thumbnail generation ──────────────────────────────────────────────────────

def _make_thumb(data: bytes) -> "bytes | None":
    """
    Resize image data to THUMB_SIZE with aspect ratio preserved,
    composite onto THUMB_BG background, save as JPEG bytes.
    Returns None if the data cannot be decoded.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        # Pillow not installed — fall back to Qt-based resize
        return _make_thumb_qt(data)

    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)   # fix orientation
        img = img.convert("RGBA") if img.mode in ("P","LA","PA") else img.convert("RGB")

        # Fit within THUMB_SIZE preserving aspect ratio
        img.thumbnail(THUMB_SIZE, Image.LANCZOS)

        # Paste onto solid background so every thumb is exactly THUMB_SIZE
        bg = Image.new("RGB", THUMB_SIZE, THUMB_BG)
        offset = (
            (THUMB_SIZE[0] - img.width)  // 2,
            (THUMB_SIZE[1] - img.height) // 2,
        )
        if img.mode == "RGBA":
            bg.paste(img, offset, img)
        else:
            bg.paste(img, offset)

        out = io.BytesIO()
        bg.save(out, format="JPEG", quality=THUMB_QUALITY, optimize=True)
        return out.getvalue()

    except Exception:
        return None


def _make_thumb_qt(data: bytes) -> "bytes | None":
    """
    Fallback thumbnail generator using PyQt6 only (no Pillow required).
    Slightly lower quality resize but always available.
    """
    try:
        from PyQt6.QtGui  import QImage, QPixmap, QPainter, QColor
        from PyQt6.QtCore import Qt, QBuffer, QByteArray, QIODevice

        src = QImage()
        if not src.loadFromData(data):
            return None
        src = src.scaled(
            THUMB_SIZE[0], THUMB_SIZE[1],
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Composite onto background
        bg = QImage(THUMB_SIZE[0], THUMB_SIZE[1], QImage.Format.Format_RGB888)
        bg.fill(QColor(*THUMB_BG))
        painter = QPainter(bg)
        painter.drawImage(
            (THUMB_SIZE[0] - src.width())  // 2,
            (THUMB_SIZE[1] - src.height()) // 2,
            src,
        )
        painter.end()

        buf = QByteArray()
        qbuf = QBuffer(buf)
        qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
        bg.save(qbuf, "JPEG", THUMB_QUALITY)
        return bytes(buf)

    except Exception:
        return None
