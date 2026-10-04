import os
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from core.models import ParentProduct
from core.copywriter import ProductCopywriter

# 1. Load intermediate JSON from Phase 2
with open("output/reima_aggregated.json", "r", encoding="utf-8") as f:
    data = json.load(f)

first_product = ParentProduct.model_validate(data[0])
print(f"Loaded: {first_product.brand} {first_product.model_name} ({first_product.parent_id})")

# 2. Enrich with LLM
copywriter = ProductCopywriter()
print("\nGenerating copy with LLM...")
enriched = copywriter.enrich_product(first_product)

# 3. Inspect results
print("\n=== GENERATED METADATA ===")
print(f"Meta Title: {enriched.meta_title}")
print(f"Meta Description: {enriched.meta_description}")
print(f"Keywords: {enriched.meta_keyword}")
print("\n=== ATTRIBUTES ===")
for attr in enriched.attributes:
    print(f" - {attr.name}: {attr.value}")
print("\n=== HTML PREVIEW ===")
print(enriched.html_description)