from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class SizeVariant(BaseModel):
    """
    Represents an individual physical variant (SKU/size option).
    Directly corresponds to an entry in OpenCart's `oc_product_option_value`.
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    size: str = Field(description="Size label (e.g., '92', '104', '48/50')")
    sku: Optional[str] = Field(default=None, description="Exact SKU for this size variant")
    barcode: Optional[str] = Field(default=None, description="EAN13 / Barcode if provided")
    stock: int = Field(default=0, description="Available inventory count")
    price: float = Field(default=0.0, description="Price specific to this variant")
    special_price: Optional[float] = Field(default=None, description="Promotional or discount price")
    price_prefix: str = Field(default="+", description="OpenCart option price prefix: '+' or '-'")
    price_diff: float = Field(default=0.0, description="Price difference relative to parent base_price")


class ProductAttributeLocalized(BaseModel):
    """
    Key-value technical specification (e.g., 'Склад' -> '100% поліестер').
    Maps to `oc_attribute_description` and `oc_product_attribute`.
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str = Field(description="Standardized attribute name")
    value: str = Field(description="Formatted attribute value")


class LocalizedCopy(BaseModel):
    """
    Language-specific marketing and SEO content.
    Maps directly to a single row in `oc_product_description`.
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str = Field(default="", description="Storefront commercial title ('Наименование')")
    meta_h1: str = Field(default="", description="HTML-tag H1 ('HTML-тег H1')")
    meta_title: str = Field(default="", description="SEO meta title ('HTML-тег Title')")
    meta_description: str = Field(default="", description="SEO meta description ('Мета-тег Description')")
    meta_keyword: str = Field(default="", description="Comma-separated SEO keywords ('Мета-тег Keywords')")
    tag: str = Field(default="", description="Product search tags ('Теги товара')")
    html_description: str = Field(default="", description="Clean HTML description with <h3>, <p>, <ul>, <li>")
    attributes: List[ProductAttributeLocalized] = Field(
        default_factory=list,
        description="List of standardized attributes for storefront specifications tab"
    )


class DualLanguageContent(BaseModel):
    """
    Container pairing Ukrainian and Russian localization models, plus OCFilter mappings.
    Guarantees strict JSON Schema compliance for LLM structured output parsing.
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    ua: LocalizedCopy
    ru: LocalizedCopy
    # Maps to OCFilter tab: {"Gender": ["Boy", "Girl"], "Insulation type": ["Synthetic"]}
    ocfilters: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Structured key-value pairs matching OCFilter names and allowed values"
    )


class ParentProduct(BaseModel):
    """
    The primary catalog entity representing a unique Model + Color.
    Maps across `oc_product`, `oc_product_description`, and `oc_product_image`.
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    parent_id: str = Field(description="Composite primary key: {model_code}_{color_code}")
    model_code: str = Field(description="Supplier model/style identifier (e.g., '21700010')")
    color_code: str = Field(description="Supplier color code (e.g., '00009')")
    model_name: str = Field(default="Без назви", description="Base model name (e.g., 'FREJA')")
    color_name: str = Field(default="", description="Base color name if provided (e.g., 'чорний')")
    product_type: str = Field(default="", description="Category hint (e.g., 'Штани', 'Куртка')")
    gender: Optional[str] = Field(default="", description="Supplier raw gender (e.g., 'Хлопчик', 'Девочка')")
    season: Optional[str] = Field(default="", description="Supplier raw season (e.g., 'Зима', 'Весна-Осінь')")
    brand: str = Field(default="", description="Manufacturer or brand name (e.g., 'HUPPA')")
    
    # Financials & Stock (oc_product)
    base_price: float = Field(default=0.0, description="Base catalog price")
    special_price: Optional[float] = Field(default=None, description="Special base promotional price")
    total_stock: int = Field(default=0, description="Summed inventory across all size variants")
    
    # Storefront routing & categorization (oc_product_to_category, oc_seo_url)
    category_ids: List[int] = Field(
        default_factory=list, 
        description="List of OpenCart category IDs to assign this product to"
    )
    main_category_id: Optional[int] = Field(
        default=None, 
        description="ID of the primary/main OpenCart category"
    )
    seo_url: Optional[str] = Field(
        default=None, 
        description="Custom SEO URL slug (e.g. 'shtani-dlya-ditej-huppa-freja-21700010-00009-chornii')"
    )

    # Media Assets (oc_product_image)
    image_urls: List[str] = Field(default_factory=list, description="Raw URLs from sheets or supplier links")
    local_image_paths: List[str] = Field(default_factory=list, description="OpenCart image paths (catalog/product/...)")
    
    # Raw unparsed supplier data (fed to LLM for context)
    raw_description: str = Field(default="", description="Original unparsed text from supplier")
    raw_specs: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary unmapped supplier columns")
    
    # Child relationships
    size_variants: List[SizeVariant] = Field(
        default_factory=list,
        description="All nested size options belonging to this product card"
    )
    
    # Enriched AI Content
    enriched: Optional[DualLanguageContent] = Field(
        default=None,
        description="Populated after Phase 3 LLM execution"
    )

    # -----------------------------------------------------------------------
    # Helper Properties
    # -----------------------------------------------------------------------
    @property
    def main_image(self) -> str:
        """Returns primary image path for OpenCart main product photo."""
        if self.local_image_paths:
            return self.local_image_paths[0]
        if self.image_urls:
            return self.image_urls[0]
        return ""

    @property
    def gallery_images(self) -> List[str]:
        """Returns secondary images for oc_product_image."""
        if len(self.local_image_paths) > 1:
            return self.local_image_paths[1:]
        if len(self.image_urls) > 1:
            return self.image_urls[1:]
        return []

    @property
    def is_in_stock(self) -> bool:
        """True if total stock across all variants is > 0."""
        return self.total_stock > 0

    @property
    def available_sizes(self) -> List[str]:
        """List of all size option labels."""
        return [v.size for v in self.size_variants]