import io
import re
from dataclasses import dataclass
from typing import Any, List, Optional
import pandas as pd

csv_raw = """sku,model_id,color,size,price,stock
SHIRT-BLK-S,101.0,Black,S,25.00 €,12
SHIRT-BLK-M,101.0,Black,M,25.00,8
SHIRT-BLK-L,101.0,Black,L,28.50 €,0
SHIRT-WHT-S,101.0,White,S,25.00,5
SHIRT-WHT-M,101.0,White,M,,4
PANT-BLU-30,202,Blue,30,45.00 €,10
"""

df_raw = pd.read_csv(io.StringIO(csv_raw))


