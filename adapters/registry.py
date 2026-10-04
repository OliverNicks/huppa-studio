from pathlib import Path
from typing import List
import pandas as pd

from adapters.base import BaseSupplierAdapter
from adapters.huppa import HuppaAdapter
from adapters.reima import ReimaAdapter


class AdapterRegistry:
    """Registry that manages and resolves supplier adapters."""

    def __init__(self):
        # Register adapters in priority order
        self.adapters: List[BaseSupplierAdapter] = [
            HuppaAdapter(),
            ReimaAdapter(),
        ]

    def register(self, adapter: BaseSupplierAdapter) -> None:
        """Register a new supplier adapter dynamically."""
        self.adapters.append(adapter)

    def load_and_normalize(self, file_path: str) -> pd.DataFrame:
        """Load a spreadsheet and normalize it with the matching adapter."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # 1. Read file depending on extension
        suffix = path.suffix.lower()
        if suffix in [".xlsx", ".xlsm"]:
            df_raw = pd.read_excel(path, engine="openpyxl")
        elif suffix == ".xls":
            df_raw = pd.read_excel(path, engine="xlrd")
        elif suffix == ".csv":
            try:
                df_raw = pd.read_csv(path, sep=None, engine="python")
            except Exception:
                df_raw = pd.read_csv(path, sep=";")
        else:
            raise ValueError(f"Unsupported file format: {suffix}")

        # 2. Find matching adapter
        for adapter in self.adapters:
            if adapter.can_handle(df_raw, path.name):
                print(f"[+] Matched parser: {adapter.__class__.__name__} for {path.name}")
                return adapter.normalize(df_raw)

        raise ValueError(
            f"No matching adapter found for '{path.name}'. "
            f"Headers: {list(df_raw.columns[:5])}"
        )


# Global default instance
registry = AdapterRegistry()