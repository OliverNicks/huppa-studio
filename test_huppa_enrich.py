import json
import asyncio
from pathlib import Path
from core.models import ParentProduct
from core.copywriter import AsyncProductCopywriter


async def main():
    json_path = Path("output/huppa_aggregated.json")
    if not json_path.exists():
        print(f"[!] File not found: {json_path}. Run test_pipeline.py first.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # Pick the first product with a non-empty description
    product_dict = next((item for item in raw_data if item.get("raw_description")), raw_data[0])
    product = ParentProduct.model_validate(product_dict)

    print(f"Testing Huppa Enrichment for: {product.brand} {product.model_name} (ID: {product.parent_id})")
    print(f"Raw description preview:\n{product.raw_description[:200]}...\n")

    copywriter = AsyncProductCopywriter(max_concurrency=1)
    enriched_product = await copywriter.enrich_single_product(product)

    res = enriched_product.enriched
    if not res:
        print("[!] Enrichment failed!")
        return

    print("=" * 30 + " UKRAINIAN (UA) " + "=" * 30)
    print(f"Store Title:  {res.ua.name}")
    print(f"Meta Title:   {res.ua.meta_title} ({len(res.ua.meta_title)} chars)")
    print(f"Meta Desc:    {res.ua.meta_description} ({len(res.ua.meta_description)} chars)")
    print(f"Keywords:     {res.ua.meta_keyword}")
    print("\nAttributes:")
    for attr in res.ua.attributes:
        print(f"  • {attr.name}: {attr.value}")
    print(f"\nHTML Description Preview:\n{res.ua.html_description}")

    print("\n" + "=" * 30 + " RUSSIAN (RU) " + "=" * 30)
    print(f"Store Title:  {res.ru.name}")
    print(f"Meta Title:   {res.ru.meta_title} ({len(res.ru.meta_title)} chars)")
    print(f"Meta Desc:    {res.ru.meta_description} ({len(res.ru.meta_description)} chars)")
    print(f"Keywords:     {res.ru.meta_keyword}")
    print("\nAttributes:")
    for attr in res.ru.attributes:
        print(f"  • {attr.name}: {attr.value}")


if __name__ == "__main__":
    asyncio.run(main())