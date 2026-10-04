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


async def test_single_item(filter_term: str = "36080004"):
    catalog_path = "data/huppa.xlsx"
    if not Path(catalog_path).exists():
        print(f"[!] File not found: {catalog_path}")
        return

    print("=" * 60)
    print("STEP 1: Load and Normalize Raw Spreadsheet")
    print("=" * 60)
    df = registry.load_and_normalize(catalog_path)
    print(f"[+] Loaded and normalized {len(df)} rows from {catalog_path}")

    print("\n" + "=" * 60)
    print("STEP 2: Aggregate Rows into Parent Products")
    print("=" * 60)
    products = aggregate_canonical_df(df)
    print(f"[+] Formed {len(products)} parent products.")

    # Pick product matching the search filter (defaults to Huppa Golden 36080004)
    target_product = next((p for p in products if filter_term in p.parent_id), products[0])

    print(f"\nTarget Product Selected:")
    print(f" - Brand & Model: {target_product.brand} {target_product.model_name}")
    print(f" - Category Hint: {target_product.product_type}")
    print(f" - Parent ID:     {target_product.parent_id}")
    print(f" - Color:         {target_product.color_name} (Code: {target_product.color_code})")
    print(f" - Base Price:    {target_product.base_price} UAH")
    print(f" - Total Stock:   {target_product.total_stock} pcs")
    print(f" - Size Variants: {[f'{v.size} (Stock: {v.stock}, Price: {v.price})' for v in target_product.size_variants]}")

    print("\n" + "=" * 60)
    print("STEP 3: Resolve Local Images from opencart_images/")
    print("=" * 60)
    resolver = OpenCartImageResolver(images_dir="opencart_images", opencart_prefix="catalog/product/")
    matched_paths = resolver.resolve_for_product(target_product)
    target_product.local_image_paths = matched_paths

    if matched_paths:
        print(f"[+] Found {len(matched_paths)} images:")
        print(f" - Main Cover:    {target_product.main_image}")
        print(f" - Gallery (x{len(target_product.gallery_images)}): {target_product.gallery_images}")
    else:
        print("[!] No local images found in opencart_images/ for this item.")

    print("\n" + "=" * 60)
    print("STEP 4: Run Double-Agent AI Enrichment (Analyst + Copywriter)")
    print("=" * 60)
    print("Calling OpenAI gpt-4o-mini via LangGraph...")
    enriched_product = await enrich_single_product_graph(target_product)

    res = enriched_product.enriched
    if not res:
        print("[!] AI Enrichment failed.")
        return

    # Print results preview
    print("\n--- [UA] UKRAINIAN STOREFRONT & SEO ---")
    print(f"Name:        {res.ua.name}")
    print(f"Meta Title:  {res.ua.meta_title}")
    print(f"Meta Desc:   {res.ua.meta_description}")
    print("Attributes (UA):")
    for a in res.ua.attributes:
        print(f"  • {a.name}: {a.value}")
    print(f"\nHTML Description Preview (UA):\n{res.ua.html_description[:350]}...")

    print("\n--- [RU] RUSSIAN STOREFRONT & SEO ---")
    print(f"Name:        {res.ru.name}")
    print(f"Meta Title:  {res.ru.meta_title}")
    print(f"Meta Desc:   {res.ru.meta_description}")
    print("Attributes (RU):")
    for a in res.ru.attributes:
        print(f"  • {a.name}: {a.value}")

    print("\n--- OCFILTER TAB ---")
    for k, v in res.ocfilters.items():
        print(f"  • {k}: {v}")

    print("\n--- CATEGORIES MATCHED ---")
    print(f"Main Category ID: {enriched_product.main_category_id}")
    print(f"All Category IDs: {enriched_product.category_ids}")

    print("\n" + "=" * 60)
    print("STEP 5: Generate OpenCart SQL Migration")
    print("=" * 60)
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    out_sql = output_dir / f"test_{target_product.parent_id}.sql"

    exporter = OpenCartSQLExporter(
        table_prefix="oc_",
        lang_ua_id=3,
        lang_ru_id=1,
        size_option_id=11,
        attribute_group_id=7
    )
    exporter.generate_sql([enriched_product], str(out_sql))

    print(f"[+] Successfully exported SQL to: {out_sql}")
    print(f"    Total SQL file size: {out_sql.stat().st_size} bytes")

    print("\n" + "=" * 60)
    print(f"DONE! You can inspect '{out_sql}'")
    print("=" * 60)


if __name__ == "__main__":
    # Allow passing a model code via command line: python test_single_item.py <code_or_id>
    search_term = sys.argv[1] if len(sys.argv) > 1 else "36080004"
    asyncio.run(test_single_item(search_term))
