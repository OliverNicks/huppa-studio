import re
from typing import List
from core.models import ParentProduct

CYR_TO_LAT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'h', 'ґ': 'g', 'д': 'd', 'е': 'e', 'є': 'ye',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'і': 'i', 'ї': 'yi', 'й': 'j', 'к': 'k', 'л': 'l',
    'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ь': '',
    'ю': 'yu', 'я': 'ya', 'ъ': '', 'ы': 'y', 'э': 'e', 'ё': 'yo'
}


def generate_seo_slug(product: ParentProduct) -> str:
    """
    Generates a clean, unique transliterated SEO URL slug for OpenCart oc_url_alias.
    Example: 'shtani-dlya-ditej-huppa-freja-21700010-00009-chorni'
    """
    if product.enriched and product.enriched.ua and product.enriched.ua.name:
        raw_source = product.enriched.ua.name
    elif product.enriched and product.enriched.ua and product.enriched.ua.meta_h1:
        raw_source = product.enriched.ua.meta_h1
    else:
        parts = []
        p_type = product.product_type or "Одяг"
        parts.append(p_type)
        parts.append("для дітей")
        if product.brand:
            parts.append(product.brand)
        if product.model_name and product.model_name.lower() not in (product.brand or "").lower():
            parts.append(product.model_name)
        clean_model = product.model_code.strip() if product.model_code else product.parent_id.split('_')[0]
        clean_color = product.color_code.strip() if product.color_code else (product.parent_id.split('_')[1] if '_' in product.parent_id else "")
        color_padded = clean_color.zfill(5) if clean_color.isdigit() and len(clean_color) < 5 else clean_color
        code_part = f"{clean_model}-{color_padded}" if color_padded else clean_model
        parts.append(code_part)
        if product.color_name:
            parts.append(product.color_name)
        raw_source = " ".join(parts)

    raw = raw_source.lower()

    translit = []
    for ch in raw:
        if ch in CYR_TO_LAT:
            translit.append(CYR_TO_LAT[ch])
        elif ch.isalnum() or ch in '-_':
            translit.append(ch)
        else:
            translit.append('-')

    slug = "".join(translit)
    slug = re.sub(r'[-_]+', '-', slug).strip('-')
    return slug[:250]


def _escape_sql(val: str) -> str:
    if val is None:
        return "NULL"
    # Escape backslashes and single quotes for clean MySQL injection
    escaped = str(val).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


