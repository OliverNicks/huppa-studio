import os
import re
import sys
import time
import argparse
import urllib.parse
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional
import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# Directory with downloaded images
IMAGES_DIR = Path("./opencart_images")
OUTPUT_DIR = Path("./output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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


def find_target_image_columns(df: pd.DataFrame) -> Tuple[Optional[str], List[str]]:
    """
    Finds ONLY target photo columns:
    1. 'URL' (case-insensitive) -> Main cover photo (_0.jpg)
    2. Latin 'Foto 1', 'Foto 2', ... -> Gallery photos (_1.jpg, _2.jpg...)
    Strictly excludes Cyrillic 'фото' columns.
    """
    main_col: Optional[str] = None
    gallery_cols: List[str] = []

    for col in df.columns:
        c_str = str(col).strip()
        c_lower = c_str.lower()

        # Ignore Cyrillic 'фото'
        if "фото" in c_lower:
            continue

        if c_lower == "url":
            main_col = col
        elif "foto" in c_lower:
            gallery_cols.append(col)

    # Sort gallery columns naturally: Foto 1, Foto 2, ... Foto 8
    def sort_key(name):
        nums = re.findall(r"\d+", str(name))
        return int(nums[0]) if nums else 0

    gallery_cols.sort(key=sort_key)
    return main_col, gallery_cols


def sanitize_url(url: str) -> str:
    """Cleans up spaces and converts Google Drive links if possible."""
    clean = url.strip()
    
    # 1. Google Drive direct download transform
    if "drive.google.com" in clean:
        match_id = re.search(r"/d/([a-zA-Z0-9_-]+)", clean) or re.search(r"id=([a-zA-Z0-9_-]+)", clean)
        if match_id:
            file_id = match_id.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"

    # 2. Encode spaces to %20 (vital for filenames with spaces like 'VIVIAN 1_s.jpg')
    clean = clean.replace(" ", "%20")
    
    # 3. Enforce HTTPS
    if clean.startswith("http://"):
        clean = "https://" + clean[7:]

    return clean


def stream_to_file(response: requests.Response, destination: Path) -> bool:
    try:
        with open(destination, "wb") as f:
            for chunk in response.iter_content(chunk_size=32768):
                if chunk:
                    f.write(chunk)
        return True
    except Exception:
        return False


def test_or_download_url(url: str, save_path: Optional[Path] = None) -> Tuple[int, str]:
    """
    Tests URL availability via HTTP. If save_path is provided, saves image if status is 200.
    Returns (status_code, reason/note).
    """
    clean_url = sanitize_url(url)
    candidates = [clean_url]

    # Extension fallbacks on 404 (.jpg <-> .JPG <-> .png)
    if clean_url.endswith(".jpg"):
        candidates.extend([clean_url[:-4] + ".JPG", clean_url[:-4] + ".png"])
    elif clean_url.endswith(".JPG"):
        candidates.extend([clean_url[:-4] + ".jpg", clean_url[:-4] + ".png"])
    elif clean_url.endswith(".png"):
        candidates.extend([clean_url[:-4] + ".PNG", clean_url[:-4] + ".jpg"])

    domain_match = re.match(r"(https?://[^/]+)", clean_url)
    domain_referer = domain_match.group(1) + "/" if domain_match else None
    headers = {"Referer": domain_referer} if domain_referer else {}

    last_status = 0
    last_reason = "Network error"

    for target_url in candidates:
        try:
            res = session.get(target_url, headers=headers, stream=True, timeout=12, allow_redirects=True)
            last_status = res.status_code
            content_type = res.headers.get("Content-Type", "").lower()

            if res.status_code == 200:
                if "text/html" in content_type:
                    return 200, "HTML Error Page (Not an image)"
                if save_path:
                    success = stream_to_file(res, save_path)
                    if success:
                        return 200, "Downloaded successfully"
                    return 500, "Disk write error"
                return 200, "OK (Image reachable)"
            elif res.status_code == 404:
                last_reason = "HTTP 404 Not Found"
            else:
                last_reason = f"HTTP {res.status_code}"
        except Exception as e:
            last_reason = f"Connection failed: {type(e).__name__}"

    return last_status, last_reason


def check_missing_photos(catalog_file: str = "data/huppa.xlsx", retry_download: bool = False):
    path = Path(catalog_file)
    if not path.exists():
        print(f"[!] Catalog file not found: {catalog_file}")
        return

    print("=" * 80)
    print(f"CHECKING PHOTOS: Dataset ('{path.name}') vs Folder ('{IMAGES_DIR.resolve()}')")
    print("=" * 80)

    # 1. Index all existing files on disk
    existing_files: Set[str] = set()
    if IMAGES_DIR.exists():
        existing_files = {
            f.name.lower() for f in IMAGES_DIR.iterdir()
            if f.is_file() and f.stat().st_size > 0
        }
    print(f"[+] Total existing image files on disk in '{IMAGES_DIR.name}': {len(existing_files):,}")

    # 2. Read spreadsheet
    print(f"[+] Reading spreadsheet {path.name}...")
    if path.suffix in [".xlsx", ".xls"]:
        df = pd.read_excel(catalog_file).dropna(subset=["Артикул"])
    else:
        df = pd.read_csv(catalog_file, low_memory=False).dropna(subset=["Артикул"])

    url_col, gallery_cols = find_target_image_columns(df)
    ordered_cols = ([url_col] if url_col else []) + gallery_cols
    print(f"[+] Found photo columns: Main='{url_col}', Gallery={gallery_cols}")

    df["_parent_id"] = df.apply(get_parent_id, axis=1)
    grouped = df.groupby("_parent_id", sort=False)
    print(f"[+] Found {len(grouped):,} unique parent products in catalog.\n")

    # 3. Match expected filenames vs disk
    expected_photos: List[Dict] = []
    missing_photos: List[Dict] = []
    present_count = 0

    for parent_id, group in grouped:
        for idx, col in enumerate(ordered_cols):
            if col in group.columns:
                valid_vals = group[col].dropna()
                found_url = None
                for val in valid_vals:
                    u = str(val).strip()
                    if u.startswith(("http://", "https://")):
                        found_url = u
                        break

                if found_url:
                    expected_filename = f"{parent_id}_{idx}.jpg"
                    role = "MAIN PHOTO" if idx == 0 else f"GALLERY #{idx}"
                    
                    # Check disk existence (case-insensitive)
                    is_present = (
                        expected_filename.lower() in existing_files or
                        f"{parent_id}_{idx}.png".lower() in existing_files or
                        f"{parent_id}_{idx}.jpeg".lower() in existing_files or
                        f"{parent_id}_{idx}.webp".lower() in existing_files
                    )

                    item_info = {
                        "parent_id": parent_id,
                        "index": idx,
                        "column": col,
                        "role": role,
                        "filename": expected_filename,
                        "url": found_url,
                        "present": is_present
                    }
                    expected_photos.append(item_info)

                    if is_present:
                        present_count += 1
                    else:
                        missing_photos.append(item_info)

    total_expected = len(expected_photos)
    total_missing = len(missing_photos)

    print("=" * 80)
    print("MATCH SUMMARY:")
    print("=" * 80)
    print(f"Total photos expected from dataset: {total_expected:,}")
    print(f"Photos present in opencart_images:  {present_count:,} ({(present_count/total_expected*100) if total_expected else 0:.1f}%)")
    print(f"Photos MISSING from folder:         {total_missing:,} ({(total_missing/total_expected*100) if total_expected else 0:.1f}%)")
    print("=" * 80)

    if total_missing == 0:
        print("[✓] Perfect! 100% of photos from the dataset are downloaded and present on disk.")
        return

    # 4. Analyze reasons for missing photos
    print(f"\nAnalyzing reasons for {total_missing} missing photos...")
    if retry_download:
        print("[*] Option --retry-download is ENABLED: Attempting to download missing photos...\n")

    missing_by_type = {
        "Google Drive Links": [],
        "URLs with unencoded spaces": [],
        "Standard Huppa URLs": []
    }

    report_rows = []
    recovered_count = 0

    for idx, item in enumerate(missing_photos, 1):
        url = item["url"]
        pid = item["parent_id"]
        fname = item["filename"]

        category = "Standard Huppa URLs"
        if "drive.google.com" in url:
            category = "Google Drive Links"
        elif " " in url:
            category = "URLs with unencoded spaces"

        missing_by_type[category].append(item)

        target_file = (IMAGES_DIR / fname) if retry_download else None
        status, reason = test_or_download_url(url, save_path=target_file)
        
        if retry_download and status == 200 and target_file and target_file.exists():
            recovered_count += 1
            print(f"  [{idx:03d}/{total_missing:03d}] RECOVERED: {fname} from {url[:55]}...")
        else:
            print(f"  [{idx:03d}/{total_missing:03d}] MISSING: {fname} | {category} | {reason} | {url[:60]}")

        item["http_status"] = status
        item["reason"] = reason
        report_rows.append(item)

    # 5. Summary breakdown of missing files
    print("\n" + "=" * 80)
    print("BREAKDOWN OF MISSING PHOTOS BY CAUSE:")
    print("=" * 80)
    for cat_name, items in missing_by_type.items():
        print(f"  - {cat_name:30s}: {len(items):3d} photo(s)")
    if retry_download:
        print(f"\n[+] Successfully recovered and downloaded: {recovered_count}/{total_missing} photos!")

    # 6. Save detailed reports
    report_txt = OUTPUT_DIR / "missing_photos_report.txt"
    with open(report_txt, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write(f"MISSING PHOTOS AUDIT REPORT - {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total expected: {total_expected}\n")
        f.write(f"Present on disk: {present_count}\n")
        f.write(f"Missing from disk: {total_missing}\n\n")
        f.write("Details of Missing Photos:\n")
        f.write("-" * 80 + "\n")
        for row in report_rows:
            f.write(f"Product:   {row['parent_id']}\n")
            f.write(f"Role:      {row['role']} (Column '{row['column']}')\n")
            f.write(f"Filename:  {row['filename']}\n")
            f.write(f"HTTP:      {row.get('http_status')} ({row.get('reason')})\n")
            f.write(f"URL:       {row['url']}\n")
            f.write("-" * 80 + "\n")

    # CSV for Excel opening
    report_csv = OUTPUT_DIR / "missing_photos.csv"
    df_missing = pd.DataFrame(report_rows)
    df_missing.to_csv(report_csv, index=False, encoding="utf-8-sig")

    print(f"\n[✓] Detailed audit text report saved to: {report_txt}")
    print(f"[✓] Detailed spreadsheet CSV saved to:   {report_csv}")
    print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check and audit missing photos between dataset and opencart_images")
    parser.add_argument("--catalog", default="data/huppa.xlsx", help="Path to input Excel or CSV")
    parser.add_argument("--retry-download", action="store_true", help="Attempt to download missing photos (with space and URL fixes)")
    args = parser.parse_args()

    check_missing_photos(args.catalog, retry_download=args.retry_download)
