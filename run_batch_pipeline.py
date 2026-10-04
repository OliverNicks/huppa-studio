import os
import sys
import json
import asyncio
import argparse
from pathlib import Path
from typing import List, Dict, Optional

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
from core.models import ParentProduct


class EnrichmentCacheManager:
    """
    Manages persistent JSONL caching of enriched ParentProduct entities.
    Ensures idempotency: products already enriched will not call the LLM again.
    """

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self.cache: Dict[str, ParentProduct] = {}
        self._load()

    def _load(self):
        if not self.cache_path.exists():
            return
        loaded = 0
        with open(self.cache_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    product = ParentProduct.model_validate_json(line)
                    if product.enriched is not None:
                        self.cache[product.parent_id] = product
                        loaded += 1
                except Exception as e:
                    continue
        if loaded > 0:
            print(f"[+] Cache: Loaded {loaded} previously enriched products from {self.cache_path.name}")

    def get(self, parent_id: str) -> Optional[ParentProduct]:
        return self.cache.get(parent_id)

    def save_product(self, product: ParentProduct):
        self.cache[product.parent_id] = product
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "a", encoding="utf-8") as f:
            f.write(product.model_dump_json() + "\n")


import time
import random
import re

# Pacing mechanism: smooth dispatch interval to maximize throughput under 200k TPM
_pacer_lock = asyncio.Lock()
_last_dispatch_time = 0.0
# At ~5,300 tokens/product, 1.65s spacing yields ~36 products/min = 190,000 TPM max
DISPATCH_INTERVAL_SEC = 1.65


async def pace_request():
    """Smooths out request bursts across concurrent workers to prevent 429 TPM limits."""
    global _last_dispatch_time
    async with _pacer_lock:
        now = time.monotonic()
        elapsed = now - _last_dispatch_time
        if elapsed < DISPATCH_INTERVAL_SEC:
            await asyncio.sleep(DISPATCH_INTERVAL_SEC - elapsed)
        _last_dispatch_time = time.monotonic()


async def enrich_with_retry(
    product: ParentProduct,
    sem: asyncio.Semaphore,
    cache_mgr: EnrichmentCacheManager,
    max_retries: int = 6
) -> ParentProduct:
    """Enriches a single product using cache lookup, concurrency semaphore, pacing, and retry logic."""
    cached = cache_mgr.get(product.parent_id)
    if cached and cached.enriched:
        # Preserve local images resolved in this run if any
        if product.local_image_paths:
            cached.local_image_paths = product.local_image_paths
        return cached

    async with sem:
        for attempt in range(1, max_retries + 1):
            try:
                await pace_request()
                enriched = await enrich_single_product_graph(product)
                if enriched and enriched.enriched:
                    cache_mgr.save_product(enriched)
                    return enriched
            except Exception as e:
                err_str = str(e)
                if attempt == max_retries:
                    print(f"\n[!] Failed to enrich {product.parent_id} after {max_retries} attempts: {e}")
                    return product

                # Detect OpenAI 429 TPM Rate Limit and dynamically extract requested sleep time
                wait_sec = 4.0 * (1.5 ** attempt) + random.uniform(0.5, 2.0)
                if "429" in err_str or "rate_limit" in err_str.lower():
                    match = re.search(r"try again in ([\d\.]+)s", err_str)
                    if match:
                        wait_sec = float(match.group(1)) + random.uniform(1.0, 2.5)
                    print(f"\n[!] Rate limit (429) on {product.parent_id}. Backing off for {wait_sec:.1f}s (attempt {attempt}/{max_retries})...")
                else:
                    print(f"\n[!] Error enriching {product.parent_id}: {e}. Retrying in {wait_sec:.1f}s...")

                await asyncio.sleep(wait_sec)

    return product


async def process_batch(
    batch_products: List[ParentProduct],
    batch_num: int,
    start_idx: int,
    end_idx: int,
    sem: asyncio.Semaphore,
    cache_mgr: EnrichmentCacheManager,
    exporter: OpenCartSQLExporter,
    output_dir: Path
) -> List[ParentProduct]:
    """Processes a single batch of products concurrently and exports a batch SQL file."""
    print(f"\n{'='*75}")
    print(f"BATCH #{batch_num:02d}: Processing products {start_idx + 1} to {end_idx} (Total: {len(batch_products)})")
    print(f"{'='*75}")

    # Check cache status before starting
    cached_count = sum(1 for p in batch_products if cache_mgr.get(p.parent_id))
    print(f"[*] Cache status: {cached_count}/{len(batch_products)} already in cache, {len(batch_products) - cached_count} to call LLM.")

    tasks = [
        enrich_with_retry(p, sem, cache_mgr)
        for p in batch_products
    ]

    completed_products = []
    # Execute batch with progress output
    for fut in asyncio.as_completed(tasks):
        res = await fut
        completed_products.append(res)
        name_preview = res.enriched.ua.name if (res.enriched and res.enriched.ua) else res.model_name
        cat_preview = f"Cat: {res.main_category_id}" if res.main_category_id else "Cat: N/A"
        gender_preview = f"Gender: {res.gender}" if res.gender else "Gender: N/A"
        season_preview = f"Season: {res.season}" if res.season else "Season: N/A"
        print(f"  [{len(completed_products):03d}/{len(batch_products):03d}] {res.parent_id} | {cat_preview} | {gender_preview} | {season_preview} | {name_preview[:40]}")

    # Export Batch SQL Migration
    batch_sql_path = output_dir / f"batch_{batch_num:03d}_products_{start_idx + 1}_{end_idx}.sql"
    exporter.generate_sql(completed_products, str(batch_sql_path))
    size_kb = batch_sql_path.stat().st_size / 1024
    print(f"[✓] Batch #{batch_num:02d} SQL exported: {batch_sql_path.name} ({size_kb:.1f} KB)")

    return completed_products


