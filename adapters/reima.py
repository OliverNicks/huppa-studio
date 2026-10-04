from pathlib import Path
import pandas as pd
from adapters.base import BaseSupplierAdapter


class ReimaAdapter(BaseSupplierAdapter):
    """Adapter for normalizing Reima collection spreadsheets."""

    def can_handle(self, df: pd.DataFrame, filename: str) -> bool:
        """Check if filename contains 'reima' or if distinct Reima columns exist."""
        # 1. Check filename
        if "reima" in Path(filename).stem.lower():
            return True

        # 2. Check header markers
        cleaned_headers = {str(col).strip().lower() for col in df.columns}
        reima_markers = {"style", "товарний знак"}
        return reima_markers.issubset(cleaned_headers)

    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize raw Reima data into canonical columns."""
        df = df.copy()
        df.columns = [str(col).strip() for col in df.columns]
        df = df.dropna(how="all")

        # 1. Clean string representations for composite SKU construction
        clean_style = df["Style"].astype(str).str.strip()
        clean_color = df["Колір"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
        clean_size = df["Розмір"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)

        # 2. Construct canonical composite SKU: Style-Color-Size
        df["canonical_sku"] = clean_style + "-" + clean_color + "-" + clean_size

        # 3. Standardize core canonical columns
        df["canonical_model_code"] = clean_style
        df["canonical_color_code"] = clean_color
        df["canonical_size"] = clean_size
        df["canonical_model"] = df.get("Опис: ua_Назва для сайту", clean_style)
        df["canonical_brand"] = df.get("Товарний знак", "Reima").fillna("Reima")
        df["canonical_description"] = df.get("Опис: ua_Опис", "")

        # 4. Handle pricing (RRP column from Reima sheet)
        price_col_candidates = [
            c for c in df.columns if "ррц" in c.lower() or "ціна" in c.lower()
        ]
        if price_col_candidates:
            df["canonical_price"] = pd.to_numeric(
                df[price_col_candidates[0]].astype(str).str.replace(r"[^\d.]", "", regex=True),
                errors="coerce",
            ).fillna(0.0)
        else:
            df["canonical_price"] = 0.0

        # 5. Default stock & blank special price
        df["canonical_stock"] = 1  # Standard availability for wholesale catalogs
        df["canonical_special_price"] = None
        df["canonical_barcode"] = None

        # 6. Set empty images list (since photos are stored separately on Drive by SKU)
        df["canonical_images"] = [[] for _ in range(len(df))]

        return df