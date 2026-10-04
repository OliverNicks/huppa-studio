# test_adapters.py
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from adapters.registry import registry

# Test with Huppa
df_huppa = registry.load_and_normalize("data/huppa.xlsx")
print("\nHuppa Canonical Columns:", [c for c in df_huppa.columns if c.startswith("canonical_")])
print(df_huppa[["canonical_sku", "canonical_model", "canonical_size", "canonical_price"]].head(2))

# Test with Reima
df_reima = registry.load_and_normalize("data/reima.xlsx")
print("\nReima Canonical Columns:", [c for c in df_reima.columns if c.startswith("canonical_")])
print(df_reima[["canonical_sku", "canonical_model", "canonical_size", "canonical_price"]].head(2))