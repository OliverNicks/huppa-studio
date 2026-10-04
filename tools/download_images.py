import os
import re
import sys
import time
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# Directory where images will be saved locally
IMAGES_DIR = Path("./opencart_images")
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Manifest tracking which parent products have already had their existing gallery files shifted (+1)
# This strictly prevents double-shifting if the script is run multiple times.
MANIFEST_FILE = IMAGES_DIR / ".shifted_manifest.json"

# Global registry to prevent downloading duplicate URLs across different products
# Mapping: {url: "catalog/product/filename.jpg"}
URL_TO_OPENCART_PATH: Dict[str, str] = {}

# Session configured to look like a desktop browser
session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,uk;q=0.8",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "cross-site",
})


def load_shifted_manifest() -> Set[str]:
    """Loads set of parent_ids whose gallery photos have already been shifted."""
    if MANIFEST_FILE.exists():
        try:
            with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception:
            return set()
    return set()


def save_shifted_manifest(shifted_set: Set[str]):
    """Persists shifted parent_ids to disk."""
    try:
        with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(shifted_set)), f, indent=2)
    except Exception as e:
        print(f"[!] Warning: Could not save shifted manifest: {e}")


def get_parent_id(row: pd.Series) -> str:
    """
    Derives unique parent SKU from the article code (e.g., '21700010-00009-00L' -> '21700010-00009').
    Fallback: Model + Color (5-digit padded).
    """
    article = str(row.get("Артикул", "")).strip()
    if article and article.lower() != "nan" and "-" in article:
        return article.rsplit("-", 1)[0]

    model = str(row.get("модель", "")).replace(".0", "").strip()
    color = str(row.get("номер коляру", "")).replace(".0", "").strip()
    if model and color:
        padded_color = color.zfill(5) if color.isdigit() else color
        return f"{model}-{padded_color}"
    return "unknown_product"


def find_image_columns(df: pd.DataFrame) -> Tuple[Optional[str], List[str]]:
    """
    Discovers image columns in exact OpenCart priority order:
    1. Main photo column: 'URL' (case-insensitive) -> becomes {parent_id}_0.jpg
    2. Gallery photo columns: Latin 'Foto 1', 'Foto 2', ..., naturally sorted -> become {parent_id}_1.jpg, _2.jpg...
    Excludes Cyrillic 'фото' (which contain Google Drive non-direct links).
    Returns (url_col, list_of_foto_cols).
    """
    main_col: Optional[str] = None
    gallery_cols: List[str] = []

    for col in df.columns:
        c_str = str(col).strip()
        c_lower = c_str.lower()

        # Strictly ignore Cyrillic 'фото' (Google Drive links)
        if "фото" in c_lower:
            continue

        # 1. Main Cover Photo column (URL)
        if c_lower == "url":
            main_col = col
        # 2. Gallery photos (Foto 1, Foto 2, Foto 3...)
        elif "foto" in c_lower:
            gallery_cols.append(col)

    # Sort gallery columns naturally (Foto 1, Foto 2, ... Foto 8)
    def sort_key(name):
        nums = re.findall(r"\d+", str(name))
        return int(nums[0]) if nums else 0

    gallery_cols.sort(key=sort_key)
    return main_col, gallery_cols


def shift_existing_photos_for_parent(parent_id: str, shifted_manifest: Set[str]) -> bool:
    """
    Shifts existing local photos on disk by +1:
      _0.jpg -> _1.jpg
      _1.jpg -> _2.jpg
      _2.jpg -> _3.jpg
      ...
    This frees up index 0 for the newly introduced main photo from column 'URL',
    preserving all previously downloaded gallery photos without re-downloading them!
    Guards against double-shifting via shifted_manifest.
    """
    if parent_id in shifted_manifest:
        return False  # Already shifted in a previous run

    # Find all existing indexed images for this parent on disk
    pattern = re.compile(rf"^{re.escape(parent_id)}_(\d+)\.(jpg|jpeg|png|webp)$", re.IGNORECASE)
    matches: List[Tuple[int, Path, str]] = []

    for f in IMAGES_DIR.glob(f"{parent_id}_*.*"):
        if f.is_file():
            m = pattern.match(f.name)
            if m:
                idx = int(m.group(1))
                matches.append((idx, f, f.suffix))

    if not matches:
        # No local files exist yet for this product, nothing to shift
        shifted_manifest.add(parent_id)
        return False

    # Sort descending by index to shift safely from highest to lowest (e.g., 2->3, 1->2, 0->1)
    matches.sort(key=lambda x: x[0], reverse=True)

    print(f"[{parent_id}] Shifting {len(matches)} existing photo(s) (+1) to reserve index 0 for main photo...")
    for idx, file_path, ext in matches:
        new_name = f"{parent_id}_{idx + 1}{ext}"
        new_path = IMAGES_DIR / new_name
        try:
            os.replace(file_path, new_path)
        except Exception as err:
            print(f"    [!] Error shifting {file_path.name} -> {new_name}: {err}")

    shifted_manifest.add(parent_id)
    return True


