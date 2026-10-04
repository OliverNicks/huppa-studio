"""
SFTP Photo Auditor for Mirohost OpenCart Hosting
=================================================
Connects to Mirohost via SFTP/SSH to audit product images directly on the remote server:
- Lists all images in `image/catalog/product/` within seconds (no file downloads).
- Checks main cover photos (_0.jpg) and gallery angles (_1.jpg, _2.jpg...).
- Identifies missing photos, partial galleries, and orphaned files consuming disk space.
"""

import os
import re
import socket
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, field
import paramiko

from core.models import ParentProduct


@dataclass
class RemotePhotoStats:
    filename: str
    size_bytes: int
    modified_time: int


@dataclass
class ProductPhotoAuditResult:
    parent_id: str
    model_code: str
    color_code: str
    model_name: str
    color_name: str
    expected_main: str
    found_main: Optional[str]
    expected_gallery: List[str]
    found_gallery: List[str]
    status: str  # "ok", "main_only", "missing_main", "missing_all"
    missing_files: List[str]


@dataclass
class AuditSummary:
    total_remote_images: int
    total_remote_size_mb: float
    total_products_checked: int
    products_with_all_photos: int
    products_main_only: int
    products_missing_main: int
    products_missing_all: int
    orphaned_files_count: int
    orphaned_files_size_mb: float
    results: List[ProductPhotoAuditResult]
    orphaned_files: List[str]


