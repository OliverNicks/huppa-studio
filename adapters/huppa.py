"""
Huppa Supplier Catalog Adapter (adapters/huppa.py)
==================================================
Deterministic, high-performance normalization for Huppa spreadsheets:
- Pre-adapter Contract Validation & Sanity Checks
- Zero fuzzy iterations over column names (strict declarative mapping)
- Fully vectorized regex extraction of Model, Color, and Size from factory SKU
- Intelligent protection against supplier typos (e.g. size pasted into color column)
- Safe zero-padding for numeric codes while preserving alphanumeric codes (e.g. O20, P18)
"""

import re
from pathlib import Path
from typing import List, Optional
import pandas as pd
import numpy as np

from adapters.base import BaseSupplierAdapter


class HuppaAdapter(BaseSupplierAdapter):
    """Adapter for normalizing supplier spreadsheets from Huppa."""

    def can_handle(self, df: pd.DataFrame, filename: str) -> bool:
        """Check if filename contains 'huppa' or if distinct Huppa markers exist."""
        if "huppa" in Path(filename).stem.lower():
            return True

        cleaned_headers = {re.sub(r"\s+", " ", str(col)).strip().lower() for col in df.columns}
        return {"номер коляру", "назва моделі"}.issubset(cleaned_headers)

    def _clean_headers(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalizes all whitespace inside and around column names."""
        df = df.copy()
        df.columns = [re.sub(r"\s+", " ", str(col)).strip() for col in df.columns]
        return df

    def _validate_contract(self, df: pd.DataFrame, filename: str = ""):
        """
        Enforces structural integrity before normalization:
        - Ensures spreadsheet contains rows
        - Verifies presence of primary SKU column ('Артикул') or fallback ('Артикул.1')
        - Verifies presence of critical commercial and taxonomy columns
        """
        if len(df) == 0:
            raise ValueError(f"Huppa spreadsheet '{filename}' is empty (0 rows).")

        has_sku = "Артикул" in df.columns or "Артикул.1" in df.columns
        if not has_sku:
            raise ValueError(
                f"Huppa contract validation failed for '{filename}': "
                "missing mandatory SKU column ('Артикул')."
            )

        mandatory_columns = ["Ціна роздрібна", "розмір", "назва моделі"]
        missing = [col for col in mandatory_columns if col not in df.columns]
        if missing:
            raise ValueError(
                f"Huppa contract validation failed for '{filename}': "
                f"missing mandatory columns: {missing}"
            )

    @staticmethod
    def _coalesce(df: pd.DataFrame, candidates: List[str], default: str = "") -> pd.Series:
        """Picks the first existing column from candidates, filling remaining nulls in priority order."""
        res = None
        for col in candidates:
            if col in df.columns:
                series = df[col]
                res = series.copy() if res is None else res.fillna(series)
        if res is None:
            return pd.Series(default, index=df.index)
        return res.fillna(default)

    def normalize(self, df: pd.DataFrame, filename: str = "") -> pd.DataFrame:
        """
        Normalizes raw Huppa data into canonical columns using 100% vectorized operations.
        """
        # 1. Clean headers and validate structure
        df = self._clean_headers(df)
        self._validate_contract(df, filename)

        # 2. Resolve primary SKU ('Артикул' column is primary, 'Артикул.1' is optional fallback)
        canonical_sku = self._coalesce(df, ["Артикул", "Артикул.1"]).astype(str).str.strip()

        # Filter out empty/banner rows where SKU is blank
        valid_sku_mask = canonical_sku.notna() & (canonical_sku != "") & (canonical_sku != "nan")
        df = df[valid_sku_mask].copy()
        canonical_sku = canonical_sku[valid_sku_mask]

        # 3. Vectorized SKU decomposition: e.g. '18130000-00118-080'
        sku_parts = canonical_sku.str.extract(
            r"^(?P<sku_model>[A-Za-z0-9]+)[-_](?P<sku_color>[A-Za-z0-9]+)[-_](?P<sku_size>.+)$"
        )

        # 4. Vectorized Combined Model-Color column decomposition: e.g. '18130000-00118'
        mc_series = self._coalesce(df, ["модель-колір", "модель плюс колір", "модель - колір"]).astype(str).str.strip()
        mc_parts = mc_series.str.extract(r"^(?P<mc_model>[A-Za-z0-9]+)[-_](?P<mc_color>[A-Za-z0-9]+)$")

        # 5. Separate columns extraction (with typo guards)
        sep_model = self._coalesce(df, ["модель"]).astype(str).str.replace(".0", "", regex=False).str.strip()
        sep_color = self._coalesce(df, ["номер коляру", "номер кольору", "номер цвета"]).astype(str).str.replace(".0", "", regex=False).str.strip()
        sep_size = self._coalesce(df, ["розмір"]).astype(str).str.replace(".0", "", regex=False).str.strip()

        # Sanity Guard: If supplier accidentally placed the size into the color column (e.g. JACKIE), ignore it
        sep_color = sep_color.where((sep_color != sep_size) & (sep_color.str.lower() != "nan"), np.nan)

        # 6. Resolve Model Code with strict priority
        canonical_model_code = (
            mc_parts["mc_model"]
            .fillna(sku_parts["sku_model"])
            .fillna(sep_model)
            .fillna("UNKNOWN")
            .astype(str).str.replace(".0", "", regex=False).str.strip()
        )

        # 7. Resolve Color Code with strict priority
        canonical_color_code = (
            mc_parts["mc_color"]
            .fillna(sku_parts["sku_color"])
            .fillna(sep_color)
            .fillna("DEFAULT")
            .astype(str).str.replace(".0", "", regex=False).str.strip()
        )

        # Safe color zero-padding: ONLY pad purely numeric codes (e.g. '9' -> '00009')
        # Preserve alphanumeric codes like 'O20', 'P18', 'Q47'
        canonical_color_code = canonical_color_code.apply(
            lambda c: str(c).zfill(5) if str(c).isdigit() and len(str(c)) < 5 else str(c)
        )

        # 8. Assign Canonical Identity & Categorization Columns
        df["canonical_sku"] = canonical_sku
        df["canonical_model_code"] = canonical_model_code
        df["canonical_color_code"] = canonical_color_code
        df["canonical_model"] = self._coalesce(df, ["назва моделі"]).astype(str).str.strip()
        df["canonical_color"] = self._coalesce(df, ["КОЛІР", "цвет"]).astype(str).str.strip()
        df["canonical_size"] = self._coalesce(df, ["розмір"]).astype(str).str.replace(".0", "", regex=False).str.strip()
        df["canonical_brand"] = "HUPPA"
        df["canonical_product_type"] = self._coalesce(df, ["ТИП ТОВАРУ", "тип товара", "Розділ каталогу"]).astype(str).str.strip()
        df["canonical_gender"] = self._coalesce(df, ["СТАТЬ ДЛЯ", "ПОЛ ДЛЯ"]).astype(str).str.strip()
        df["canonical_season"] = self._coalesce(df, ["СЕЗОН", "Сезон"]).astype(str).str.strip()

        # 9. Assign Commercial & Inventory Columns
        df["canonical_price"] = pd.to_numeric(
            self._coalesce(df, ["Ціна роздрібна"]).astype(str).str.replace(r"[^\d.]", "", regex=True),
            errors="coerce"
        ).fillna(0.0)

        raw_special = pd.to_numeric(
            self._coalesce(df, ["Акційна ціна, грн."]).astype(str).str.replace(r"[^\d.]", "", regex=True),
            errors="coerce"
        )
        df["canonical_special_price"] = raw_special.where(raw_special > 0, None)

        df["canonical_stock"] = pd.to_numeric(
            self._coalesce(df, ["Кількість продукції на складі"]).astype(str).str.replace(r"[^\d.]", "", regex=True),
            errors="coerce"
        ).fillna(0).astype(int)

        raw_barcode = self._coalesce(df, ["штрихкод"]).astype(str).str.replace(".0", "", regex=False).str.strip()
        df["canonical_barcode"] = raw_barcode.replace({"nan": None, "": None, "None": None})

        # 10. Assign Specs & Content Columns
        df["canonical_description"] = self._coalesce(df, ["ОПИС", "описание"]).astype(str).str.strip()
        df["canonical_composition"] = self._coalesce(
            df,
            ["СКЛАД: Матеріал верх/підкладка/утеплювач", "СОСТАВ: Материал верх/подкладка/утеплитель"]
        ).astype(str).str.strip()
        df["canonical_temp_range"] = self._coalesce(df, ["температурний режим"]).astype(str).str.strip()
        df["canonical_care"] = self._coalesce(df, ["ДОГЛЯД", "Уход"]).astype(str).str.strip()
        df["canonical_age_group"] = self._coalesce(df, ["ВІК", "вік (возраст)"]).astype(str).str.strip()
        df["canonical_measurements"] = self._coalesce(df, ["ЗАМІРИ", "Замеры"]).astype(str).str.strip()

        # 11. Extract Media Assets (Main URL first, then gallery photos in order)
        img_candidates = [
            "URL", "Foto 1", "Foto 2", "Foto 3", "Foto 4", "Foto 5", "Foto 6", "Foto 7", "Foto 8",
            "фото 1", "фото 2", "фото 3", "фото 4", "фото 5", "фото 6"
        ]
        active_img_cols = [c for c in img_candidates if c in df.columns]

        def extract_images(row):
            urls = []
            for col in active_img_cols:
                val = row[col]
                if pd.notna(val):
                    val_str = str(val).strip()
                    if (val_str.startswith("http://") or val_str.startswith("https://")) and val_str not in urls:
                        urls.append(val_str)
            return urls

        df["canonical_images"] = df.apply(extract_images, axis=1)

        return df