def stream_to_file(response: requests.Response, destination: Path) -> bool:
    """Writes binary image chunks to disk."""
    try:
        with open(destination, "wb") as f:
            for chunk in response.iter_content(chunk_size=32768):
                if chunk:
                    f.write(chunk)
        return True
    except Exception:
        return False


def download_image(url: str, destination: Path) -> bool:
    """
    Downloads an image via HTTPS with browser headers and extension fallbacks.
    """
    clean_url = url.strip()

    # Enforce HTTPS (avoids port 80 redirects and blocked plain HTTP)
    if clean_url.startswith("http://"):
        clean_url = "https://" + clean_url[7:]

    candidates = [clean_url]

    # Extension fallbacks on 404 (.jpg <-> .JPG <-> .png)
    if clean_url.endswith(".jpg"):
        candidates.extend([clean_url[:-4] + ".JPG", clean_url[:-4] + ".png"])
    elif clean_url.endswith(".png"):
        candidates.extend([clean_url[:-4] + ".PNG", clean_url[:-4] + ".jpg"])
    elif clean_url.endswith(".JPG"):
        candidates.extend([clean_url[:-4] + ".jpg", clean_url[:-4] + ".png"])

    # Base domain Referer to bypass anti-hotlinking
    domain_match = re.match(r"(https?://[^/]+)", clean_url)
    domain_referer = domain_match.group(1) + "/" if domain_match else None

    req_headers = {}
    if domain_referer:
        req_headers["Referer"] = domain_referer

    for target_url in candidates:
        try:
            res = session.get(target_url, headers=req_headers, stream=True, timeout=15, allow_redirects=True)
            if res.status_code == 200:
                content_type = res.headers.get("Content-Type", "").lower()
                if "text/html" not in content_type:
                    return stream_to_file(res, destination)
        except Exception:
            continue

    return False


def download_parent_images(parent_id: str, urls: List[str], overwrite: bool = False) -> List[str]:
    """
    Downloads images for a parent product in strict order:
      - urls[0] (from 'URL')    -> {parent_id}_0.jpg (Main Cover Photo)
      - urls[1] (from 'Foto 1') -> {parent_id}_1.jpg (Gallery Photo 1)
      - urls[2] (from 'Foto 2') -> {parent_id}_2.jpg (Gallery Photo 2)
      - ...
    """
    db_relative_paths: List[str] = []

    for idx, url in enumerate(urls):
        # 1. Reuse already downloaded image if the exact URL was seen before
        if url in URL_TO_OPENCART_PATH and not overwrite:
            existing_path = URL_TO_OPENCART_PATH[url]
            print(f"[{parent_id}] Reusing existing image ({existing_path}) for duplicate URL")
            db_relative_paths.append(existing_path)
            continue

        filename = f"{parent_id}_{idx}.jpg"
        local_filepath = IMAGES_DIR / filename
        opencart_db_path = f"catalog/product/{filename}"

        role = "MAIN PHOTO" if idx == 0 else f"GALLERY #{idx}"

        # 2. Check local disk cache (shifted files will hit here without re-downloading!)
        if local_filepath.exists() and not overwrite:
            print(f"[{parent_id}] Cache hit ({role}): {filename} already exists.")
            URL_TO_OPENCART_PATH[url] = opencart_db_path
            db_relative_paths.append(opencart_db_path)
            continue

        print(f"[{parent_id}] Downloading {role} -> {filename} from {url[:60]}...")
        success = download_image(url, local_filepath)

        if success:
            URL_TO_OPENCART_PATH[url] = opencart_db_path
            db_relative_paths.append(opencart_db_path)
            time.sleep(0.1)  # Polite pacing
        else:
            print(f"    [!] FAILED: {url}")
            with open("failed_images.txt", "a", encoding="utf-8") as f_fail:
                f_fail.write(f"{parent_id}\t{idx}\t{url}\n")

    return db_relative_paths


