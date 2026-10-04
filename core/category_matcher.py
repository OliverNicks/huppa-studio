from typing import List, Tuple, Optional, Set
from core.models import ParentProduct


# Real OpenCart Category Mapping from huppa.com.ua database (Mirohost)
# Includes exact supplier categories from data/huppa.xlsx
CATEGORY_RULES = {
    # -------------------------------------------------------------------------
    # 59: Overalls & Baby sleep sacks
    # -------------------------------------------------------------------------
    "Конверт - Спальный мешок": {
        "parent_id": 59,
        "gender_map": {"default": 107}
    },
    "Конверт для новорожденных": {
        "parent_id": 59,
        "gender_map": {"default": 107}
    },
    "Конверт - Комбинезон - Спальный мешок": {
        "parent_id": 59,
        "gender_map": {
            "Хлопчик": 75,
            "Дівчинка": 76,
            "default": 107
        }
    },
    "Спальный мешок - Для коляски": {
        "parent_id": 59,
        "gender_map": {"default": 107}
    },
    "Конверт": {
        "parent_id": 59,
        "gender_map": {"default": 107}
    },
    "Конверти": {
        "parent_id": 59,
        "gender_map": {"default": 107}
    },
    "Комбинезон": {
        "parent_id": 59,
        "gender_map": {
            "Хлопчик": 75,
            "Дівчинка": 76,
        }
    },
    "Комбінезон": {
        "parent_id": 59,
        "gender_map": {
            "Хлопчик": 75,
            "Дівчинка": 76,
        }
    },

    # -------------------------------------------------------------------------
    # 60: Jackets & Parkas
    # -------------------------------------------------------------------------
    "Пальто - Плащ - Куртка - Парка": {
        "parent_id": 62,
        "gender_map": {
            "Хлопчик": 79,
            "Дівчинка": 80,
            "Чоловікам": 81,
            "Жінкам": 82,
        }
    },
    "Пальто - Куртка - Парка": {
        "parent_id": 62,
        "gender_map": {
            "Хлопчик": 79,
            "Дівчинка": 80,
            "Чоловікам": 81,
            "Жінкам": 82,
        }
    },
    "Куртка - Парка - Пальто": {
        "parent_id": 60,
        "gender_map": {
            "Хлопчик": 70,
            "Дівчинка": 71,
            "Чоловікам": 72,
            "Жінкам": 73,
        }
    },
    "Куртка - Парка": {
        "parent_id": 60,
        "gender_map": {
            "Хлопчик": 70,
            "Дівчинка": 71,
            "Чоловікам": 72,
            "Жінкам": 73,
        }
    },
    "Куртка - Дождевик": {
        "parent_id": 60,
        "gender_map": {
            "Хлопчик": 70,
            "Дівчинка": 71,
            "Чоловікам": 72,
            "Жінкам": 73,
        }
    },
    "Парка - Пальто": {
        "parent_id": 62,
        "gender_map": {
            "Хлопчик": 79,
            "Дівчинка": 80,
            "Чоловікам": 81,
            "Жінкам": 82,
        }
    },
    "Парка": {
        "parent_id": 60,
        "gender_map": {
            "Хлопчик": 70,
            "Дівчинка": 71,
            "Чоловікам": 72,
            "Жінкам": 73,
        }
    },
    "Куртка": {
        "parent_id": 60,
        "gender_map": {
            "Хлопчик": 70,
            "Дівчинка": 71,
            "Чоловікам": 72,
            "Жінкам": 73,
        }
    },

    # -------------------------------------------------------------------------
    # 61: Sets
    # -------------------------------------------------------------------------
    "Комплект (куртка+полукомбинезон)": {
        "parent_id": 61,
        "gender_map": {
            "Хлопчик": 77,
            "Дівчинка": 78,
        }
    },
    "Комплект (куртка+напівкомбінезон)": {
        "parent_id": 61,
        "gender_map": {
            "Хлопчик": 77,
            "Дівчинка": 78,
        }
    },
    "Комплект (куртка+брюки)": {
        "parent_id": 61,
        "gender_map": {
            "Хлопчик": 77,
            "Дівчинка": 78,
        }
    },
    "Комплект (куртка+штани)": {
        "parent_id": 61,
        "gender_map": {
            "Хлопчик": 77,
            "Дівчинка": 78,
        }
    },
    "Комплект": {
        "parent_id": 61,
        "gender_map": {
            "Хлопчик": 77,
            "Дівчинка": 78,
        }
    },

    # -------------------------------------------------------------------------
    # 62: Coats
    # -------------------------------------------------------------------------
    "Пальто - Плащ": {
        "parent_id": 62,
        "gender_map": {
            "Хлопчик": 79,
            "Дівчинка": 80,
            "Чоловікам": 81,
            "Жінкам": 82,
        }
    },
    "Пальто": {
        "parent_id": 62,
        "gender_map": {
            "Хлопчик": 79,
            "Дівчинка": 80,
            "Чоловікам": 81,
            "Жінкам": 82,
        }
    },

    # -------------------------------------------------------------------------
    # 63: Trousers & 64: Semi-overalls / Bib pants
    # -------------------------------------------------------------------------
    "Брюки - Полукомбинезон - Дождевик": {
        "parent_id": 64,
        "gender_map": {
            "Хлопчик": 87,
            "Дівчинка": 88,
        }
    },
    "Брюки - Полукомбинезон": {
        "parent_id": 64,
        "gender_map": {
            "Хлопчик": 87,
            "Дівчинка": 88,
        }
    },
    "Полукомбинезон": {
        "parent_id": 64,
        "gender_map": {
            "Хлопчик": 87,
            "Дівчинка": 88,
        }
    },
    "Напівкомбінезон": {
        "parent_id": 64,
        "gender_map": {
            "Хлопчик": 87,
            "Дівчинка": 88,
        }
    },
    "Брюки": {
        "parent_id": 63,
        "gender_map": {
            "Хлопчик": 84,
            "Дівчинка": 83,
            "Чоловікам": 85,
            "Жінкам": 86,
        }
    },
    "Штани": {
        "parent_id": 63,
        "gender_map": {
            "Хлопчик": 84,
            "Дівчинка": 83,
            "Чоловікам": 85,
            "Жінкам": 86,
        }
    },

    # -------------------------------------------------------------------------
    # 65: Fleece & Jacket - Cardigan
    # -------------------------------------------------------------------------
    "Жакет - Кофта": {
        "parent_id": 65,
        "gender_map": {
            "Хлопчик": 91,
            "Дівчинка": 92,
        }
    },
    "Флісовий комбінезон": {
        "parent_id": 65,
        "gender_map": {
            "Хлопчик": 89,
            "Дівчинка": 90,
        }
    },
    "Флісова кофта": {
        "parent_id": 65,
        "gender_map": {
            "Хлопчик": 91,
            "Дівчинка": 92,
        }
    },
    "Флісові штани": {
        "parent_id": 65,
        "gender_map": {
            "Хлопчик": 93,
            "Дівчинка": 94,
        }
    },
    "Фліс": {
        "parent_id": 65,
        "gender_map": {}
    },

    # -------------------------------------------------------------------------
    # 66: Hats & 67: Balaclavas / Helmet hats
    # -------------------------------------------------------------------------
    "Шапка - Шлем": {
        "parent_id": 67,
        "gender_map": {
            "Хлопчик": 97,
            "Дівчинка": 98,
        }
    },
    "Шапка-шолом": {
        "parent_id": 67,
        "gender_map": {
            "Хлопчик": 97,
            "Дівчинка": 98,
        }
    },
    "Шапки шоломи": {
        "parent_id": 67,
        "gender_map": {
            "Хлопчик": 97,
            "Дівчинка": 98,
        }
    },
    "Манишка": {
        "parent_id": 66,
        "gender_map": {"default": 103}
    },
    "Манішка": {
        "parent_id": 66,
        "gender_map": {"default": 103}
    },
    "Шапка": {
        "parent_id": 66,
        "gender_map": {
            "Хлопчик": 95,
            "Дівчинка": 96,
        }
    },
    "Шапки": {
        "parent_id": 66,
        "gender_map": {
            "Хлопчик": 95,
            "Дівчинка": 96,
        }
    },

    # -------------------------------------------------------------------------
    # 68: Mittens, Gloves, Booties
    # -------------------------------------------------------------------------
    "Варежки - Для коляски": {
        "parent_id": 68,
        "gender_map": {"default": 68}
    },
    "Варежки": {
        "parent_id": 68,
        "gender_map": {"default": 68}
    },
    "Перчатки": {
        "parent_id": 68,
        "gender_map": {"default": 102}
    },
    "Краги": {
        "parent_id": 68,
        "gender_map": {"default": 102}
    },
    "Пинетки": {
        "parent_id": 68,
        "gender_map": {"default": 101}
    },
    "Пінетки": {
        "parent_id": 68,
        "gender_map": {"default": 101}
    },
    "Рукавиці": {
        "parent_id": 68,
        "gender_map": {"default": 68}
    },

    # -------------------------------------------------------------------------
    # 69: Knitwear (Skirts, Dresses, T-shirts)
    # -------------------------------------------------------------------------
    "Юбка": {
        "parent_id": 69,
        "gender_map": {"default": 104}
    },
    "Спідниця": {
        "parent_id": 69,
        "gender_map": {"default": 104}
    },
    "Платье": {
        "parent_id": 69,
        "gender_map": {"default": 105}
    },
    "Плаття": {
        "parent_id": 69,
        "gender_map": {"default": 105}
    },
    "Футболка": {
        "parent_id": 69,
        "gender_map": {"default": 106}
    },
    "Трикотаж": {
        "parent_id": 69,
        "gender_map": {}
    }
}


