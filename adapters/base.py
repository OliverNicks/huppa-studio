from abc import ABC, abstractmethod
import pandas as pd

class BaseSupplierAdapter(ABC):

    @abstractmethod
    def can_handle(self, df: pd.DataFrame, filename: str) -> bool:
        pass

    @abstractmethod
    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        pass