import json
import asyncio
from pathlib import Path
from core.models import ParentProduct
from core.enrichment_graph import enrich_single_product_graph


async def main():
    # 1. Prefer Huppa, fallback to Reima intermediate JSON
    json_path = Path("output/huppa_aggregated.json")
    if not json_path.exists():
        json_path = Path("output/reima_aggregated.json")

    if not json_path.exists():
        print(f"[!] Neither output/huppa_aggregated.json nor output/reima_aggregated.json exists.")
        print("Please run test_pipeline.py first to generate aggregated data.")
        return

    # 2. Load intermediate JSON
    with open(json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # 3. Pick the first product
    product = ParentProduct.model_validate(raw_data[0])
    print(f"\n=======================================================")
    print(f"Testing Double-Agent LangGraph Enrichment for:")
    print(f"Brand & Model: {product.brand} {product.model_name}")
    print(f"Parent ID:     {product.parent_id}")
    print(f"=======================================================\n")

    # 4. Run Double-Agent Enrichment
    enriched_product = await enrich_single_product_graph(product)

    res = enriched_product.enriched
    if not res:
        print("[!] Enrichment failed!")
        return

    # 5. Display Ukrainian Storefront & SEO
    print("\n" + "=" * 30 + " UKRAINIAN (UA) " + "=" * 30)
    print(f"Store Title:  {res.ua.name}")
    print(f"Meta H1:      {res.ua.meta_h1}")
    print(f"Meta Title:   {res.ua.meta_title} ({len(res.ua.meta_title)} chars)")
    print(f"Meta Desc:    {res.ua.meta_description} ({len(res.ua.meta_description)} chars)")
    print(f"Keywords:     {res.ua.meta_keyword}")
    print("\nAttributes (Характеристики UA):")
    for attr in res.ua.attributes:
        print(f"  • {attr.name}: {attr.value}")
    print(f"\nHTML Description Preview (UA):\n{res.ua.html_description[:300]}...")

    # 6. Display Russian Storefront & SEO
    print("\n" + "=" * 30 + " RUSSIAN (RU) " + "=" * 30)
    print(f"Store Title:  {res.ru.name}")
    print(f"Meta H1:      {res.ru.meta_h1}")
    print(f"Meta Title:   {res.ru.meta_title} ({len(res.ru.meta_title)} chars)")
    print(f"Meta Desc:    {res.ru.meta_description} ({len(res.ru.meta_description)} chars)")
    print(f"Keywords:     {res.ru.meta_keyword}")
    print("\nAttributes (Характеристики RU):")
    for attr in res.ru.attributes:
        print(f"  • {attr.name}: {attr.value}")

    # 7. Display OCFilter Options
    print("\n" + "=" * 30 + " OCFILTER DICTIONARY " + "=" * 30)
    for filter_name, values in res.ocfilters.items():
        print(f"  • {filter_name}: {values}")

    # 8. Save a serialized sample to output
    out_file = Path("output/graph_enriched_sample.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(enriched_product.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
    print(f"\n[+] Saved validated sample to {out_file}")


if __name__ == "__main__":
    asyncio.run(main())