async def main():
    parser = argparse.ArgumentParser(description="Batch AI Enrichment & SQL Migration Pipeline for OpenCart")
    parser.add_argument("--catalog", default="data/huppa.xlsx", help="Path to supplier spreadsheet")
    parser.add_argument("--images-dir", default="opencart_images", help="Directory containing product images")
    parser.add_argument("--cache-file", default="data/enriched_cache.jsonl", help="JSONL cache file path")
    parser.add_argument("--output-dir", default="output", help="Directory to save generated SQL files")
    parser.add_argument("--batch-size", type=int, default=50, help="Number of products per batch chunk (default: 50)")
    parser.add_argument("--offset", type=int, default=0, help="Starting index (0-based)")
    parser.add_argument("--limit", type=int, default=None, help="Max number of products to process (default: all)")
    parser.add_argument("--all", action="store_true", help="Process the entire catalog in batches")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent OpenAI API requests (default: 5, auto-paced)")
    args = parser.parse_args()

    catalog_path = Path(args.catalog)
    if not catalog_path.exists():
        print(f"[!] Catalog file not found: {catalog_path}")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cache_mgr = EnrichmentCacheManager(Path(args.cache_file))

    # Step 1: Load and normalize supplier catalog
    print("=" * 75)
    print("STEP 1: Load and Normalize Supplier Catalog")
    print("=" * 75)
    df = registry.load_and_normalize(str(catalog_path))
    print(f"[+] Loaded {len(df)} rows from {catalog_path}")

    # Step 2: Aggregate into Parent Products
    print("\n" + "=" * 75)
    print("STEP 2: Aggregate Rows into Parent Products (Model + Color cards)")
    print("=" * 75)
    all_products = aggregate_canonical_df(df)
    total_catalog = len(all_products)
    print(f"[+] Total parent products formed: {total_catalog}")

    # Step 3: Resolve Local Images
    print("\n" + "=" * 75)
    print("STEP 3: Resolve Local Product Photos")
    print("=" * 75)
    resolver = OpenCartImageResolver(images_dir=args.images_dir, opencart_prefix="catalog/product/")
    for p in all_products:
        p.local_image_paths = resolver.resolve_for_product(p)
    with_images = sum(1 for p in all_products if p.local_image_paths)
    print(f"[+] Matched local images for {with_images}/{total_catalog} products.")

    # Slice catalog by offset and limit
    start_idx = args.offset
    if args.all or args.limit is None:
        end_idx = total_catalog
    else:
        end_idx = min(start_idx + args.limit, total_catalog)

    selected_slice = all_products[start_idx:end_idx]
    total_to_process = len(selected_slice)

    print("\n" + "=" * 75)
    print(f"PIPELINE RUN CONFIGURATION:")
    print(f"  - Target slice:      Indices {start_idx} to {end_idx - 1} (Total: {total_to_process} products)")
    print(f"  - Batch size:        {args.batch_size} products per batch")
    print(f"  - Concurrency:       {args.concurrency} parallel LLM workers")
    print(f"  - Cache file:        {args.cache_file}")
    print(f"  - Output directory:  {args.output_dir}/")
    print("=" * 75)

    sem = asyncio.Semaphore(args.concurrency)
    exporter = OpenCartSQLExporter(
        table_prefix="oc_",
        lang_ua_id=3,
        lang_ru_id=1,
        size_option_id=11,
        attribute_group_id=7
    )

    all_completed: List[ParentProduct] = []
    batch_num = 1

    # Process in chunks of batch_size
    for i in range(0, total_to_process, args.batch_size):
        chunk = selected_slice[i:i + args.batch_size]
        chunk_start = start_idx + i
        chunk_end = chunk_start + len(chunk)

        completed_chunk = await process_batch(
            batch_products=chunk,
            batch_num=batch_num,
            start_idx=chunk_start,
            end_idx=chunk_end,
            sem=sem,
            cache_mgr=cache_mgr,
            exporter=exporter,
            output_dir=output_dir
        )
        all_completed.extend(completed_chunk)
        batch_num += 1

    # Master cumulative SQL export if more than 1 batch was run
    if len(all_completed) > args.batch_size or args.all:
        master_sql_path = output_dir / "all_enriched_products.sql"
        print(f"\n[+] Generating master cumulative SQL migration: {master_sql_path.name}...")
        exporter.generate_sql(all_completed, str(master_sql_path))
        print(f"[✓] Master SQL written: {master_sql_path} ({master_sql_path.stat().st_size / 1024:.1f} KB)")

    print("\n" + "=" * 75)
    print("ALL BATCHES COMPLETE!")
    print(f"Successfully processed {len(all_completed)} products.")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
