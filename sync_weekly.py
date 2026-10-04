"""
OpenCart Weekly Catalog Synchronization Tool (sync_weekly.py)
=============================================================
Quickly updates prices, promotions, total stock, and size options in OpenCart
using intelligent Change Data Capture (Delta Sync).

Key Features:
1. Compares fresh supplier spreadsheet with data/enriched_cache.jsonl.
2. Identifies ONLY products with actual changes (price, special, total stock, or size stock).
3. Completely SKIPS unchanged products (keeping SQL small and preserving OpenCart date_modified).
4. Generates targeted UPDATEs for changed products, zeroes discontinued items, and exports new models.
5. Updates cache snapshots so next week compares against the new baseline.
"""

import sys
import os
import re
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from adapters.registry import registry
from core.aggregator import aggregate_canonical_df
from core.models import ParentProduct
from core.cache_backup import create_cache_backup


def _escape_sql(val: str) -> str:
    """Escapes string value for safe inclusion in MySQL queries."""
    if val is None:
        return "NULL"
    cleaned = str(val).replace("\\", "\\\\").replace("'", "''")
    return f"'{cleaned}'"


def load_cached_catalog(cache_path: Path) -> Dict[str, ParentProduct]:
    """Loads all known parent products from the persistent JSONL cache."""
    cached: Dict[str, ParentProduct] = {}
    if not cache_path.exists():
        return cached

    with open(cache_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                prod = ParentProduct.model_validate_json(line)
                cached[prod.parent_id] = prod
            except Exception:
                continue
    return cached


def detect_product_changes(fresh: ParentProduct, cached: ParentProduct) -> Tuple[bool, List[str]]:
    """
    Compares fresh product data against the cached baseline snapshot.
    Returns (has_changed, list_of_human_readable_change_descriptions).
    """
    changes: List[str] = []

    # 1. Base price change
    if abs(fresh.base_price - cached.base_price) > 0.01:
        changes.append(f"Ціна: {cached.base_price:.0f} -> {fresh.base_price:.0f} грн")

    # 2. Promotional special price change
    fresh_sp = fresh.special_price if (fresh.special_price and 0 < fresh.special_price < fresh.base_price) else None
    cached_sp = cached.special_price if (cached.special_price and 0 < cached.special_price < cached.base_price) else None

    if fresh_sp != cached_sp:
        if cached_sp is None and fresh_sp is not None:
            changes.append(f"Нова акція: {fresh_sp:.0f} грн")
        elif cached_sp is not None and fresh_sp is None:
            changes.append(f"Акцію знято (була {cached_sp:.0f} грн)")
        elif fresh_sp and cached_sp and abs(fresh_sp - cached_sp) > 0.01:
            changes.append(f"Акція змінена: {cached_sp:.0f} -> {fresh_sp:.0f} грн")

    # 3. Total stock change
    if fresh.total_stock != cached.total_stock:
        if cached.total_stock > 0 and fresh.total_stock <= 0:
            changes.append(f"Залишок: {cached.total_stock} -> 0 (Закінчився)")
        elif cached.total_stock <= 0 and fresh.total_stock > 0:
            changes.append(f"Залишок: 0 -> {fresh.total_stock} (З'явився)")
        else:
            changes.append(f"Залишок: {cached.total_stock} -> {fresh.total_stock}")

    # 4. Individual size variant stock changes
    fresh_sizes = {v.size.strip(): max(0, v.stock) for v in fresh.size_variants}
    cached_sizes = {v.size.strip(): max(0, v.stock) for v in cached.size_variants}

    all_sizes = set(fresh_sizes.keys()).union(set(cached_sizes.keys()))
    size_diffs = []
    for s in sorted(all_sizes):
        f_qty = fresh_sizes.get(s, 0)
        c_qty = cached_sizes.get(s, 0)
        if f_qty != c_qty:
            size_diffs.append(f"{s} ({c_qty} -> {f_qty})")

    if size_diffs:
        summary_sizes = ", ".join(size_diffs[:3])
        if len(size_diffs) > 3:
            summary_sizes += f" + ще {len(size_diffs) - 3}"
        changes.append(f"Розміри: {summary_sizes}")

    has_changed = len(changes) > 0
    return (has_changed, changes)


def update_cache_snapshots(cache_path: Path, updated_products: List[ParentProduct]):
    """
    Updates dynamic values (prices, stock, sizes) in data/enriched_cache.jsonl
    while preserving static AI content (descriptions, meta tags, attributes).
    Automatically saves a timestamped snapshot backup before modifying the cache.
    """
    if not cache_path.exists() or not updated_products:
        return

    # Automatically snapshot cache before updating (keeps 10 newest backups)
    try:
        create_cache_backup(cache_path, max_backups=10, tag="weekly_sync")
    except Exception as e:
        print(f"[!] Warning: Failed to create cache backup: {e}")

    updated_dict = {p.parent_id: p for p in updated_products}
    new_lines = []

    with open(cache_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                prod = ParentProduct.model_validate_json(line)
                if prod.parent_id in updated_dict:
                    fresh = updated_dict[prod.parent_id]
                    prod.base_price = fresh.base_price
                    prod.special_price = fresh.special_price
                    prod.total_stock = fresh.total_stock
                    prod.size_variants = fresh.size_variants
                    prod.raw_specs = fresh.raw_specs
                new_lines.append(prod.model_dump_json())
            except Exception:
                new_lines.append(line)

    with open(cache_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")


def generate_weekly_sync_sql(
    changed_products: List[Tuple[ParentProduct, List[str]]],
    discontinued_models: List[str],
    output_sql_path: Path,
    table_prefix: str = "oc_",
    size_option_id: int = 11
) -> int:
    """
    Generates a targeted, ultra-lightweight SQL migration containing UPDATEs
    ONLY for products that actually changed.
    """
    lines: List[str] = [
        "-- ======================================================================",
        "-- OpenCart Weekly Delta Synchronization Migration",
        f"-- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"-- Actual Products with Changes: {len(changed_products)}",
        f"-- Products Discontinued (Zeroed): {len(discontinued_models)}",
        "-- ======================================================================",
        "SET NAMES utf8mb4;",
        "SET FOREIGN_KEY_CHECKS = 0;",
        "START TRANSACTION;",
        "",
        "-- Dynamic OpenCart System Identifiers",
        f"SET @default_customer_group_id = (SELECT `customer_group_id` FROM `{table_prefix}customer_group` ORDER BY `sort_order` ASC, `customer_group_id` ASC LIMIT 1);",
        "SET @default_customer_group_id = IFNULL(@default_customer_group_id, 1);",
        "",
        f"SET @stock_out_of_stock_id = (SELECT `stock_status_id` FROM `{table_prefix}stock_status` WHERE LOWER(`name`) LIKE '%нет в налич%' OR LOWER(`name`) LIKE '%немає%' OR LOWER(`name`) LIKE '%відсутн%' OR LOWER(`name`) LIKE '%out of stock%' LIMIT 1);",
        "SET @stock_out_of_stock_id = IFNULL(@stock_out_of_stock_id, 5);",
        "",
        f"SET @stock_in_stock_id = (SELECT `stock_status_id` FROM `{table_prefix}stock_status` WHERE (LOWER(`name`) LIKE '%в налич%' OR LOWER(`name`) LIKE '%наявн%' OR LOWER(`name`) LIKE '%in stock%') AND LOWER(`name`) NOT LIKE '%нет%' AND LOWER(`name`) NOT LIKE '%немає%' LIMIT 1);",
        "SET @stock_in_stock_id = IFNULL(@stock_in_stock_id, 7);",
        ""
    ]

    for p, change_list in changed_products:
        product_code = f"{p.model_code}-{p.color_code}"
        code_esc = _escape_sql(product_code)
        parent_id_esc = _escape_sql(p.parent_id)
        total_qty = max(0, p.total_stock)
        change_desc = "; ".join(change_list)

        lines.append(f"-- ----------------------------------------------------")
        lines.append(f"-- Product: {p.brand} {p.model_name} ({product_code}) | Зміни: {change_desc}")
        lines.append(f"-- ----------------------------------------------------")
        lines.append(f"""SET @current_product_id = (
    SELECT `product_id` FROM `{table_prefix}product` 
    WHERE `model` = {code_esc} 
       OR `sku` = {code_esc}
       OR `sku` = {parent_id_esc}
    LIMIT 1
);

-- 1. Оновлення ціни, загального залишку та статусу наявності
UPDATE `{table_prefix}product` SET
    `price` = {p.base_price},
    `quantity` = {total_qty},
    `stock_status_id` = IF({total_qty} > 0, @stock_in_stock_id, @stock_out_of_stock_id),
    `date_modified` = NOW()
WHERE `product_id` = @current_product_id;
""")

        # 2. Promotional price update (oc_product_special)
        lines.append(f"DELETE FROM `{table_prefix}product_special` WHERE `product_id` = @current_product_id;")
        if p.special_price is not None and 0 < p.special_price < p.base_price:
            lines.append(f"""INSERT INTO `{table_prefix}product_special` (
    `product_id`, `customer_group_id`, `priority`, `price`, `date_start`, `date_end`
)
SELECT @current_product_id, @default_customer_group_id, 1, {p.special_price}, '0000-00-00', '0000-00-00'
WHERE @current_product_id IS NOT NULL;""")

        # 3. Updating stock levels for specific sizes (oc_product_option_value)
        if p.size_variants:
            lines.append(f"-- Оновлення залишків за розмірами для опції ID {size_option_id}")
            for var in p.size_variants:
                size_esc = _escape_sql(var.size.strip())
                var_qty = max(0, var.stock)
                lines.append(f"""UPDATE `{table_prefix}product_option_value` pov
INNER JOIN `{table_prefix}option_value_description` ovd ON pov.`option_value_id` = ovd.`option_value_id`
SET pov.`quantity` = {var_qty}
WHERE pov.`product_id` = @current_product_id
  AND pov.`option_id` = {size_option_id}
  AND ovd.`name` = {size_esc};""")

        lines.append("")

    # 4. Resetting stock levels to zero for items that have been removed from the price list
    if discontinued_models:
        lines.append("-- ======================================================================")
        lines.append(f"-- Товари, що зникли з прайсу постачальника ({len(discontinued_models)} шт.)")
        lines.append("-- Переведення в залишок 0 та статус 'Немає в наявності' (SEO збережено)")
        lines.append("-- ======================================================================")
        chunk_size = 100
        for i in range(0, len(discontinued_models), chunk_size):
            chunk = discontinued_models[i:i + chunk_size]
            models_list = ", ".join(_escape_sql(m) for m in chunk)
            lines.append(f"""UPDATE `{table_prefix}product` SET
    `quantity` = 0,
    `stock_status_id` = @stock_out_of_stock_id,
    `date_modified` = NOW()
WHERE `model` IN ({models_list});""")
        lines.append("")

    lines.append("COMMIT;")
    lines.append("SET FOREIGN_KEY_CHECKS = 1;")
    lines.append("-- Finished weekly delta sync migration")

    output_sql_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_sql_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return output_sql_path.stat().st_size


async def enrich_new_products_cli(
    new_products: List[ParentProduct],
    cache_path: Path,
    images_dir: Path,
    concurrency: int = 5
) -> List[ParentProduct]:
    """
    Enriches detected new products using the paced AI graph (OpenAI gpt-4o-mini).
    Automatically saves enriched products to the JSONL cache and resolves local images.
    """
    from core.image_resolver import OpenCartImageResolver
    from run_batch_pipeline import enrich_with_retry, EnrichmentCacheManager
    from tqdm.asyncio import tqdm

    cache_mgr = EnrichmentCacheManager(cache_path)
    resolver = OpenCartImageResolver(images_dir=str(images_dir), opencart_prefix="catalog/product/")
    for p in new_products:
        p.local_image_paths = resolver.resolve_for_product(p)

    sem = asyncio.Semaphore(concurrency)
    tasks = [enrich_with_retry(p, sem, cache_mgr) for p in new_products]
    enriched_results = await tqdm.gather(*tasks, desc="AI Enrichment for New Products")
    return [p for p in enriched_results if p.enriched is not None]


def main():
    parser = argparse.ArgumentParser(description="OpenCart Weekly Delta Sync Tool (Only Real Changes)")
    parser.add_argument("--catalog", default="data/huppa.xlsx", help="Path to supplier spreadsheet")
    parser.add_argument("--cache-file", default="data/enriched_cache.jsonl", help="Path to enriched products cache")
    parser.add_argument("--output-dir", default="output", help="Directory to save sync SQL files")
    parser.add_argument("--table-prefix", default="oc_", help="OpenCart database table prefix (default: oc_)")
    parser.add_argument("--size-option-id", type=int, default=11, help="OpenCart Option ID for Size (default: 11)")
    parser.add_argument("--auto-enrich", action="store_true", help="Automatically call OpenAI LLM to enrich detected new products and append INSERT statements to SQL")
    parser.add_argument("--images-dir", default="opencart_images", help="Path to images directory for OpenCart (default: opencart_images)")
    parser.add_argument("--dry-run", action="store_true", help="Perform comparison and report without writing SQL")
    args = parser.parse_args()

    start_time = datetime.now()
    catalog_path = Path(args.catalog)
    cache_path = Path(args.cache_file)
    output_dir = Path(args.output_dir)

    print("=" * 75)
    print("HUPPA OPENCART DELTA SYNCHRONIZER (ONLY REAL CHANGES)")
    print(f"Date: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 75)

    if not catalog_path.exists():
        print(f"[!] Supplier spreadsheet not found at: {catalog_path}")
        sys.exit(1)

    # 1. Loading a known catalogue from the cache
    print(f"\n[1/4] Loading existing catalog from cache ({cache_path.name})...")
    cached_catalog = load_cached_catalog(cache_path)
    print(f"      Loaded {len(cached_catalog)} known baseline products.")

    # 2. Uploading and standardising the new price list
    print(f"\n[2/4] Parsing and normalizing fresh spreadsheet: {catalog_path.name}...")
    df = registry.load_and_normalize(str(catalog_path))
    print(f"      Loaded {len(df)} supplier rows.")

    print(f"      Aggregating into parent products (model + color)...")
    fresh_products = aggregate_canonical_df(df)
    print(f"      Formed {len(fresh_products)} unique parent product cards.")

    # 3. Delta Detection: pinpoint detection of actual changes
    print(f"\n[3/4] Running Delta Change Detection...")
    fresh_dict = {p.parent_id: p for p in fresh_products}

    changed_products: List[Tuple[ParentProduct, List[str]]] = []
    unchanged_products: List[ParentProduct] = []
    new_products: List[ParentProduct] = []

    for p in fresh_products:
        if p.parent_id in cached_catalog:
            cached_p = cached_catalog[p.parent_id]
            has_changed, change_list = detect_product_changes(fresh=p, cached=cached_p)
            if has_changed:
                changed_products.append((p, change_list))
            else:
                unchanged_products.append(p)
        else:
            new_products.append(p)

    # Items that were in the cache with a stock level > 0 but have disappeared from the latest price list
    discontinued_models = [
        f"{cached_prod.model_code}-{cached_prod.color_code}"
        for parent_id, cached_prod in cached_catalog.items()
        if parent_id not in fresh_dict and cached_prod.total_stock > 0
    ]

    # 4. Generating results
    today_str = datetime.now().strftime("%Y_%m_%d")
    output_sql_path = output_dir / f"weekly_sync_{today_str}.sql"
    new_products_path = output_dir / "new_products_pending.json"

    file_size_kb = 0.0
    enriched_new_count = 0

    if not args.dry_run:
        print(f"\n[4/4] Generating Delta SQL migration: {output_sql_path.name}...")
        bytes_written = generate_weekly_sync_sql(
            changed_products=changed_products,
            discontinued_models=discontinued_models,
            output_sql_path=output_sql_path,
            table_prefix=args.table_prefix,
            size_option_id=args.size_option_id
        )
        file_size_kb = bytes_written / 1024

        # Updating the cache with the changed values
        if changed_products:
            update_cache_snapshots(cache_path, [p for p, _ in changed_products])

        if new_products:
            if args.auto_enrich:
                print(f"\n[✨] Auto-enriching {len(new_products)} new products via OpenAI LLM...")
                enriched_new = asyncio.run(
                    enrich_new_products_cli(
                        new_products=new_products,
                        cache_path=cache_path,
                        images_dir=Path(args.images_dir),
                        concurrency=5
                    )
                )
                enriched_new_count = len(enriched_new)
                if enriched_new:
                    from core.sql_exporter import OpenCartSQLExporter
                    temp_new_sql = output_dir / "temp_new_cli.sql"
                    exporter = OpenCartSQLExporter(table_prefix=args.table_prefix, lang_ua_id=3, lang_ru_id=1)
                    exporter.generate_sql(enriched_new, str(temp_new_sql))
                    if temp_new_sql.exists():
                        with open(temp_new_sql, "r", encoding="utf-8") as f_in:
                            new_sql_text = f_in.read()
                        with open(output_sql_path, "a", encoding="utf-8") as f_out:
                            f_out.write("\n\n-- ======================================================\n")
                            f_out.write("-- ПОВНЕ ДОДАВАННЯ НОВИХ ТОВАРІВ (INSERT)\n")
                            f_out.write("-- ======================================================\n")
                            f_out.write(new_sql_text)
                        temp_new_sql.unlink(missing_ok=True)
                    file_size_kb = output_sql_path.stat().st_size / 1024
                    print(f"      [✓] Successfully enriched & appended {enriched_new_count} new products (INSERT) to {output_sql_path.name}")
            else:
                new_summary = [
                    {
                        "parent_id": np.parent_id,
                        "model_code": np.model_code,
                        "color_code": np.color_code,
                        "model_name": np.model_name,
                        "color_name": np.color_name,
                        "product_type": np.product_type,
                        "base_price": np.base_price,
                        "total_stock": np.total_stock
                    }
                    for np in new_products
                ]
                with open(new_products_path, "w", encoding="utf-8") as f:
                    json.dump(new_summary, f, ensure_ascii=False, indent=2)
                print(f"      [i] Новинки ({len(new_products)}) збережено у {new_products_path.name}. Додайте --auto-enrich для автоматичного виклику LLM.")

    elapsed_sec = (datetime.now() - start_time).total_seconds()

    # Final Report
    print("\n" + "=" * 75)
    print("WEEKLY DELTA SYNCHRONIZATION REPORT")
    print("=" * 75)
    print(f"  • Вхідний прайс:               {catalog_path} ({len(df):,} рядків)")
    print(f"  • Всього карток у прайсі:      {len(fresh_products)}")
    print("---------------------------------------------------------------------------")
    print(f"  [⚡] РЕАЛЬНО ЗМІНИЛОСЯ (в SQL):  {len(changed_products)} товарів")
    print(f"  [⏸️] БЕЗ ЗМІН (пропущено):       {len(unchanged_products)} товарів")
    print(f"  [!] Зникли з прайсу (в stock 0): {len(discontinued_models)} товарів")
    print(f"  [✨] Нових моделей (новинки):    {len(new_products)} товарів")
    print("---------------------------------------------------------------------------")
    if changed_products:
        print("Приклади виявлених змін:")
        for p, chg in changed_products[:5]:
            print(f"  * {p.model_code}-{p.color_code} ({p.model_name}): {'; '.join(chg)}")
        if len(changed_products) > 5:
            print(f"  ... та ще {len(changed_products) - 5} товарів.")
        print("---------------------------------------------------------------------------")

    if not args.dry_run:
        print(f"  [✓] Згенеровано SQL-файл:       {output_sql_path} ({file_size_kb:.1f} KB)")
        if new_products:
            if args.auto_enrich:
                print(f"  [✨] AI-збагачення новинок:     Успішно додано {enriched_new_count} карток (INSERT)")
            else:
                print(f"  [!] Новинки збережено в:        {new_products_path} (додайте --auto-enrich для запуску AI)")
    else:
        print("  [*] Режим DRY-RUN: SQL-файл не записувався.")

    if args.auto_enrich and enriched_new_count > 0:
        print(f"  [✓] Загальний час виконання:    {elapsed_sec:.2f} сек. (з урахуванням AI-збагачення)")
    else:
        print(f"  [✓] Загальний час виконання:    {elapsed_sec:.2f} сек. (нуль витрат токенів AI)")
    print("=" * 75)


if __name__ == "__main__":
    main()
