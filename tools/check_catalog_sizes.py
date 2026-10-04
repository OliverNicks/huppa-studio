import os
import sys
import json
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# The exact sizes currently existing in Mirohost DB for 'Размер'
DB_EXISTING_SIZES = {
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL",
    "62", "68", "74", "80", "86", "92", "98", "104", "110",
    "116", "122", "128", "134", "140", "146", "152", "158", "164", "170"
}

def analyze_sizes():
    catalog_path = Path("data/huppa.xlsx")
    if not catalog_path.exists():
        print(f"[!] File not found: {catalog_path}")
        return

    print("[*] Reading supplier catalog to find all unique sizes...")
    df = pd.read_excel(catalog_path, engine="openpyxl")
    
    # Locate size column
    size_col = None
    for col in df.columns:
        if "розмір" in str(col).lower() or "размер" in str(col).lower():
            size_col = col
            break
            
    if not size_col:
        print("[!] Could not find size column in spreadsheet headers:", df.columns[:10])
        return

    # Extract all non-empty sizes
    raw_sizes = df[size_col].dropna().astype(str).str.strip()
    raw_sizes = raw_sizes.str.replace(r"\.0$", "", regex=True)
    unique_sizes = sorted(list(set(raw_sizes)))

    print(f"\n[+] Total unique sizes found in supplier Excel: {len(unique_sizes)}")
    print(f"[+] All supplier sizes: {unique_sizes}\n")

    matched = [s for s in unique_sizes if s in DB_EXISTING_SIZES]
    missing = [s for s in unique_sizes if s not in DB_EXISTING_SIZES]

    print("=" * 60)
    print(f"MATCHED ({len(matched)} sizes already exist in OpenCart):")
    print(", ".join(matched))
    print("=" * 60)
    print(f"MISSING ({len(missing)} sizes MUST BE ADDED to OpenCart):")
    print(", ".join(missing))
    print("=" * 60)

    # Generate SQL to insert missing sizes
    if missing:
        sql_lines = [
            "-- SQL to insert all missing HUPPA sizes into OCFilter",
            "SET @size_opt_id = (SELECT `option_id` FROM `oc_ocfilter_option_description` WHERE LOWER(`name`) IN ('размер', 'розмір') LIMIT 1);",
            "SET @max_val_id = (SELECT IFNULL(MAX(`value_id`), 4274011350) FROM `oc_ocfilter_option_value`);\n"
        ]
        
        start_id = 4274011400
        for idx, sz in enumerate(missing, 1):
            val_id = start_id + idx
            sql_lines.append(f"""-- Size: {sz}
INSERT IGNORE INTO `oc_ocfilter_option_value` (`value_id`, `option_id`, `sort_order`)
VALUES ({val_id}, @size_opt_id, 0);

INSERT IGNORE INTO `oc_ocfilter_option_value_description` (`value_id`, `option_id`, `language_id`, `name`)
VALUES 
    ({val_id}, @size_opt_id, 1, '{sz}'),
    ({val_id}, @size_opt_id, 3, '{sz}');
""")

        sql_output = "\n".join(sql_lines)
        out_path = Path("output/insert_missing_sizes.sql")
        out_path.parent.mkdir(exist_ok=True)
        out_path.write_text(sql_output, encoding="utf-8")
        print(f"\n[+] Generated SQL for missing sizes saved to: {out_path}")

if __name__ == "__main__":
    analyze_sizes()
