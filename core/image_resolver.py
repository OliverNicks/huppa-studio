from pathlib import Path
from typing import List, Set, Optional, Dict
from core.models import ParentProduct


class OpenCartImageResolver:
    """
    Scans the local opencart_images directory and attaches the corresponding
    OpenCart server paths ('catalog/product/...') to each ParentProduct.
    """

    def __init__(
        self,
        images_dir: str = "opencart_images",
        opencart_prefix: str = "catalog/product/"
    ):
        self.images_dir = Path(images_dir)
        self.prefix = opencart_prefix
        self.indexed_files: Set[str] = set()

        if self.images_dir.exists():
            self.indexed_files = {
                f.name for f in self.images_dir.iterdir()
                if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
            }

    def _get_candidate_prefixes(self, product: ParentProduct) -> List[str]:
        """
        Generates candidate file prefixes:
        1. From variant SKUs (e.g., '21700010-00009-00L' -> '21700010-00009')
        2. From model and zero-padded color (e.g., '21700010-00009')
        3. From model and raw color (e.g., '21700010-9')
        4. From parent_id with hyphen (e.g., '21700010-9' or '21700010-00009')
        """
        candidates: List[str] = []

        # 1. From variant SKUs (most precise representation from sheet)
        for v in product.size_variants:
            if v.sku and "-" in v.sku:
                parts = v.sku.strip().split("-")
                if len(parts) >= 2:
                    sku_prefix = f"{parts[0]}-{parts[1]}"
                    if sku_prefix not in candidates:
                        candidates.append(sku_prefix)

        # 2. Zero-padded 5-digit color code (Huppa catalog standard)
        clean_model = product.model_code.strip() if product.model_code else ""
        clean_color = product.color_code.strip() if product.color_code else ""

        if clean_model and clean_color:
            padded_color = clean_color.zfill(5)
            c_padded = f"{clean_model}-{padded_color}"
            if c_padded not in candidates:
                candidates.append(c_padded)

            c_raw = f"{clean_model}-{clean_color}"
            if c_raw not in candidates:
                candidates.append(c_raw)

            # Check underscore variants
            c_under = f"{clean_model}_{clean_color}"
            if c_under not in candidates:
                candidates.append(c_under)

        # 3. Direct parent_id replacement
        if product.parent_id:
            pid_hyphen = product.parent_id.replace("_", "-")
            if pid_hyphen not in candidates:
                candidates.append(pid_hyphen)

        return candidates

    def resolve_for_product(self, product: ParentProduct) -> List[str]:
        """
        Finds the main cover photo (_0.jpg) and all subsequent gallery angles (_1.jpg, _2.jpg...).
        Returns a list of server-relative OpenCart image paths.
        """
        for prefix in self._get_candidate_prefixes(product):
            main_file = f"{prefix}_0.jpg"
            # Fallback if no angle suffix exists
            alt_main = f"{prefix}.jpg"

            resolved: List[str] = []

            if main_file in self.indexed_files:
                resolved.append(f"{self.prefix}{main_file}")
                # Harvest all consecutive gallery photos (_1.jpg, _2.jpg, ...)
                angle_idx = 1
                while f"{prefix}_{angle_idx}.jpg" in self.indexed_files:
                    resolved.append(f"{self.prefix}{prefix}_{angle_idx}.jpg")
                    angle_idx += 1
                return resolved

            elif alt_main in self.indexed_files:
                resolved.append(f"{self.prefix}{alt_main}")
                return resolved

        return []

    def attach_images_to_catalog(self, products: List[ParentProduct]) -> int:
        """
        Attaches resolved OpenCart image paths to all products in place.
        Returns the number of products that successfully matched at least one image.
        """
        matched = 0
        for p in products:
            paths = self.resolve_for_product(p)
            if paths:
                p.local_image_paths = paths
                matched += 1
        return matched
