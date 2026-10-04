import re
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np

from core.models import ParentProduct, SizeVariant


def _clean_scalar(val: Any) -> Any:
    """Convert numpy/pandas types to native Python primitives safely for JSON serialization."""
    if isinstance(val, pd.Series):
        val = val.dropna().iloc[0] if not val.dropna().empty else None

    if val is None or pd.isna(val):
        return None
    if isinstance(val, (np.integer, np.int64, np.int32)):
        return int(val)
    if isinstance(val, (np.floating, np.float64, np.float32)):
        return float(val)
    if isinstance(val, str):
        cleaned = val.strip()
        # Clean trailing .0 from stringified integers (e.g., '21700010.0' -> '21700010')
        return re.sub(r"\.0$", "", cleaned)
    return val


def _safe_float(val: Any, default: Optional[float] = 0.0) -> Optional[float]:
    """Safely cast values to float, handling strings with currency symbols and NaNs."""
    if val is None or pd.isna(val):
        return default
    try:
        if isinstance(val, str):
            val = re.sub(r"[^\d.]", "", val.replace(",", "."))
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    """Safely cast values to int, avoiding 'cannot convert float NaN to integer'."""
    f = _safe_float(val, float(default))
    return int(round(f)) if f is not None else default


def _get_first_valid(group: pd.DataFrame, col: str, default: Any = None) -> Any:
    """Extract the first non-null, non-empty value across all rows in a group."""
    if col in group.columns:
        valid_series = group[col].dropna()
        for val in valid_series:
            cleaned = _clean_scalar(val)
            if cleaned not in (None, "", "nan", "None"):
                return cleaned
    return default


def _natural_size_key(size_str: str):
    """
    Sort key for natural sorting: handles sizes like 86, 92, 98, 104, 
    or S, M, L, or composite sizes like 48/50.
    """
    num_match = re.search(r"\d+", size_str)
    num_part = int(num_match.group()) if num_match else 9999
    return (num_part, size_str)


def aggregate_canonical_df(df: pd.DataFrame) -> List[ParentProduct]:
    """
    Groups flat canonical DataFrame into hierarchical ParentProduct entities
    with nested SizeVariant children, ensuring:
    - Base price defaults to minimum positive catalog price (standard OpenCart UX)
    - Deduplication of identical size options (summing stock)
    - Natural chronological sorting of sizes
    - Robust non-null attribute harvesting across all rows in a group
    """
    products: List[ParentProduct] = []

    # 1. Clean grouping identifiers
    df = df.copy()
    model_code_col = df.get("canonical_model_code", pd.Series(["UNKNOWN"] * len(df)))
    color_code_col = df.get("canonical_color_code", pd.Series(["DEFAULT"] * len(df)))

    clean_model = model_code_col.fillna("UNKNOWN").astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    clean_color = color_code_col.fillna("DEFAULT").astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    clean_color = clean_color.apply(lambda x: x.zfill(5) if x.isdigit() and len(x) < 5 else x)

    df["_group_id"] = clean_model + "_" + clean_color

    reserved_cols = {
        col for col in df.columns if col.startswith("canonical_")
    } | {"_group_id"}

    # 2. Group by product card (Model + Color)
    for group_id, group in df.groupby("_group_id", sort=False):
        # Determine Base Price: prefer minimum positive price for OpenCart '+' prefix UX
        valid_prices = [
            p for p in group["canonical_price"].apply(_safe_float)
            if p is not None and p > 0
        ]
        base_price = float(min(valid_prices)) if valid_prices else 0.0

        valid_specials = [
            p for p in group["canonical_special_price"].apply(_safe_float)
            if p is not None and p > 0
        ] if "canonical_special_price" in group.columns else []
        special_price = float(min(valid_specials)) if valid_specials else _safe_float(_get_first_valid(group, "canonical_special_price"), None)

        # 3. Harvest & Deduplicate Size Variants
        raw_variants: Dict[str, SizeVariant] = {}

        for _, row in group.iterrows():
            raw_size = str(_clean_scalar(row.get("canonical_size")) or "ONE_SIZE").strip()
            raw_sku = _clean_scalar(row.get("canonical_sku"))
            raw_barcode = _clean_scalar(row.get("canonical_barcode"))

            var_stock = _safe_int(row.get("canonical_stock"), default=0)
            var_price = _safe_float(row.get("canonical_price"), default=base_price) or base_price

            var_special_raw = row.get("canonical_special_price")
            var_special = _safe_float(var_special_raw, None)

            diff = round(var_price - base_price, 2)
            prefix = "+" if diff >= 0 else "-"

            if raw_size in raw_variants:
                # Merge stock and update missing SKU/barcode
                existing = raw_variants[raw_size]
                existing.stock += var_stock
                if not existing.barcode and raw_barcode:
                    existing.barcode = str(raw_barcode)
                if not existing.sku and raw_sku:
                    existing.sku = str(raw_sku)
            else:
                raw_variants[raw_size] = SizeVariant(
                    size=raw_size,
                    sku=str(raw_sku) if raw_sku is not None else None,
                    barcode=str(raw_barcode) if raw_barcode is not None else None,
                    stock=var_stock,
                    price=var_price,
                    special_price=var_special,
                    price_prefix=prefix,
                    price_diff=abs(diff),
                )

        # Natural sort size variants (86 -> 92 -> 98 -> 104)
        variants = sorted(raw_variants.values(), key=lambda v: _natural_size_key(v.size))

        # 4. Collect Image URLs safely (handles both lists and comma-separated strings)
        all_images: List[str] = []
        if "canonical_images" in group.columns:
            for item in group["canonical_images"].dropna():
                if isinstance(item, list):
                    for url in item:
                        u = str(url).strip()
                        if u and u not in all_images:
                            all_images.append(u)
                elif isinstance(item, str):
                    for part in item.split(","):
                        u = part.strip()
                        if u.startswith("http") and u not in all_images:
                            all_images.append(u)

        # 5. Extract unmapped raw specifications across the group
        raw_specs: Dict[str, Any] = {}
        for col in group.columns:
            if col not in reserved_cols:
                first_val = _get_first_valid(group, col)
                if first_val is not None:
                    raw_specs[col] = first_val

        # Total stock
        total_stock = sum(v.stock for v in variants)

        # 6. Construct ParentProduct using first non-null values across group
        parent = ParentProduct(
            parent_id=group_id,
            model_code=str(_get_first_valid(group, "canonical_model_code", "")),
            color_code=str(_get_first_valid(group, "canonical_color_code", "")),
            model_name=str(_get_first_valid(group, "canonical_model", "Без назви")),
            color_name=str(_get_first_valid(group, "canonical_color", "")),
            product_type=str(_get_first_valid(group, "canonical_product_type", "")),
            gender=str(_get_first_valid(group, "canonical_gender", "") or ""),
            season=str(_get_first_valid(group, "canonical_season", "") or ""),
            brand=str(_get_first_valid(group, "canonical_brand", "")),
            base_price=base_price,
            special_price=special_price,
            total_stock=total_stock,
            image_urls=all_images,
            raw_description=str(_get_first_valid(group, "canonical_description", "")),
            raw_specs=raw_specs,
            size_variants=variants,
        )

        products.append(parent)

    return products