def process_catalog_images(
    file_path: str, 
    overwrite: bool = False, 
    no_shift: bool = False
) -> Dict[str, List[str]]:
    path = Path(file_path)
    print(f"Reading file: {path.name}...")

    if path.suffix in [".xlsx", ".xls"]:
        df = pd.read_excel(file_path).dropna(subset=["Артикул"])
    else:
        df = pd.read_csv(file_path, low_memory=False).dropna(subset=["Артикул"])

    # Locate image columns: URL (main) and Foto 1, Foto 2, ...
    url_col, gallery_cols = find_image_columns(df)
    ordered_cols = ([url_col] if url_col else []) + gallery_cols

    print(f"[+] Main photo column detected:    {url_col}")
    print(f"[+] Gallery photo columns detected: {gallery_cols}")
    print(f"[+] Total ordered image columns:    {ordered_cols}\n")

    if not ordered_cols:
        raise ValueError("No matching 'URL' or 'Foto' columns found in the file! Please verify headers.")

    df["parent_id"] = df.apply(get_parent_id, axis=1)

    catalog_image_map: Dict[str, List[str]] = {}
    grouped = df.groupby("parent_id", sort=False)

    shifted_manifest = load_shifted_manifest()
    print(f"[+] Loaded shifted manifest with {len(shifted_manifest)} existing tracked products.")
    print(f"[+] Found {len(grouped)} unique parent products to process.\n")

    processed_count = 0

    for parent_id, group in grouped:
        # Check if this parent has a valid URL in the 'URL' column
        has_main_url = False
        if url_col and url_col in group.columns:
            valid_vals = group[url_col].dropna()
            for v in valid_vals:
                u = str(v).strip()
                if u.startswith("http://") or u.startswith("https://"):
                    has_main_url = True
                    break

        # If this product has a new main photo from 'URL', shift existing local photos (+1)
        # so that existing _0.jpg becomes _1.jpg (Foto 1), _1.jpg becomes _2.jpg (Foto 2), etc.
        if has_main_url and not no_shift:
            shift_existing_photos_for_parent(parent_id, shifted_manifest)

        # Extract URLs across all rows in the group in exact column order:
        # URL (main) -> Foto 1 -> Foto 2 -> ...
        urls: List[str] = []
        for col in ordered_cols:
            if col in group.columns:
                valid_vals = group[col].dropna()
                for val in valid_vals:
                    u = str(val).strip()
                    if (u.startswith("http://") or u.startswith("https://")) and u not in urls:
                        urls.append(u)
                        break  # Found the URL for this column slot, advance to next column

        if urls:
            paths = download_parent_images(parent_id, urls, overwrite=overwrite)
            catalog_image_map[parent_id] = paths
        else:
            catalog_image_map[parent_id] = []

        processed_count += 1
        if processed_count % 50 == 0:
            save_shifted_manifest(shifted_manifest)

    # Save final manifest
    save_shifted_manifest(shifted_manifest)

    print("\n==========================================")
    print("Download and Image Organization complete!")
    print(f"Total unique images mapped in OpenCart: {len(URL_TO_OPENCART_PATH)}")
    print(f"Directory: {IMAGES_DIR.resolve()}")
    if Path("failed_images.txt").exists():
        print("Check 'failed_images.txt' for any URLs that were unreachable.")
    print("==========================================")

    return catalog_image_map


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download and organize Huppa images for OpenCart")
    parser.add_argument("--file", default=r"data\huppa.xlsx", help="Path to input Excel or CSV file")
    parser.add_argument("--overwrite", action="store_true", help="Force re-downloading images even if they already exist")
    parser.add_argument("--no-shift", action="store_true", help="Disable shifting existing files on disk")
    parser.add_argument("--reset-shift-manifest", action="store_true", help="Reset tracking manifest of shifted files")
    args = parser.parse_args()

    if args.reset_shift_manifest and MANIFEST_FILE.exists():
        MANIFEST_FILE.unlink()
        print("[+] Reset .shifted_manifest.json")

    mapping = process_catalog_images(
        file_path=args.file,
        overwrite=args.overwrite,
        no_shift=args.no_shift
    )