import json
import asyncio
from pathlib import Path
from core.models import ParentProduct
from core.copywriter import AsyncProductCopywriter


async def main():
    json_path = Path("output/reima_aggregated.json")
    with open(json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    products = [ParentProduct.model_validate(item) for item in raw_data]
    print(f"Loaded {len(products)} products from {json_path.name}")

    copywriter = AsyncProductCopywriter(max_concurrency=3)

    # Test run on the first 5 items
    print("\nRunning async batch enrichment on 5 items...")
    enriched_products = await copywriter.enrich_catalog_batch(products, max_items=5)

    # Save to a dedicated enriched JSON file
    out_path = Path("output/reima_enriched_sample.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([p.model_dump(mode="json") for p in enriched_products[:5]], f, ensure_ascii=False, indent=2)

    print(f"\n[+] Saved sample enriched file to: {out_path}")
    print(f"Sample 1 Title: {enriched_products[0].enriched.meta_title}")
    print(f"Sample 5 Title: {enriched_products[4].enriched.meta_title}")


if __name__ == "__main__":
    asyncio.run(main())