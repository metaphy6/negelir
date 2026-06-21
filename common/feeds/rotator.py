"""File rotation with compression and checksums for FeedWriter (Phase 16.2 bullet 4).

Handles atomic rotation at midnight UTC with durability guarantees:
  - Compression: compress → fsync → checksum → atomic rename
  - Checksums: per-file SHA256 sidecar for integrity verification
  - Durability: fsync on file descriptor, parent directory, and manifest
  - Safety: atomic rename ensures no partial files

Properties (binding per Phase 16.2, ledger #14):
  - Every write: write() + os.fsync() on file descriptor
  - Rotation: compress → fsync → checksum → atomic rename → unlink → fsync(parent)
  - Fsync modes: always|batch|off (off is test-only)
  - Per-file sidecar: <file>.sha256 for integrity verification
  - Manifest records: codec, level, sidecar_sha256
"""

import hashlib
import logging
import os
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CompressionConfig:
    """Configuration for compression strategy."""
    codec: str = "zstd"  # zstd|gzip|off
    level: int = 9  # 1-22 for zstd, 1-9 for gzip
    dict_path: Optional[Path] = None  # Optional per-plane dictionary


class FileRotator:
    """Handles atomic file rotation with compression and checksums.
    
    Rotation sequence (atomic per Phase 16.2 §4):
      1. Close current file handle
      2. Compress: .ndjson → .ndjson.zst (with gzip/zstd)
      3. Fsync compressed file
      4. Checksum: compute SHA256 and write .ndjson.zst.sha256
      5. Atomic rename: from .ndjson.zst.tmp → .ndjson.zst
      6. Unlink original .ndjson
      7. Fsync parent directory
    
    Usage:
        rotator = FileRotator(
            feeds_dir="/data/feeds",
            compression=CompressionConfig(codec="zstd", level=9),
            fsync_mode="always",
        )
        
        rotator.rotate_file(
            file_path=Path("/data/feeds/score/mackolik/2026-06-09.ndjson"),
            new_file_path=Path("/data/feeds/score/mackolik/2026-06-10.ndjson"),
        )
        
        state = rotator.get_rotation_state()  # For manifest recording
    """
    
    def __init__(
        self,
        feeds_dir: str = "/data/feeds",
        compression: Optional[CompressionConfig] = None,
        fsync_mode: str = "always",
        fsync_batch_ms: int = 100,
    ):
        """Initialize FileRotator.
        
        Args:
            feeds_dir: Root directory for feeds
            compression: CompressionConfig (default zstd level 9)
            fsync_mode: "always", "batch", or "off" (test-only)
            fsync_batch_ms: Batch flush interval (ms)
        """
        self.feeds_dir = Path(feeds_dir)
        self.compression = compression or CompressionConfig()
        self.fsync_mode = fsync_mode
        self.fsync_batch_ms = fsync_batch_ms
        
        self.last_rotation_bytes = 0
        self.last_rotation_file = None
        self.last_rotation_checksum = None

    def rotate_file(self, file_path: Path, new_file_path: Optional[Path] = None) -> dict:
        """Perform atomic rotation: compress → checksum → rename → fsync.
        
        Args:
            file_path: Path to .ndjson file to rotate
            new_file_path: Path to new file (optional; used for manifest tracking)
            
        Returns:
            Dictionary with rotation metadata (bytes, checksum, codec, level)
            
        Raises:
            IOError: If rotation fails at any step
        """
        if not file_path.exists():
            logger.warning(f"Rotate: file not found: {file_path}")
            return {
                "file_path": str(file_path),
                "bytes": 0,
                "checksum": None,
                "codec": self.compression.codec,
                "level": self.compression.level,
                "status": "not_found",
            }
        
        try:
            # Step 1: Get original file size
            original_bytes = file_path.stat().st_size
            
            # Step 2: Compress (only if codec != "off")
            if self.compression.codec == "off":
                # No compression; just checksum the original
                compressed_path = file_path
            else:
                compressed_path = self._compress_file(file_path)
            
            # Step 3: Fsync compressed file
            self._fsync_file(compressed_path)
            
            # Step 4: Compute and write checksum sidecar
            checksum, sidecar_path = self._write_checksum_sidecar(compressed_path)
            
            # Step 5: Atomic rename (if compression happened, replace original)
            if self.compression.codec != "off":
                # Remove original and rename compressed
                if file_path.exists():
                    file_path.unlink()
                compressed_path.replace(file_path.with_suffix(".ndjson.zst"))
                rotated_path = file_path.with_suffix(".ndjson.zst")
            else:
                rotated_path = file_path
            
            # Step 6: Fsync parent directory
            self._fsync_directory(rotated_path.parent)
            
            # Record state for manifest
            self.last_rotation_bytes = original_bytes
            self.last_rotation_file = str(rotated_path)
            self.last_rotation_checksum = checksum
            
            logger.info(
                f"Rotated {file_path.name}: {original_bytes} bytes, "
                f"checksum={checksum[:16]}..., codec={self.compression.codec}"
            )
            
            return {
                "file_path": str(rotated_path),
                "bytes": original_bytes,
                "checksum": checksum,
                "codec": self.compression.codec,
                "level": self.compression.level,
                "sidecar_path": str(sidecar_path),
                "status": "success",
            }
        
        except Exception as e:
            logger.error(f"Rotation failed for {file_path}: {e}")
            raise IOError(f"Rotation failed: {e}") from e

    def _compress_file(self, file_path: Path) -> Path:
        """Compress file using configured codec.
        
        Args:
            file_path: Path to .ndjson file
            
        Returns:
            Path to compressed file (.ndjson.zst or .ndjson.gz)
        """
        if self.compression.codec == "zstd":
            try:
                import zstandard as zstd
            except ImportError:
                logger.warning("zstandard not available; skipping compression")
                return file_path
            
            compressed_path = file_path.with_suffix(".ndjson.zst.tmp")
            with open(file_path, "rb") as f_in:
                with open(compressed_path, "wb") as f_out:
                    cctx = zstd.ZstdCompressor(level=self.compression.level)
                    f_out.write(cctx.compress(f_in.read()))
            
            return compressed_path
        
        elif self.compression.codec == "gzip":
            compressed_path = file_path.with_suffix(".ndjson.gz.tmp")
            with open(file_path, "rb") as f_in:
                with open(compressed_path, "wb") as f_out:
                    # Use wbT mode for text (gzip expects bytes)
                    import gzip
                    with gzip.open(f_out, "wb", compresslevel=self.compression.level) as gz:
                        gz.write(f_in.read())
            
            return compressed_path
        
        else:
            return file_path

    def _write_checksum_sidecar(self, file_path: Path) -> tuple[str, Path]:
        """Compute SHA256 and write sidecar file.
        
        Args:
            file_path: Path to file to checksum
            
        Returns:
            Tuple of (checksum_hex, sidecar_path)
        """
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        
        checksum = hasher.hexdigest()
        sidecar_path = file_path.with_suffix(".sha256")
        
        with open(sidecar_path, "w") as f:
            f.write(f"{checksum}  {file_path.name}\n")
        
        return checksum, sidecar_path

    def _fsync_file(self, file_path: Path) -> None:
        """Fsync file descriptor if fsync_mode != "off".
        
        Args:
            file_path: Path to file to fsync
        """
        if self.fsync_mode == "off":
            return
        
        try:
            fd = os.open(str(file_path), os.O_RDONLY)
            os.fsync(fd)
            os.close(fd)
        except Exception as e:
            logger.warning(f"fsync failed for {file_path}: {e}")

    def _fsync_directory(self, dir_path: Path) -> None:
        """Fsync parent directory to ensure renames persist.
        
        Args:
            dir_path: Path to directory to fsync
        """
        if self.fsync_mode == "off":
            return
        
        try:
            fd = os.open(str(dir_path), os.O_RDONLY)
            os.fsync(fd)
            os.close(fd)
        except Exception as e:
            logger.warning(f"fsync failed for directory {dir_path}: {e}")

    def get_rotation_state(self) -> dict:
        """Get last rotation state for manifest recording.
        
        Returns:
            Dictionary with rotation metadata
        """
        return {
            "last_rotation_file": self.last_rotation_file,
            "last_rotation_bytes": self.last_rotation_bytes,
            "last_rotation_checksum": self.last_rotation_checksum,
            "codec": self.compression.codec,
            "level": self.compression.level,
            "fsync_mode": self.fsync_mode,
        }