class OpenCartSQLExporter:
    def __init__(
        self,
        table_prefix: str = "oc_",
        lang_ua_id: int = 3,           # Exact ID for UA from your oc_language
        lang_ru_id: int = 1,           # Exact ID for RU from your oc_language
        size_option_id: int = 11,      # Option "Size"
        attribute_group_id: int = 7    # Group "Characteristics"
    ):
        self.prefix = table_prefix
        self.lang_ua = lang_ua_id
        self.lang_ru = lang_ru_id
        self.size_option_id = size_option_id
        self.attribute_group_id = attribute_group_id

    def generate_sql(self, products: List[ParentProduct], output_path: str):
        lines = [
            "-- OpenCart Catalog Auto-Generated SQL Migration",
            "SET NAMES utf8mb4;",
            "SET FOREIGN_KEY_CHECKS = 0;",
            "START TRANSACTION;\n",
            f"-- Get default customer group ID for specials (oc_product_special)",
            f"SET @default_customer_group_id = (SELECT `customer_group_id` FROM `{self.prefix}customer_group` ORDER BY `sort_order` ASC, `customer_group_id` ASC LIMIT 1);",
            f"SET @default_customer_group_id = IFNULL(@default_customer_group_id, 1);\n",
            f"-- Get stock status IDs (oc_stock_status)",
            f"SET @stock_out_of_stock_id = (SELECT `stock_status_id` FROM `{self.prefix}stock_status` WHERE LOWER(`name`) LIKE '%нет в налич%' OR LOWER(`name`) LIKE '%немає%' OR LOWER(`name`) LIKE '%відсутн%' OR LOWER(`name`) LIKE '%out of stock%' LIMIT 1);",
            f"SET @stock_out_of_stock_id = IFNULL(@stock_out_of_stock_id, 5);",
            f"SET @stock_in_stock_id = (SELECT `stock_status_id` FROM `{self.prefix}stock_status` WHERE (LOWER(`name`) LIKE '%в налич%' OR LOWER(`name`) LIKE '%наявн%' OR LOWER(`name`) LIKE '%in stock%') AND LOWER(`name`) NOT LIKE '%нет%' AND LOWER(`name`) NOT LIKE '%немає%' LIMIT 1);",
            f"SET @stock_in_stock_id = IFNULL(@stock_in_stock_id, 7);\n"
        ]

        system_attrs = {
            "бренд", "модель", "колір", "номер кольору", "цвет", "номер цвета", 
            "розмір", "размер", "артикул", "код товару", "штрихкод"
        }

        for p in products:
            clean_model = p.model_code.strip() if p.model_code else p.parent_id.split('_')[0]
            clean_color = p.color_code.strip() if p.color_code else (p.parent_id.split('_')[1] if '_' in p.parent_id else "")
            color_padded = clean_color.zfill(5) if clean_color.isdigit() and len(clean_color) < 5 else clean_color

            # Product Code in OpenCart (oc_product.model) = model_number - color_code (with 5 digits)
            # SKU in OpenCart (oc_product.sku) = model_number
            product_code = f"{clean_model}-{color_padded}" if color_padded else clean_model
            product_sku = clean_model

            model_esc = _escape_sql(product_code)
            sku_esc = _escape_sql(product_sku)
            parent_id_esc = _escape_sql(p.parent_id)

            brand_esc = _escape_sql(p.brand)
            total_qty = sum(v.stock for v in p.size_variants)
            main_image = p.main_image
            main_img_esc = _escape_sql(main_image)
            main_cat_id = p.main_category_id or 0

            lines.append(f"\n-- ----------------------------------------------------")
            lines.append(f"-- Product: {p.brand} {p.model_name} (Code: {product_code}, SKU: {product_sku})")
            lines.append(f"-- ----------------------------------------------------")

            # 1. Find or create manufacturer (oc_manufacturer)
            lines.append(f"""
-- Manufacturer: {p.brand}
SET @current_manufacturer_id = (
    SELECT `manufacturer_id` FROM `{self.prefix}manufacturer` 
    WHERE LOWER(`name`) = LOWER({brand_esc}) 
    LIMIT 1
);

INSERT INTO `{self.prefix}manufacturer` (`name`, `sort_order`)
SELECT {brand_esc}, 0 FROM DUAL WHERE @current_manufacturer_id IS NULL;

SET @current_manufacturer_id = (
    SELECT IFNULL(@current_manufacturer_id, (SELECT MAX(`manufacturer_id`) FROM `{self.prefix}manufacturer`))
);

INSERT IGNORE INTO `{self.prefix}manufacturer_to_store` (`manufacturer_id`, `store_id`)
VALUES (@current_manufacturer_id, 0);
""")

            # 2. Base product card (oc_product)
            # Product code -> `model` = 21700010-00009
            # SKU          -> `sku`   = 21700010
            lines.append(f"""
SET @current_product_id = (
    SELECT `product_id` FROM `{self.prefix}product` 
    WHERE `model` = {model_esc} 
       OR `sku` = {model_esc}
       OR `sku` = {parent_id_esc}
    LIMIT 1
);

UPDATE `{self.prefix}product` SET
    `model` = {model_esc},
    `sku` = {sku_esc},
    `manufacturer_id` = @current_manufacturer_id,
    `quantity` = {total_qty},
    `stock_status_id` = IF({total_qty} > 0, @stock_in_stock_id, @stock_out_of_stock_id),
    `image` = IF({main_img_esc} != '', {main_img_esc}, `image`),
    `price` = {p.base_price},
    `date_modified` = NOW()
WHERE `product_id` = @current_product_id;

INSERT INTO `{self.prefix}product` (
    `model`, `sku`, `manufacturer_id`, `quantity`, `stock_status_id`, `image`, `price`, 
    `shipping`, `status`, `date_available`, `date_added`, `date_modified`
) 
SELECT 
    {model_esc}, {sku_esc}, @current_manufacturer_id, {total_qty}, IF({total_qty} > 0, @stock_in_stock_id, @stock_out_of_stock_id), {main_img_esc}, {p.base_price},
    1, 1, CURDATE(), NOW(), NOW()
FROM DUAL 
WHERE @current_product_id IS NULL;

SET @current_product_id = (SELECT IFNULL(@current_product_id, LAST_INSERT_ID()));

INSERT IGNORE INTO `{self.prefix}product_to_store` (`product_id`, `store_id`) 
VALUES (@current_product_id, 0);

-- Product SEO URL (oc_url_alias)
DELETE FROM `{self.prefix}url_alias` 
WHERE `query` = CONCAT('product_id=', @current_product_id)
   OR `keyword` = {_escape_sql(generate_seo_slug(p))};

INSERT INTO `{self.prefix}url_alias` (`query`, `keyword`)
VALUES (CONCAT('product_id=', @current_product_id), {_escape_sql(generate_seo_slug(p))});
""")

            # 2.5. Product special price (oc_product_special)
            lines.append(f"\n-- Product special price (oc_product_special)")
            lines.append(f"DELETE FROM `{self.prefix}product_special` WHERE `product_id` = @current_product_id;")
            if p.special_price is not None and 0 < p.special_price < p.base_price:
                lines.append(f"""INSERT INTO `{self.prefix}product_special` (
    `product_id`, `customer_group_id`, `priority`, `price`, `date_start`, `date_end`
) VALUES (
    @current_product_id, @default_customer_group_id, 1, {p.special_price}, '0000-00-00', '0000-00-00'
);""")

            # 3. Product categories (oc_product_to_category)
            if p.category_ids:
                lines.append(f"\n-- Category assignment (oc_product_to_category)")
                lines.append(f"DELETE FROM `{self.prefix}product_to_category` WHERE `product_id` = @current_product_id;")
                for cat_id in p.category_ids:
                    is_main = 1 if cat_id == p.main_category_id else 0
                    lines.append(f"""INSERT IGNORE INTO `{self.prefix}product_to_category` (`product_id`, `category_id`, `main_category`)
VALUES (@current_product_id, {cat_id}, {is_main});""")

            # 4. Additional gallery images (oc_product_image)
            gallery_images = p.gallery_images
            if gallery_images:
                lines.append(f"\n-- Gallery additional images for product: {p.parent_id}")
                lines.append(f"DELETE FROM `{self.prefix}product_image` WHERE `product_id` = @current_product_id;")
                for idx, g_img in enumerate(gallery_images, start=1):
                    lines.append(f"""INSERT INTO `{self.prefix}product_image` (`product_id`, `image`, `sort_order`)
VALUES (@current_product_id, {_escape_sql(g_img)}, {idx});""")

            # 5. Product descriptions (oc_product_description)
            if p.enriched:
                ua = p.enriched.ua
                ru = p.enriched.ru

                # UA
                lines.append(f"""
INSERT INTO `{self.prefix}product_description` (
    `product_id`, `language_id`, `name`, `description`, `tag`, `meta_title`, `meta_h1`, `meta_description`, `meta_keyword`
) VALUES (
    @current_product_id, {self.lang_ua}, {_escape_sql(ua.name)}, {_escape_sql(ua.html_description)},
    {_escape_sql(ua.tag)}, {_escape_sql(ua.meta_title)}, {_escape_sql(ua.meta_h1)}, {_escape_sql(ua.meta_description)}, {_escape_sql(ua.meta_keyword)}
) ON DUPLICATE KEY UPDATE
    `name` = VALUES(`name`),
    `description` = VALUES(`description`),
    `tag` = VALUES(`tag`),
    `meta_title` = VALUES(`meta_title`),
    `meta_h1` = VALUES(`meta_h1`),
    `meta_description` = VALUES(`meta_description`),
    `meta_keyword` = VALUES(`meta_keyword`);
""")

                # RU
                lines.append(f"""
INSERT INTO `{self.prefix}product_description` (
    `product_id`, `language_id`, `name`, `description`, `tag`, `meta_title`, `meta_h1`, `meta_description`, `meta_keyword`
) VALUES (
    @current_product_id, {self.lang_ru}, {_escape_sql(ru.name)}, {_escape_sql(ru.html_description)},
    {_escape_sql(ru.tag)}, {_escape_sql(ru.meta_title)}, {_escape_sql(ru.meta_h1)}, {_escape_sql(ru.meta_description)}, {_escape_sql(ru.meta_keyword)}
) ON DUPLICATE KEY UPDATE
    `name` = VALUES(`name`),
    `description` = VALUES(`description`),
    `tag` = VALUES(`tag`),
    `meta_title` = VALUES(`meta_title`),
    `meta_h1` = VALUES(`meta_h1`),
    `meta_description` = VALUES(`meta_description`),
    `meta_keyword` = VALUES(`meta_keyword`);
""")

                # 6. Attributes (oc_product_attribute)
                lines.append(f"\n-- Product attributes: {p.parent_id}")
                ua_attrs = [a for a in p.enriched.ua.attributes if a.name.lower().strip() not in system_attrs]
                ru_attrs = [a for a in p.enriched.ru.attributes if a.name.lower().strip() not in system_attrs]

                for idx, attr_ua in enumerate(ua_attrs):
                    attr_ru = ru_attrs[idx] if idx < len(ru_attrs) else attr_ua
                    ua_name_esc = _escape_sql(attr_ua.name.strip())
                    ru_name_esc = _escape_sql(attr_ru.name.strip())
                    ua_val_esc = _escape_sql(attr_ua.value.strip())
                    ru_val_esc = _escape_sql(attr_ru.value.strip())

                    lines.append(f"""
SET @current_attr_id = (
    SELECT `attribute_id` FROM `{self.prefix}attribute_description`
    WHERE (`language_id` = {self.lang_ua} AND `name` = {ua_name_esc})
       OR (`language_id` = {self.lang_ru} AND `name` = {ru_name_esc})
    LIMIT 1
);

INSERT INTO `{self.prefix}attribute` (`attribute_group_id`, `sort_order`)
SELECT {self.attribute_group_id}, 0 FROM DUAL WHERE @current_attr_id IS NULL;

SET @current_attr_id = (
    SELECT IFNULL(@current_attr_id, (SELECT MAX(`attribute_id`) FROM `{self.prefix}attribute`))
);

INSERT IGNORE INTO `{self.prefix}attribute_description` (`attribute_id`, `language_id`, `name`)
VALUES 
    (@current_attr_id, {self.lang_ua}, {ua_name_esc}),
    (@current_attr_id, {self.lang_ru}, {ru_name_esc});

INSERT INTO `{self.prefix}product_attribute` (`product_id`, `attribute_id`, `language_id`, `text`)
VALUES 
    (@current_product_id, @current_attr_id, {self.lang_ua}, {ua_val_esc}),
    (@current_product_id, @current_attr_id, {self.lang_ru}, {ru_val_esc})
ON DUPLICATE KEY UPDATE `text` = VALUES(`text`);
""")

                # 7. OCFilter filter options (oc_ocfilter_option_value_to_product)
                if p.enriched.ocfilters:
                    lines.append(f"\n-- OCFilter filter options (oc_ocfilter_option_value_to_product)")
                    lines.append(f"DELETE FROM `{self.prefix}ocfilter_option_value_to_product` WHERE `product_id` = @current_product_id;")
                    for filter_name, filter_values in p.enriched.ocfilters.items():
                        filter_name_esc = _escape_sql(filter_name.strip())
                        is_size_filter = filter_name.strip().lower() in ["размер", "розмір"]

                        for val in filter_values:
                            val_esc = _escape_sql(val.strip())

                            if is_size_filter:
                                # Strict exact match for sizes to prevent '56' falsely matching single digit '5'
                                val_condition = f"TRIM(LOWER(`name`)) = TRIM(LOWER({val_esc}))"
                                order_by_sql = ""
                            else:
                                val_condition = f"""(
          LOWER(`name`) = LOWER({val_esc})
          OR LOWER(`name`) LIKE CONCAT(LOWER({val_esc}), '%')
          OR REPLACE(LOWER(`name`), 'і', 'и') = REPLACE(LOWER({val_esc}), 'і', 'и')
          OR REPLACE(LOWER(`name`), '-', ' ') = REPLACE(LOWER({val_esc}), '-', ' ')
          OR (LOWER({val_esc}) = 'конверт' AND LOWER(`name`) LIKE '%спальн%')
      )"""
                                order_by_sql = f"\n    ORDER BY (LOWER(`name`) = LOWER({val_esc})) DESC"

                            lines.append(f"""
SET @f_opt_id = (
    SELECT `option_id` FROM `{self.prefix}ocfilter_option_description` 
    WHERE LOWER(`name`) = LOWER({filter_name_esc}) 
       OR LOWER(`name`) LIKE CONCAT(LOWER({filter_name_esc}), '%')
    LIMIT 1
);
SET @f_val_id = (
    SELECT `value_id` FROM `{self.prefix}ocfilter_option_value_description` 
    WHERE `option_id` = @f_opt_id 
      AND {val_condition}{order_by_sql}
    LIMIT 1
);
INSERT IGNORE INTO `{self.prefix}ocfilter_option_value_to_product` (
    `product_id`, `option_id`, `value_id`, `slide_value_min`, `slide_value_max`
)
SELECT @current_product_id, @f_opt_id, @f_val_id, 0, 0
FROM DUAL
WHERE @f_opt_id IS NOT NULL AND @f_val_id IS NOT NULL;
""")

            # 8. Size options (oc_product_option and oc_product_option_value)
            if p.size_variants:
                lines.append(f"""
-- Clear previous product options to avoid duplicates on re-import
DELETE FROM `{self.prefix}product_option_value` WHERE `product_id` = @current_product_id AND `option_id` = {self.size_option_id};
DELETE FROM `{self.prefix}product_option` WHERE `product_id` = @current_product_id AND `option_id` = {self.size_option_id};

-- Link 'Size' option
INSERT INTO `{self.prefix}product_option` (`product_id`, `option_id`, `value`, `required`)
VALUES (@current_product_id, {self.size_option_id}, '', 1);

SET @current_product_option_id = LAST_INSERT_ID();
""")

                for var in p.size_variants:
                    size_esc = _escape_sql(var.size.strip())

                    lines.append(f"""
-- Size variant: {var.size}
SET @opt_val_id = (
    SELECT `option_value_id` FROM `{self.prefix}option_value_description` 
    WHERE `option_id` = {self.size_option_id} AND `name` = {size_esc} 
    LIMIT 1
);

INSERT INTO `{self.prefix}option_value` (`option_id`, `sort_order`)
SELECT {self.size_option_id}, 0 FROM DUAL WHERE @opt_val_id IS NULL;

SET @opt_val_id = (
    SELECT IFNULL(
        @opt_val_id, 
        (SELECT MAX(`option_value_id`) FROM `{self.prefix}option_value` WHERE `option_id` = {self.size_option_id})
    )
);

INSERT IGNORE INTO `{self.prefix}option_value_description` (`option_value_id`, `language_id`, `option_id`, `name`)
VALUES 
    (@opt_val_id, {self.lang_ua}, {self.size_option_id}, {size_esc}),
    (@opt_val_id, {self.lang_ru}, {self.size_option_id}, {size_esc});

INSERT INTO `{self.prefix}product_option_value` (
    `product_option_id`, `product_id`, `option_id`, `option_value_id`, 
    `quantity`, `subtract`, `price`, `price_prefix`
) VALUES (
    @current_product_option_id, @current_product_id, {self.size_option_id}, @opt_val_id,
    {var.stock}, 1, {var.price_diff}, {_escape_sql(var.price_prefix)}
);
""")

            # 9. Related products: other colors of the same model (oc_product_related)
            if clean_model and clean_model != "UNKNOWN":
                lines.append(f"""
-- Related products: other colors of the same model '{clean_model}' (oc_product_related)
DELETE FROM `{self.prefix}product_related` WHERE `product_id` = @current_product_id;

INSERT IGNORE INTO `{self.prefix}product_related` (`product_id`, `related_id`)
SELECT @current_product_id, `product_id`
FROM `{self.prefix}product`
WHERE `sku` = {sku_esc} AND `sku` != '' AND `sku` != 'UNKNOWN' AND `product_id` != @current_product_id;

-- Bidirectional link with existing colors of this model in DB
INSERT IGNORE INTO `{self.prefix}product_related` (`product_id`, `related_id`)
SELECT `product_id`, @current_product_id
FROM `{self.prefix}product`
WHERE `sku` = {sku_esc} AND `sku` != '' AND `sku` != 'UNKNOWN' AND `product_id` != @current_product_id;
""")

        lines.append("\nCOMMIT;")
        lines.append("SET FOREIGN_KEY_CHECKS = 1;")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))