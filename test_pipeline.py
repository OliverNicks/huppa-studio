import json
from pathlib import Path
from adapters.registry import registry
from core.aggregator import aggregate_canonical_df
from core.image_resolver import OpenCartImageResolver


def process_catalog(file_path: str):
    path = Path(file_path)
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    print(f"\n--- Processing: {path.name} ---")

    # 1. Ingestion & Normalization (Phase 1)
    df_canonical = registry.load_and_normalize(str(path))
    print(f"[Phase 1] Normalized {len(df_canonical)} raw rows.")

    # 2. Aggregation & Entity Grouping (Phase 2)
    products = aggregate_canonical_df(df_canonical)
    print(f"[Phase 2] Aggregated into {len(products)} parent products.")

    # 3. Attach Local OpenCart Images (Phase 2.1)
    resolver = OpenCartImageResolver()
    matched_count = resolver.attach_images_to_catalog(products)
    print(f"[Phase 2.1] Attached OpenCart images for {matched_count}/{len(products)} products.")

    # 4. Save Intermediate Checkpoint
    output_file = output_dir / f"{path.stem}_aggregated.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump([p.model_dump(mode="json") for p in products], f, ensure_ascii=False, indent=2)

    print(f"[+] Saved intermediate JSON to: {output_file}")

    # Preview first parent product
    if products:
        p = products[0]
        print(f"\nSample Parent Product:")
        print(f" - ID: {p.parent_id}")
        print(f" - Brand & Model: {p.brand} {p.model_name}")
        print(f" - Base Price: {p.base_price} UAH")
        print(f" - Total Stock: {p.total_stock}")
        print(f" - Variants Count: {len(p.size_variants)}")
        print(f" - Main Image: {p.main_image}")
        print(f" - Gallery Images: {p.gallery_images}")


if __name__ == "__main__":
    # Test both datasets sequentially
    test_files = [
        "data/huppa.xlsx",
    ]

    for f in test_files:
        p = Path(f)
        if p.exists():
            process_catalog(str(p))
        else:
            print(f"[!] File not found: {f}")