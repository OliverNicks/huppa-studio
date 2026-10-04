"""
Cache Backup Manager for OpenCart Pipeline
=========================================
Manages automated snapshot backups and rotation for data/enriched_cache.jsonl.
Maintains strictly the 10 most recent backups sorted by timestamp with human-readable dates.
"""

import shutil
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

DEFAULT_BACKUP_DIR = Path("data/cache_backups")
MAX_BACKUPS_DEFAULT = 10


def get_backup_dir(base_dir: Optional[Path] = None) -> Path:
    """Returns the backup directory path, creating it if necessary."""
    if base_dir is None:
        base_dir = DEFAULT_BACKUP_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def create_cache_backup(
    cache_path: Path,
    backup_dir: Optional[Path] = None,
    max_backups: int = MAX_BACKUPS_DEFAULT,
    tag: str = ""
) -> Optional[Path]:
    """
    Creates a timestamped snapshot of the given cache file and rotates
    older backups so that at most `max_backups` (default 10) are retained.

    Returns:
        Path to the newly created backup file, or None if cache_path does not exist.
    """
    cache_file = Path(cache_path)
    if not cache_file.exists() or cache_file.stat().st_size == 0:
        return None

    target_dir = get_backup_dir(backup_dir)
    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S")
    tag_suffix = f"_{tag.strip()}" if tag.strip() else ""
    backup_filename = f"cache_backup_{timestamp_str}{tag_suffix}.jsonl"
    backup_target = target_dir / backup_filename

    # Perform atomic copy with metadata preservation
    shutil.copy2(cache_file, backup_target)
    try:
        os.utime(backup_target, None)
    except Exception:
        pass

    # Rotate old backups - keep strictly max_backups most recent
    rotate_backups(target_dir, max_backups=max_backups)

    return backup_target


def parse_backup_timestamp(filename: str, fallback_mtime: float) -> datetime:
    """Extracts the precise backup creation timestamp from the filename."""
    try:
        clean = filename.replace("cache_backup_", "")
        parts = clean.split("_")
        date_str = f"{parts[0]}_{parts[1].split('.')[0]}"
        return datetime.strptime(date_str, "%Y-%m-%d_%H-%M-%S")
    except Exception:
        return datetime.fromtimestamp(fallback_mtime)


def rotate_backups(backup_dir: Optional[Path] = None, max_backups: int = MAX_BACKUPS_DEFAULT) -> int:
    """
    Keeps only the `max_backups` newest backups in the directory and deletes older ones.
    Returns the number of deleted old backups.
    """
    target_dir = get_backup_dir(backup_dir)
    backup_files = sorted(
        [f for f in target_dir.glob("cache_backup_*.jsonl") if f.is_file()],
        key=lambda f: parse_backup_timestamp(f.name, f.stat().st_mtime),
        reverse=True
    )

    deleted_count = 0
    if len(backup_files) > max_backups:
        for old_file in backup_files[max_backups:]:
            try:
                old_file.unlink()
                deleted_count += 1
            except Exception:
                pass

    return deleted_count


def count_file_lines(file_path: Path) -> int:
    """Fast line counter for jsonl files."""
    try:
        count = 0
        with open(file_path, "rb") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
    except Exception:
        return 0


def list_cache_backups(backup_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Returns a sorted list of all available backups (newest first)
    with human-readable date, file size, line count, and path.
    """
    target_dir = get_backup_dir(backup_dir)
    backup_files = sorted(
        [f for f in target_dir.glob("cache_backup_*.jsonl") if f.is_file()],
        key=lambda f: parse_backup_timestamp(f.name, f.stat().st_mtime),
        reverse=True
    )

    results = []
    for f in backup_files:
        stat = f.stat()
        created_dt = parse_backup_timestamp(f.name, stat.st_mtime)
        results.append({
            "filename": f.name,
            "path": f,
            "datetime": created_dt,
            "formatted_date": created_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "lines_count": count_file_lines(f),
        })

    return results


def restore_cache_backup(backup_path: Path, target_cache: Path) -> bool:
    """
    Restores the cache file from a specified backup snapshot.
    Safely creates a pre-restore safety copy of the current cache before overwriting.
    """
    backup_file = Path(backup_path)
    target_file = Path(target_cache)

    if not backup_file.exists():
        return False

    # Create emergency backup of current target before overwriting
    if target_file.exists() and target_file.stat().st_size > 0:
        create_cache_backup(target_file, tag="pre_restore")

    shutil.copy2(backup_file, target_file)
    return True
