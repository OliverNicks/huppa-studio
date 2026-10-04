import os
import sys
import asyncio
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from adapters.registry import registry
from core.aggregator import aggregate_canonical_df
from core.image_resolver import OpenCartImageResolver
from core.enrichment_graph import enrich_single_product_graph
from core.sql_exporter import OpenCartSQLExporter


# 5 representative parent IDs across 5 distinct clothing categories:
# 1. Overall:    36080004_90147 (HUPPA GOLDEN)
# 2. Jacket:     18160010_90086 (HUPPA ALEXIS)
# 3. Set:        41190114_93335 (HUPPA YOKO 1)
# 4. Coat:       21700010_00009 (HUPPA FREJA)
# 5. Trousers:   32130020_00020 (HUPPA ZIPPY)
TARGET_PARENT_IDS = [
    "36080004_90147",
    "18160010_90086",
    "41190114_93335",
    "21700010_00009",
    "32130020_00020"
]


async def run_test_five_items():
    catalog_path = "data/huppa.xlsx"
    if not Path(catalog_path).exists():
        print(f"[!] File not found: {catalog_path}")
        return

    print("=" * 70)
    print("STEP 1: Load and Normalize Raw Spreadsheet")
    print("=" * 70)
    df = registry.load_and_normalize(catalog_path)
    print(f"[+] Loaded and normalized {len(df)} rows from {catalog_path}")

    print("\n" + "=" * 70)
    print("STEP 2: Aggregate Rows into Parent Products")
    print("=" * 70)
    products = aggregate_canonical_df(df)
    print(f"[+] Formed {len(products)} total parent products.")

    # Select the 5 target products
    selected_products = []
    for pid in TARGET_PARENT_IDS:
        prefix = pid.split('_')[0]
        match = next((p for p in products if p.parent_id == pid or p.model_code == prefix or prefix in p.parent_id), None)
        if match and match not in selected_products:
            selected_products.append(match)

    print(f"[+] Selected {len(selected_products)} diverse test products:")
    for idx, p in enumerate(selected_products, 1):
        print(f"  {idx}. [{p.parent_id}] {p.brand} {p.model_name} ({p.product_type}) | Gender: {p.gender} | Season: {p.season} | Stock: {p.total_stock} pcs | Price: {p.base_price} UAH")

    print("\n" + "=" * 70)
    print("STEP 3: Resolve Local Images from opencart_images/")
    print("=" * 70)
    resolver = OpenCartImageResolver(images_dir="opencart_images", opencart_prefix="catalog/product/")
    for p in selected_products:
        matched_paths = resolver.resolve_for_product(p)
        p.local_image_paths = matched_paths
        print(f"[+] {p.parent_id}: Main cover={'YES' if p.main_image else 'NO'}, Gallery photos={len(p.gallery_images)}")

    print("\n" + "=" * 70)
    print("STEP 4: Run Double-Agent AI Enrichment (Analyst + Copywriter)")
    print("=" * 70)
    enriched_products = []
    for idx, p in enumerate(selected_products, 1):
        print(f"\n[{idx}/5] Enriching {p.brand} {p.model_name} ({p.parent_id})...")
        enriched = await enrich_single_product_graph(p)
        enriched_products.append(enriched)
        
        res = enriched.enriched
        if res:
            print(f"  -> UA Name:      {res.ua.name}")
            print(f"  -> Main Cat ID:  {enriched.main_category_id} (All: {enriched.category_ids})")
            print(f"  -> OCFilter:     {list(res.ocfilters.keys())}")
            print(f"  -> Gender in OCFilter: {res.ocfilters.get('Пол', [])}")
            print(f"  -> Season in OCFilter: {res.ocfilters.get('Сезон', [])}")
            print(f"  -> Sizes in OCFilter:  {res.ocfilters.get('Размер', [])}")
            print(f"  -> Color in OCFilter:  {res.ocfilters.get('Цвет', [])}")
            print(f"  -> Type in OCFilter:   {res.ocfilters.get('Тип', [])}")

    print("\n" + "=" * 70)
    print("STEP 5: Generate OpenCart SQL Migration for 5 Products")
    print("=" * 70)
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    out_sql = output_dir / "test_five_items.sql"

    exporter = OpenCartSQLExporter(
        table_prefix="oc_",
        lang_ua_id=3,
        lang_ru_id=1,
        size_option_id=11,
        attribute_group_id=7
    )
    exporter.generate_sql(enriched_products, str(out_sql))

    print(f"[+] Successfully exported combined SQL migration to: {out_sql}")
    print(f"    Total SQL file size: {out_sql.stat().st_size} bytes")

    print("\n" + "=" * 70)
    print("TEST SUMMARY FOR 5 PRODUCTS:")
    print("=" * 70)
    for p in enriched_products:
        print(f"\nProduct: {p.brand} {p.model_name} (ID: {p.parent_id})")
        print(f" - Price:         {p.base_price} UAH")
        print(f" - Special Price: {p.special_price} UAH (АКЦІЯ)" if p.special_price else " - Special Price: Немає")
        print(f" - Main Category: ID {p.main_category_id}")
        print(f" - Categories:    {p.category_ids}")
        print(f" - Sizes:         {[f'{v.size} (qty:{v.stock})' for v in p.size_variants]}")
        print(f" - Stock:         {p.total_stock} шт. (Статус складу: {'В наявності' if p.total_stock > 0 else 'Немає в наявності'})")
        print(f" - Main Image:    {p.main_image}")
        print(f" - Gallery (x{len(p.gallery_images)}): {p.gallery_images}")
        if p.enriched:
            print(f" - SEO Title UA:  {p.enriched.ua.meta_title}")
            print(f" - H1 UA:         {p.enriched.ua.meta_h1}")
            print(f" - OCFilter keys: {list(p.enriched.ocfilters.keys())}")
            print(f" - OCFilter vals: {p.enriched.ocfilters}")

    print("\n" + "=" * 70)
    print(f"DONE! SQL script ready at '{out_sql}'")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_test_five_items())
