import os
import sys
import json
import asyncio
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from core.models import ParentProduct
from core.copywriter import AsyncProductCopywriter


async def main():
    json_path = Path("output/reima_aggregated.json")
    if not json_path.exists():
        print(f"[!] File not found: {json_path}. Run test_pipeline.py first.")
        return

    # 1. Load intermediate JSON
    with open(json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # 2. Pick the first product
    product = ParentProduct.model_validate(raw_data[0])
    print(f"Testing Dual-Language Enrichment for: {product.brand} {product.model_name} ({product.parent_id})")

    # 3. Run enrichment
    copywriter = AsyncProductCopywriter(max_concurrency=1)
    enriched_product = await copywriter.enrich_single_product(product)

    res = enriched_product.enriched
    if not res:
        print("[!] Enrichment failed!")
        return

    # 4. Display Ukrainian Results
    print("\n" + "=" * 30 + " UKRAINIAN (UA) " + "=" * 30)
    print(f"Store Title:  {res.ua.name}")
    print(f"Meta Title:   {res.ua.meta_title} ({len(res.ua.meta_title)} chars)")
    print(f"Meta Desc:    {res.ua.meta_description} ({len(res.ua.meta_description)} chars)")
    print(f"Keywords:     {res.ua.meta_keyword}")
    print("\nAttributes:")
    for attr in res.ua.attributes:
        print(f"  • {attr.name}: {attr.value}")
    print(f"\nHTML Description Preview:\n{res.ua.html_description[:300]}...")

    # 5. Display Russian Results
    print("\n" + "=" * 30 + " RUSSIAN (RU) " + "=" * 30)
    print(f"Store Title:  {res.ru.name}")
    print(f"Meta Title:   {res.ru.meta_title} ({len(res.ru.meta_title)} chars)")
    print(f"Meta Desc:    {res.ru.meta_description} ({len(res.ru.meta_description)} chars)")
    print(f"Keywords:     {res.ru.meta_keyword}")
    print("\nAttributes:")
    for attr in res.ru.attributes:
        print(f"  • {attr.name}: {attr.value}")
    print(f"\nHTML Description Preview:\n{res.ru.html_description[:300]}...")

    # 6. Save a serialized sample to output
    out_file = Path("output/dual_enriched_sample.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(enriched_product.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
    print(f"\n[+] Saved validated sample to {out_file}")


if __name__ == "__main__":
    asyncio.run(main())