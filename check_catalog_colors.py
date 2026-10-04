import re
from collections import Counter
from pathlib import Path
import pandas as pd

# The 18 colors currently in Mirohost DB for 'Цвет'
DB_EXISTING_COLORS = {
    "бежевый", "белый", "бордовый", "голубой", "жёлтый", "зеленый",
    "коричневый", "красный", "лайм", "морская волна", "оранжевый",
    "розовый", "серый", "синий", "тёмно-синий", "фиолетовый", "фуксия", "чёрный"
}

def analyze_dataset_colors():
    catalog_path = Path("data/huppa.xlsx")
    if not catalog_path.exists():
        print(f"[!] File not found: {catalog_path}")
        return

    print("[*] Reading supplier catalog (data/huppa.xlsx)...")
    df = pd.read_excel(catalog_path, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]

    color_col = next((c for c in df.columns if c.upper() in ["КОЛІР", "ЦВЕТ", "COLOR"]), None)
    if not color_col:
        print("[!] No color column found. Headers:", list(df.columns[:10]))
        return

    raw_series = df[color_col].dropna().astype(str).str.strip()
    color_counts = Counter(raw_series)

    print(f"\n[+] Total rows with color: {len(raw_series)}")
    print(f"[+] Unique raw color descriptions: {len(color_counts)}")

    # Extract base color keywords
    # Known potential candidates for new colors in kids outerwear
    potential_new_colors = {
        "хаки": ["хаки", "хакі", "khaki", "олива", "оливк"],
        "бирюзовый": ["бирюз", "бірюз", "turquoise"],
        "мятный": ["мятн", "м'ятн", "mint"],
        "пудровый": ["пудр", "powder"],
        "сиреневый": ["сирен", "бузков", "лаван"],
        "серебристый": ["серебр", "срібл", "silver", "металік", "металлик"],
        "золотистый": ["золот", "gold"],
        "коралловый": ["коралл", "корал"],
        "джинс": ["джинс", "denim"],
        "малиновый": ["малин"],
        "персиковый": ["персик"],
        "горчичный": ["горчич", "гірчич"],
    }

    # Analyze how raw colors match existing DB colors vs potential new colors
    existing_matches = Counter()
    new_candidates = Counter()
    unclassified = []

    for raw_val, count in color_counts.items():
        val_lower = raw_val.lower()
        matched_existing = False
        
        # Check against existing DB colors
        for db_c in DB_EXISTING_COLORS:
            # normalization for check
            check_c = db_c.replace("ё", "е")
            if check_c in val_lower.replace("ё", "е") or db_c in val_lower:
                existing_matches[db_c] += count
                matched_existing = True
                break
        
        # Check against potential new colors
        matched_new = False
        for new_name, patterns in potential_new_colors.items():
            if any(p in val_lower for p in patterns):
                new_candidates[new_name] += count
                matched_new = True
                break

        if not matched_existing and not matched_new:
            unclassified.append((raw_val, count))

    print("\n" + "=" * 65)
    print("1. COVERAGE BY CURRENT DATABASE COLORS (18 COLORS)")
    print("=" * 65)
    for c, cnt in existing_matches.most_common():
        print(f"  - {c.ljust(18)} : {cnt} products")

    print("\n" + "=" * 65)
    print("2. CANDIDATES FOR NEW COLORS FOUND IN SPREADSHEET")
    print("=" * 65)
    if new_candidates:
        for c, cnt in new_candidates.most_common():
            print(f"  + [NEW] {c.ljust(14)} : {cnt} products (e.g. {potential_new_colors[c][0]})")
    else:
        print("  No major unmapped color groups found.")

    print("\n" + "=" * 65)
    print(f"3. UNCLASSIFIED OR UNIQUE COMPOSITE SHADES ({len(unclassified)} distinct labels)")
    print("=" * 65)
    for raw_val, cnt in sorted(unclassified, key=lambda x: x[1], reverse=True)[:20]:
        print(f"  ? {raw_val.ljust(35)} : {cnt} products")

    # Generate full report to file
    report_lines = [
        "=== HUPPA CATALOG COLOR AUDIT REPORT ===",
        f"Total rows: {len(raw_series)}",
        f"Distinct color values: {len(color_counts)}\n",
        "--- ALL UNIQUE SUPPLIER COLOR VALUES IN DATASET ---"
    ]
    for val, cnt in color_counts.most_common():
        report_lines.append(f"{cnt:4d} x {val}")

    out_report = Path("output/color_audit_report.txt")
    out_report.parent.mkdir(exist_ok=True)
    out_report.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n[+] Detailed color audit written to: {out_report}")

if __name__ == "__main__":
    analyze_dataset_colors()
