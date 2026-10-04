import asyncio
import json
from pathlib import Path

from core.aggregator import aggregate_canonical_df
from core.enrichment_graph import enrich_single_product_graph
from core.image_resolver import OpenCartImageResolver
from core.models import ParentProduct
from core.sql_exporter import OpenCartSQLExporter
from adapters.registry import registry


async def generate_huppa_test_sql():
    # 1. Load and aggregate raw Huppa price list
    print("[1] Зчитування Huppa...")
    df = registry.load_and_normalize("data/huppa.xlsx")
    products = aggregate_canonical_df(df)

    # 2. Attach images from opencart_images/
    resolver = OpenCartImageResolver()
    resolver.attach_images_to_catalog(products)

    # 3. Pick specific model HUPPA FREJA (21700010_9)
    product = next((p for p in products if "21700010" in p.parent_id), products[0])
    print(f"[2] Обробка товару: {product.brand} {product.model_name} ({product.parent_id})")
    print(f"    Головне фото:    {product.main_image}")
    print(f"    Фото в галереї:  {product.gallery_images}")

    # 4. Enrich via Double-Agent LangGraph (UA + RU + OCFilter)
    enriched_product = await enrich_single_product_graph(product)

    # 5. Generate SQL with exact database settings
    exporter = OpenCartSQLExporter(
        table_prefix="oc_",
        lang_ua_id=3,
        lang_ru_id=1,
        size_option_id=11,
        attribute_group_id=7
    )

    out_file = "output/huppa_sample.sql"
    exporter.generate_sql([enriched_product], out_file)
    print(f"[+] SQL успішно створено: {out_file}")


if __name__ == "__main__":
    asyncio.run(generate_huppa_test_sql())