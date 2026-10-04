"""
Direct URL-to-FTP Photo Uploader for OpenCart (Mirohost)
========================================================
Extracts image links exclusively from spreadsheet columns:
- Column 'URL' (case-insensitive) -> Main cover photo: `{parent_id}_0.jpg`
- Columns 'Foto 1', 'Foto 2'... (Latin only) -> Gallery photos: `{parent_id}_1.jpg`, `_2.jpg`...
- Strictly ignores Cyrillic 'фото' columns (Google Drive web links).

Streams images in-memory (RAM) directly into Mirohost OpenCart FTP (port 21):
`image/catalog/product/{parent_id}_{idx}.jpg`
Zero local disk clutter.
"""

import os
import re
import io
import time
import ftplib
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set, Any, Generator
from dataclasses import dataclass
import pandas as pd
import requests


@dataclass
class ImageUploadTask:
    parent_id: str
    filename: str
    url: str
    is_main: bool
    photo_index: int


@dataclass
class UploadResult:
    total_found: int
    already_on_server: int
    to_upload: int
    uploaded_success: int
    failed: int
    failed_items: List[Tuple[str, str, str]]  # (filename, url, reason)


class DirectPhotoUploader:
    """Manages downloading images from supplier URLs and streaming directly to Mirohost FTP."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,uk;q=0.8",
        })

    @staticmethod
    def get_parent_id(row: pd.Series) -> str:
        """Derives unique parent SKU (model-padded_color)."""
        article = str(row.get("Артикул", "")).strip()
        if article and article.lower() != "nan" and "-" in article:
            return article.rsplit("-", 1)[0]

        model = str(row.get("модель", "")).replace(".0", "").strip()
        color = str(row.get("номер коляру", "")).replace(".0", "").strip()
        if model and color:
            padded_color = color.zfill(5) if color.isdigit() else color
            return f"{model}-{padded_color}"

        # Canonical fallback if dataframe was normalized
        c_m = str(row.get("canonical_model_code", "")).replace(".0", "").strip()
        c_c = str(row.get("canonical_color_code", "")).replace(".0", "").strip()
        if c_m and c_c:
            p_c = c_c.zfill(5) if c_c.isdigit() else c_c
            return f"{c_m}-{p_c}"

        return "unknown"

    @staticmethod
    def discover_image_columns(df: pd.DataFrame) -> Tuple[Optional[str], List[str]]:
        """
        Discovers target image columns:
        1. 'URL' (case-insensitive) -> Main cover photo (_0.jpg)
        2. Latin 'Foto 1', 'Foto 2'... -> Gallery photos (_1.jpg, _2.jpg...)
        Strictly ignores Cyrillic 'фото'.
        """
        main_col: Optional[str] = None
        gallery_cols: List[str] = []

        for col in df.columns:
            c_str = str(col).strip()
            c_lower = c_str.lower()

            if "фото" in c_lower:
                continue

            if c_lower == "url":
                main_col = col
            elif "foto" in c_lower:
                gallery_cols.append(col)

        def natural_sort_key(name):
            nums = re.findall(r"\d+", str(name))
            return int(nums[0]) if nums else 0

        gallery_cols.sort(key=natural_sort_key)
        return main_col, gallery_cols

    def build_tasks_from_dataframe(
        self,
        df: pd.DataFrame,
        existing_remote_files: Optional[Set[str]] = None
    ) -> Tuple[List[ImageUploadTask], int]:
        """
        Scans DataFrame and returns list of missing photo upload tasks.
        Returns (tasks_to_upload, already_on_server_count).
        """
        remote_lower = {f.lower() for f in existing_remote_files} if existing_remote_files else set()

        main_col, gallery_cols = self.discover_image_columns(df)
        tasks: List[ImageUploadTask] = []
        already_present = 0
        seen_filenames: Set[str] = set()

        df_copy = df.copy()
        df_copy["_parent_id"] = df_copy.apply(self.get_parent_id, axis=1)

        for parent_id, group in df_copy.groupby("_parent_id", sort=False):
            if parent_id == "unknown":
                continue

            # 1. Main Cover Photo from column 'URL'
            if main_col and main_col in group.columns:
                val = group[main_col].dropna().astype(str).str.strip()
                valid_urls = [u for u in val if u.startswith(("http://", "https://"))]
                if valid_urls:
                    target_name = f"{parent_id}_0.jpg"
                    if target_name.lower() in remote_lower:
                        already_present += 1
                    elif target_name not in seen_filenames:
                        seen_filenames.add(target_name)
                        tasks.append(
                            ImageUploadTask(
                                parent_id=parent_id,
                                filename=target_name,
                                url=valid_urls[0],
                                is_main=True,
                                photo_index=0
                            )
                        )

            # 2. Gallery photos from Latin 'Foto 1', 'Foto 2'...
            for idx, col in enumerate(gallery_cols, start=1):
                if col in group.columns:
                    val = group[col].dropna().astype(str).str.strip()
                    valid_urls = [u for u in val if u.startswith(("http://", "https://"))]
                    if valid_urls:
                        target_name = f"{parent_id}_{idx}.jpg"
                        if target_name.lower() in remote_lower:
                            already_present += 1
                        elif target_name not in seen_filenames:
                            seen_filenames.add(target_name)
                            tasks.append(
                                ImageUploadTask(
                                    parent_id=parent_id,
                                    filename=target_name,
                                    url=valid_urls[0],
                                    is_main=False,
                                    photo_index=idx
                                )
                            )

        return tasks, already_present

    def build_tasks_from_products(
        self,
        products: List[Any],
        existing_remote_files: Optional[Set[str]] = None
    ) -> Tuple[List[ImageUploadTask], int]:
        """
        Builds missing image tasks from a list of ParentProduct objects (e.g. from cache).
        """
        remote_lower = {f.lower() for f in existing_remote_files} if existing_remote_files else set()
        tasks: List[ImageUploadTask] = []
        already_present = 0
        seen_filenames: Set[str] = set()

        for p in products:
            p_id = getattr(p, "parent_id", "").replace("_", "-")
            m_code = getattr(p, "model_code", "").strip()
            c_code = getattr(p, "color_code", "").strip()
            padded_color = c_code.zfill(5) if c_code.isdigit() else c_code
            clean_pid = f"{m_code}-{padded_color}" if m_code and padded_color else p_id

            urls = getattr(p, "image_urls", []) or []
            for idx, u in enumerate(urls):
                url_str = str(u).strip()
                if not (url_str.startswith("http://") or url_str.startswith("https://")):
                    continue
                target_name = f"{clean_pid}_{idx}.jpg"
                if target_name.lower() in remote_lower:
                    already_present += 1
                elif target_name not in seen_filenames:
                    seen_filenames.add(target_name)
                    tasks.append(
                        ImageUploadTask(
                            parent_id=clean_pid,
                            filename=target_name,
                            url=url_str,
                            is_main=(idx == 0),
                            photo_index=idx
                        )
                    )

        return tasks, already_present

    def fetch_image_bytes(self, url: str) -> Tuple[Optional[bytes], str]:
        """Downloads image bytes from URL with fallback extensions and header protections."""
        clean_url = url.strip().replace(" ", "%20")
        if clean_url.startswith("http://"):
            clean_url = "https://" + clean_url[7:]

        candidates = [clean_url]
        if clean_url.endswith(".jpg"):
            candidates.extend([clean_url[:-4] + ".JPG", clean_url[:-4] + ".png"])
        elif clean_url.endswith(".png"):
            candidates.extend([clean_url[:-4] + ".PNG", clean_url[:-4] + ".jpg"])
        elif clean_url.endswith(".JPG"):
            candidates.extend([clean_url[:-4] + ".jpg", clean_url[:-4] + ".png"])

        domain_match = re.match(r"(https?://[^/]+)", clean_url)
        referer = domain_match.group(1) + "/" if domain_match else None
        headers = {"Referer": referer} if referer else {}

        last_err = "Unknown error"
        for target_url in candidates:
            try:
                res = self.session.get(target_url, headers=headers, timeout=12)
                if res.status_code == 200:
                    c_type = res.headers.get("Content-Type", "").lower()
                    if "text/html" in c_type:
                        return None, "HTML Error Page (Not an image)"
                    return res.content, "OK"
                elif res.status_code == 404:
                    last_err = "HTTP 404 Not Found"
                else:
                    last_err = f"HTTP {res.status_code}"
            except Exception as e:
                last_err = f"Download connection error: {e}"

        return None, last_err

    def upload_missing_photos_generator(
        self,
        tasks: List[ImageUploadTask],
        ftp_host: str,
        ftp_user: str,
        ftp_pass: str,
        ftp_port: int = 21,
        remote_dir: str = "image/catalog/product"
    ) -> Generator[Dict[str, Any], None, UploadResult]:
        """
        Connects to FTP and streams missing photos one by one.
        Yields progress dictionaries for real-time Streamlit updates.
        Returns final UploadResult.
        """
        total = len(tasks)
        if total == 0:
            return UploadResult(0, 0, 0, 0, 0, [])

        ftp: Optional[ftplib.FTP] = None

        def get_ftp_conn():
            c = ftplib.FTP()
            c.connect(ftp_host, ftp_port, timeout=15)
            c.login(ftp_user, ftp_pass)
            try:
                c.cwd(remote_dir)
            except Exception:
                pass
            return c

        try:
            ftp = get_ftp_conn()
        except Exception as e:
            yield {"type": "error", "message": f"Не вдалося підключитися до FTP {ftp_host}:{ftp_port}: {e}"}
            return UploadResult(total, 0, total, 0, total, [(t.filename, t.url, str(e)) for t in tasks])

        uploaded_success = 0
        failed_count = 0
        failed_items = []
        uploaded_tasks: List[ImageUploadTask] = []

        for idx, task in enumerate(tasks, start=1):
            # 1. Fetch image into RAM
            img_bytes, fetch_status = self.fetch_image_bytes(task.url)
            if not img_bytes:
                failed_count += 1
                failed_items.append((task.filename, task.url, fetch_status))
                yield {
                    "type": "progress",
                    "current": idx,
                    "total": total,
                    "filename": task.filename,
                    "parent_id": task.parent_id,
                    "status": "error",
                    "error": fetch_status
                }
                continue

            # 2. Upload to FTP
            upload_ok = False
            for attempt in range(2):
                try:
                    bio = io.BytesIO(img_bytes)
                    ftp.storbinary(f"STOR {task.filename}", bio)
                    upload_ok = True
                    break
                except Exception as ftp_err:
                    # Reconnect and retry once
                    try:
                        ftp.close()
                    except Exception:
                        pass
                    try:
                        ftp = get_ftp_conn()
                    except Exception:
                        pass

            if upload_ok:
                uploaded_success += 1
                uploaded_tasks.append(task)
                yield {
                    "type": "progress",
                    "current": idx,
                    "total": total,
                    "filename": task.filename,
                    "parent_id": task.parent_id,
                    "status": "success",
                    "size_kb": len(img_bytes) / 1024
                }
            else:
                failed_count += 1
                failed_items.append((task.filename, task.url, "FTP Upload failed"))
                yield {
                    "type": "progress",
                    "current": idx,
                    "total": total,
                    "filename": task.filename,
                    "parent_id": task.parent_id,
                    "status": "error",
                    "error": "Помилка передачі по FTP"
                }

        if ftp:
            try:
                ftp.quit()
            except Exception:
                try:
                    ftp.close()
                except Exception:
                    pass

        result = UploadResult(
            total_found=total,
            already_on_server=0,
            to_upload=total,
            uploaded_success=uploaded_success,
            failed=failed_count,
            failed_items=failed_items
        )
        yield {
            "type": "complete",
            "result": result,
            "uploaded_tasks": uploaded_tasks
        }
        return result


def link_uploaded_images_in_opencart_db(
    uploaded_tasks: List[ImageUploadTask],
    host: str,
    user: str,
    password: str,
    database: str,
    port: int = 3306,
    table_prefix: str = "oc_"
) -> Tuple[int, int, str]:
    """
    Updates `oc_product.image` and inserts gallery rows into `oc_product_image`
    for the newly uploaded photos.
    Returns (main_updated_count, gallery_inserted_count, message).
    """
    if not uploaded_tasks:
        return 0, 0, "Немає завантажених фото для лінкування."

    import pymysql
    try:
        conn = pymysql.connect(
            host=host.strip(),
            user=user.strip(),
            password=password,
            database=database.strip(),
            port=int(port),
            charset="utf8mb4",
            connect_timeout=10,
            autocommit=True
        )

        main_updated = 0
        gallery_inserted = 0

        with conn.cursor() as cur:
            for t in uploaded_tasks:
                img_rel_path = f"catalog/product/{t.filename}"
                p_code = t.parent_id  # e.g., '21700010-00009'

                if t.is_main:
                    # Update cover photo if empty or set
                    q = f"""
                    UPDATE `{table_prefix}product`
                    SET `image` = %s
                    WHERE (`model` = %s OR `sku` = %s OR `sku` = %s)
                      AND (`image` = '' OR `image` IS NULL);
                    """
                    p_code_under = p_code.replace("-", "_")
                    cur.execute(q, (img_rel_path, p_code, p_code, p_code_under))
                    if cur.rowcount > 0:
                        main_updated += cur.rowcount
                else:
                    # Insert gallery photo
                    q = f"""
                    INSERT INTO `{table_prefix}product_image` (`product_id`, `image`, `sort_order`)
                    SELECT p.`product_id`, %s, %s
                    FROM `{table_prefix}product` p
                    WHERE (p.`model` = %s OR p.`sku` = %s OR p.`sku` = %s)
                      AND NOT EXISTS (
                          SELECT 1 FROM `{table_prefix}product_image` pi
                          WHERE pi.`product_id` = p.`product_id` AND pi.`image` = %s
                      );
                    """
                    p_code_under = p_code.replace("-", "_")
                    cur.execute(q, (img_rel_path, t.photo_index, p_code, p_code, p_code_under, img_rel_path))
                    if cur.rowcount > 0:
                        gallery_inserted += cur.rowcount

        conn.close()
        return main_updated, gallery_inserted, f"Оновлено {main_updated} головних фото та додано {gallery_inserted} фото галереї в базу OpenCart."

    except Exception as e:
        return 0, 0, f"Помилка прив'язки в базі даних: {e}"
