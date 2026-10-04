import re
import pandas as pd
from pathlib import Path

def audit_catalog_photos(file_path: str = "data/huppa.xlsx"):
    path = Path(file_path)
    if not path.exists():
        print(f"[!] File not found: {file_path}")
        return

    print(f"Reading {path.name}...")
    if path.suffix in [".xlsx", ".xls"]:
        df = pd.read_excel(file_path)
    else:
        df = pd.read_csv(file_path, low_memory=False)

    total_rows = len(df)
    print(f"Total rows in dataset: {total_rows}\n")

    # Find all photo columns
    # Exclude Cyrillic 'фото' (Google Drive non-direct links)
    all_image_cols = []
    cyrillic_cols = []
    
    for c in df.columns:
        c_str = str(c).strip()
        c_lower = c_str.lower()
        if "фото" in c_lower:
            cyrillic_cols.append(c)
        elif c_lower == "url" or "foto" in c_lower:
            all_image_cols.append(c)

    # Sort columns: URL first, then Foto 1, Foto 2...
    url_cols = [c for c in all_image_cols if str(c).strip().lower() == "url"]
    foto_cols = [c for c in all_image_cols if str(c).strip().lower() != "url"]
    foto_cols.sort(key=lambda x: int(re.findall(r"\d+", str(x))[0]) if re.findall(r"\d+", str(x)) else 0)
    ordered_target_cols = url_cols + foto_cols

    print("=" * 75)
    print("1. TARGET IMAGE COLUMNS IN EXCEL (URL & Latin Foto)")
    print("=" * 75)
    
    col_stats = []
    total_valid_urls_all = set()

    for col in ordered_target_cols:
        series = df[col].dropna().astype(str).str.strip()
        non_empty = len(series[series != ""])
        valid_urls = series[series.str.startswith(("http://", "https://"))]
        valid_count = len(valid_urls)
        unique_urls = valid_urls.nunique()
        sample = valid_urls.iloc[0] if len(valid_urls) > 0 else "None"
        
        for u in valid_urls:
            total_valid_urls_all.add(u)
            
        col_stats.append({
            "Column": col,
            "Non-empty rows": non_empty,
            "Valid HTTP(S) URLs": valid_count,
            "Unique URLs": unique_urls,
            "Sample": sample[:70] + "..." if len(sample) > 70 else sample
        })
        
        print(f"Column: '{col}'")
        print(f"  - Non-empty rows:     {non_empty:,}")
        print(f"  - Valid HTTP(S) URLs: {valid_count:,}")
        print(f"  - Unique URLs:        {unique_urls:,}")
        print(f"  - Sample URL:         {sample}\n")

    print("=" * 75)
    print("2. CYRILLIC 'ФОТО' COLUMNS (Excluded Google Drive links)")
    print("=" * 75)
    for col in cyrillic_cols:
        series = df[col].dropna().astype(str).str.strip()
        valid = series[series.str.startswith(("http://", "https://"))]
        sample = valid.iloc[0] if len(valid) > 0 else "None"
        print(f"Column: '{col}' -> {len(valid):,} links (Sample: {sample})")

    print("\n" + "=" * 75)
    print("3. UNIQUE IMAGES PER PARENT PRODUCT CARD (Model + Color)")
    print("=" * 75)
    
    # Derive parent_id
    def get_parent_id(row):
        art = str(row.get("Артикул", "")).strip()
        if art and art.lower() != "nan" and "-" in art:
            return art.rsplit("-", 1)[0]
        model = str(row.get("модель", "")).replace(".0", "").strip()
        color = str(row.get("номер коляру", "")).replace(".0", "").strip()
        return f"{model}-{color.zfill(5)}" if model and color else "unknown"

    df["_parent_id"] = df.apply(get_parent_id, axis=1)
    df_clean = df[df["_parent_id"] != "unknown"]
    
    grouped = df_clean.groupby("_parent_id", sort=False)
    total_parents = len(grouped)
    
    parent_photo_counts = {}
    parents_with_main_url = 0
    parents_without_main_url = 0
    total_unique_photos_across_catalog = set()

    for pid, grp in grouped:
        p_urls = []
        # Main photo
        has_url = False
        for c in url_cols:
            if c in grp.columns:
                vals = grp[c].dropna().astype(str).str.strip()
                for v in vals:
                    if v.startswith(("http://", "https://")) and v not in p_urls:
                        p_urls.append(v)
                        has_url = True
                        break
        if has_url:
            parents_with_main_url += 1
        else:
            parents_without_main_url += 1

        # Gallery photos
        for c in foto_cols:
            if c in grp.columns:
                vals = grp[c].dropna().astype(str).str.strip()
                for v in vals:
                    if v.startswith(("http://", "https://")) and v not in p_urls:
                        p_urls.append(v)
                        break
                        
        count = len(p_urls)
        parent_photo_counts[count] = parent_photo_counts.get(count, 0) + 1
        for u in p_urls:
            total_unique_photos_across_catalog.add(u)

    print(f"Total parent product cards:                {total_parents:,}")
    print(f"Products with Main Photo (from 'URL'):     {parents_with_main_url:,} ({parents_with_main_url/total_parents*100:.1f}%)")
    print(f"Products WITHOUT Main Photo (only Foto):   {parents_without_main_url:,}")
    print(f"Total distinct image files to download:    {len(total_unique_photos_across_catalog):,}\n")
    
    print("Photo count distribution per product card:")
    for num_photos in sorted(parent_photo_counts.keys()):
        print(f"  - Exactly {num_photos} photo(s): {parent_photo_counts[num_photos]:,} products")

    print("\n" + "=" * 75)

if __name__ == "__main__":
    audit_catalog_photos()