class MirohostSFTPClient:
    """Manages connection and operations over SFTP to Mirohost."""

    COMMON_SEARCH_PATHS = [
        "image/catalog/product",
        "image/catalog/products",
        "huppa.com.ua/image/catalog/product",
        "www/huppa.com.ua/image/catalog/product",
        "public_html/image/catalog/product",
        "data/www/huppa.com.ua/image/catalog/product",
    ]

    def __init__(
        self,
        host: str,
        username: str,
        password: Optional[str] = None,
        key_path: Optional[str] = None,
        port: int = 21,
        timeout: int = 10,
    ):
        self.host = host.strip()
        self.username = username.strip()
        self.password = password
        self.key_path = key_path
        self.port = int(port)
        self.timeout = timeout
        self.ssh_client: Optional[paramiko.SSHClient] = None
        self.sftp_client: Optional[paramiko.SFTPClient] = None
        self.ftp_client: Optional[Any] = None
        self.is_ftp = (self.port == 21)

    def connect(self) -> Tuple[bool, str]:
        """Establishes FTP or SFTP connections based on port."""
        if not self.password and not (self.key_path and os.path.exists(self.key_path)):
            return False, "Не вказано пароль для підключення."

        if self.is_ftp:
            import ftplib
            try:
                self.ftp_client = ftplib.FTP()
                self.ftp_client.connect(self.host, self.port, timeout=self.timeout)
                self.ftp_client.login(self.username, self.password or "")
                return True, f"FTP з'єднання успішно встановлено з {self.host}:21."
            except ftplib.error_perm as e:
                return False, f"Помилка авторизації FTP: невірний логін або пароль ({e})"
            except Exception as e:
                return False, f"Помилка FTP з'єднання з {self.host}:{self.port} — {e}"

        # Otherwise, SFTP (SSH)
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": self.host,
                "port": self.port,
                "username": self.username,
                "timeout": self.timeout,
            }

            if self.key_path and os.path.exists(self.key_path):
                connect_kwargs["key_filename"] = self.key_path
            elif self.password:
                connect_kwargs["password"] = self.password

            self.ssh_client.connect(**connect_kwargs)
            self.sftp_client = self.ssh_client.open_sftp()
            return True, f"SFTP з'єднання успішно встановлено з {self.host}:{self.port}."

        except paramiko.AuthenticationException:
            return False, "Помилка автентифікації SFTP: невірний логін або пароль."
        except (paramiko.SSHException, socket.error) as e:
            return False, f"Помилка з'єднання з хостом {self.host}:{self.port} — {e}"
        except Exception as e:
            return False, f"Непередбачена помилка SFTP: {e}"

    def close(self):
        """Closes connections."""
        if self.ftp_client:
            try:
                self.ftp_client.quit()
            except Exception:
                try:
                    self.ftp_client.close()
                except Exception:
                    pass
            self.ftp_client = None

        if self.sftp_client:
            try:
                self.sftp_client.close()
            except Exception:
                pass
            self.sftp_client = None

        if self.ssh_client:
            try:
                self.ssh_client.close()
            except Exception:
                pass
            self.ssh_client = None

    def resolve_remote_dir(self, specified_path: str = "") -> Optional[str]:
        """
        Verifies if the specified directory exists.
        If not found or empty, tests common Mirohost paths.
        """
        candidates = []
        if specified_path.strip():
            clean_p = specified_path.strip().rstrip("/")
            candidates.append(clean_p)

        candidates.extend(self.COMMON_SEARCH_PATHS)

        # For FTP
        if self.is_ftp and self.ftp_client:
            original_cwd = None
            try:
                original_cwd = self.ftp_client.pwd()
            except Exception:
                pass

            for path in candidates:
                try:
                    self.ftp_client.cwd(path)
                    # Check if there are files in this folder
                    items = self.ftp_client.nlst()
                    if any(Path(it).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") for it in items):
                        return path
                except Exception:
                    continue
                finally:
                    if original_cwd:
                        try:
                            self.ftp_client.cwd(original_cwd)
                        except Exception:
                            pass
            return None

        # For SFTP
        if not self.sftp_client:
            return None

        for path in candidates:
            try:
                attrs = self.sftp_client.stat(path)
                import stat
                if stat.S_ISDIR(attrs.st_mode):
                    return path
            except Exception:
                continue

        return None

    def list_remote_images(self, remote_dir: str) -> Dict[str, RemotePhotoStats]:
        """
        Quickly fetches metadata for all images in remote directory without downloading.
        Returns a dictionary mapping lowercase filename -> RemotePhotoStats.
        """
        remote_images = {}
        image_extensions = {".jpg", ".jpeg", ".png", ".webp"}

        if self.is_ftp and self.ftp_client:
            try:
                self.ftp_client.cwd(remote_dir)
                try:
                    # Try MLSD first (fast and gives sizes)
                    for name, facts in self.ftp_client.mlsd():
                        ext = Path(name).suffix.lower()
                        if ext in image_extensions:
                            size = int(facts.get("size", 0))
                            remote_images[name.lower()] = RemotePhotoStats(
                                filename=name,
                                size_bytes=size,
                                modified_time=0
                            )
                except Exception:
                    # Fallback to NLST
                    for name in self.ftp_client.nlst():
                        ext = Path(name).suffix.lower()
                        if ext in image_extensions:
                            try:
                                size = self.ftp_client.size(name) or 0
                            except Exception:
                                size = 0
                            remote_images[name.lower()] = RemotePhotoStats(
                                filename=name,
                                size_bytes=size,
                                modified_time=0
                            )
            except Exception as e:
                print(f"[!] Error listing FTP directory {remote_dir}: {e}")
            return remote_images

        if not self.sftp_client:
            return {}

        try:
            for file_attr in self.sftp_client.listdir_attr(remote_dir):
                name = file_attr.filename
                ext = Path(name).suffix.lower()
                if ext in image_extensions:
                    remote_images[name.lower()] = RemotePhotoStats(
                        filename=name,
                        size_bytes=file_attr.st_size,
                        modified_time=file_attr.st_mtime,
                    )
        except Exception as e:
            print(f"[!] Error listing SFTP directory {remote_dir}: {e}")

        return remote_images


def audit_products_against_remote(
    products: List[ParentProduct],
    remote_images: Dict[str, RemotePhotoStats]
) -> AuditSummary:
    """
    Compares active catalog products against remote images on Mirohost.
    """
    results: List[ProductPhotoAuditResult] = []
    used_remote_files: Set[str] = set()

    for p in products:
        m_code = p.model_code.strip() if p.model_code else ""
        c_code = p.color_code.strip() if p.color_code else ""
        padded_color = c_code.zfill(5) if c_code.isdigit() else c_code

        # Candidate prefixes
        prefixes = [
            f"{m_code}-{padded_color}",
            f"{m_code}_{padded_color}",
            f"{m_code}-{c_code}",
            f"{m_code}_{c_code}",
        ]
        if p.parent_id:
            prefixes.append(p.parent_id.replace("_", "-"))
            prefixes.append(p.parent_id)

        # Unique prefixes keeping order
        unique_prefixes = []
        for pref in prefixes:
            if pref and pref not in unique_prefixes:
                unique_prefixes.append(pref)

        # 1. Main Cover Photo Search (_0.jpg, .jpg, etc.)
        found_main = None
        expected_main = f"{m_code}-{padded_color}_0.jpg"

        for pref in unique_prefixes:
            for ext in [".jpg", ".png", ".webp", ".jpeg"]:
                c_main_0 = f"{pref}_0{ext}".lower()
                c_main_alt = f"{pref}{ext}".lower()

                if c_main_0 in remote_images:
                    found_main = remote_images[c_main_0].filename
                    used_remote_files.add(c_main_0)
                    break
                elif c_main_alt in remote_images:
                    found_main = remote_images[c_main_alt].filename
                    used_remote_files.add(c_main_alt)
                    break
            if found_main:
                break

        # 2. Gallery Photos Search (_1.jpg, _2.jpg...)
        found_gallery = []
        expected_gallery = []
        # Check angles up to 8
        for angle in range(1, 9):
            angle_expected = f"{m_code}-{padded_color}_{angle}.jpg"
            angle_found = False
            for pref in unique_prefixes:
                for ext in [".jpg", ".png", ".webp", ".jpeg"]:
                    cand_angle = f"{pref}_{angle}{ext}".lower()
                    if cand_angle in remote_images:
                        found_gallery.append(remote_images[cand_angle].filename)
                        used_remote_files.add(cand_angle)
                        angle_found = True
                        break
                if angle_found:
                    break

            if angle <= 3:  # Expect at least angles 1-3 for standard Huppa catalog
                expected_gallery.append(angle_expected)

        # Determine status
        missing_files = []
        if not found_main:
            missing_files.append(expected_main)

        if found_main and found_gallery:
            status = "ok"
        elif found_main and not found_gallery:
            status = "main_only"
        elif not found_main and found_gallery:
            status = "missing_main"
        else:
            status = "missing_all"

        results.append(
            ProductPhotoAuditResult(
                parent_id=p.parent_id,
                model_code=m_code,
                color_code=c_code,
                model_name=p.model_name,
                color_name=p.color_name,
                expected_main=expected_main,
                found_main=found_main,
                expected_gallery=expected_gallery,
                found_gallery=found_gallery,
                status=status,
                missing_files=missing_files,
            )
        )

    # Compute orphaned files
    orphaned_files = []
    orphaned_size_bytes = 0
    total_remote_size_bytes = sum(item.size_bytes for item in remote_images.values())

    for f_lower, stats in remote_images.items():
        if f_lower not in used_remote_files:
            orphaned_files.append(stats.filename)
            orphaned_size_bytes += stats.size_bytes

    return AuditSummary(
        total_remote_images=len(remote_images),
        total_remote_size_mb=round(total_remote_size_bytes / (1024 * 1024), 2),
        total_products_checked=len(products),
        products_with_all_photos=sum(1 for r in results if r.status == "ok"),
        products_main_only=sum(1 for r in results if r.status == "main_only"),
        products_missing_main=sum(1 for r in results if r.status == "missing_main"),
        products_missing_all=sum(1 for r in results if r.status == "missing_all"),
        orphaned_files_count=len(orphaned_files),
        orphaned_files_size_mb=round(orphaned_size_bytes / (1024 * 1024), 2),
        results=results,
        orphaned_files=orphaned_files,
    )