def resolve_categories_for_product(
    product: ParentProduct,
    taxonomy_type: Optional[str] = None,
    product_type: Optional[str] = None,
    genders: Optional[List[str]] = None,
    **kwargs
) -> Tuple[Optional[int], List[int]]:
    """
    Resolves the main_category_id and all category_ids for a product
    based on its category type and target gender(s).

    Priority:
      1. product.product_type (Excel spreadsheet raw value - ground truth)
      2. taxonomy_type (AI NormalizedTaxonomy classification fallback)
      3. Fallback text search on model_name & description

    Returns:
        (main_category_id, [all_category_ids])
    """
    sorted_keys = sorted(CATEGORY_RULES.keys(), key=len, reverse=True)

    def _match_candidate(candidate: Optional[str]):
        if not candidate:
            return None
        clean = candidate.strip().lower()
        # A. Exact match first
        for key in sorted_keys:
            if key.lower() == clean:
                return CATEGORY_RULES[key]
        # B. Substring match
        for key in sorted_keys:
            if key.lower() in clean or clean in key.lower():
                return CATEGORY_RULES[key]
        return None

    # PRIORITY 1: Supplier raw type from Excel (ParentProduct.product_type)
    matched_rule = _match_candidate(product.product_type)

    # PRIORITY 2: AI Fallback from NormalizedTaxonomy
    if not matched_rule:
        fallback = taxonomy_type or product_type or kwargs.get("fallback_type")
        matched_rule = _match_candidate(fallback)

    # PRIORITY 3: Full-text scan in model name and description
    if not matched_rule:
        full_text = f"{product.model_name} {product.raw_description}".lower()
        for key in sorted_keys:
            if key.lower() in full_text:
                matched_rule = CATEGORY_RULES[key]
                break

    if not matched_rule:
        return (None, [])

    parent_id = matched_rule["parent_id"]
    gender_map = matched_rule.get("gender_map", {})

    target_genders = list(genders) if genders else []
    if not target_genders and getattr(product, "gender", None):
        raw_g = str(product.gender).lower()
        if "хлопч" in raw_g or "мальч" in raw_g:
            target_genders.append("Хлопчик")
        if "дівчат" in raw_g or "девоч" in raw_g:
            target_genders.append("Дівчинка")
        if "чоловік" in raw_g or "мужчин" in raw_g:
            target_genders.append("Чоловікам")
        if "жінок" in raw_g or "женщин" in raw_g:
            target_genders.append("Жінкам")

    subcategories: List[int] = []

    for g in target_genders:
        for g_key, cat_id in gender_map.items():
            if g_key.lower() in g.lower():
                if cat_id not in subcategories:
                    subcategories.append(cat_id)

    if not subcategories and "default" in gender_map:
        subcategories.append(gender_map["default"])

    # All categories include subcategories + parent category
    all_categories = list(subcategories)
    if parent_id not in all_categories:
        all_categories.append(parent_id)

    # Main category is the most specific subcategory, or parent if no subcategory
    main_cat_id = subcategories[0] if subcategories else parent_id

    return (main_cat_id, all_categories)
