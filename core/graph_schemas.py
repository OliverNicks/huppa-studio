from typing import List, Dict, Optional, Literal, TypedDict
from pydantic import BaseModel, Field
from core.models import ParentProduct, ProductAttributeLocalized, LocalizedCopy


# ===========================================================================
# 1. MAPPING DICTIONARIES (UA -> RU) FOR OCFILTER
# ===========================================================================
# These deterministic mappings allow Agent 1 to work 100% in Ukrainian,
# while still supporting OpenCart databases where OCFilter options
# were originally installed in Russian.

GENDER_MAP_UA_TO_RU = {
    "Хлопчик": "Мальчик",
    "Дівчинка": "Девочка",
    "Чоловікам": "Мужчина",
    "Жінкам": "Женщина"
}

PRODUCT_TYPE_MAP_UA_TO_RU = {
    "Штани": "Штаны",
    "Куртка": "Куртка",
    "Комбінезон": "Комбинезон",
    "Конверт": "Конверт",
    "Комплект": "Комплект",
    "Напівкомбінезон": "Полукомбинезон",
    "Парка": "Парка",
    "Пальто": "Пальто",
    "Шапка": "Шапка",
    "Шапка-шолом": "Шапка-шлем",
    "Рукавиці": "Перчатки",
    "Краги": "Краги",
    "Пінетки": "Пинетки",
    "Манішка": "Манишка",
    "Фліс": "Флис",
    "Флісовий комбінезон": "Флисовый комбинезон",
    "Флісова кофта": "Флисовая кофта",
    "Флісові штани": "Флисовые штаны",
    "Спідниця": "Юбка",
    "Плаття": "Платье",
    "Футболка": "Футболка",
    "Трикотаж": "Трикотаж",
}

AGE_GROUP_MAP_UA_TO_RU = {
    "Дітям": "Детям",
    "Підліткам": "Подросткам",
    "Дорослим": "Взрослым"
}

COLOR_MAP_UA_TO_RU = {
    "чорний": "чёрный",
    "темно-синій": "тёмно-синий",
    "синій": "синий",
    "блакитний": "голубой",
    "зелений": "зеленый",
    "лайм": "лайм",
    "жовтий": "жёлтый",
    "помаранчевий": "оранжевый",
    "жовто-гарячий": "оранжевый",
    "червоний": "красный",
    "бордовий": "бордовый",
    "рожевий": "розовый",
    "фуксія": "фуксия",
    "фіолетовий": "фиолетовый",
    "ліловий": "лиловый",
    "бірюзовий": "бирюзовый",
    "м'ятний": "мятный",
    "бежевий": "бежевый",
    "коричневий": "коричневый",
    "сірий": "серый",
    "білий": "белый",
    "морська хвиля": "морская волна",
}

INSULATION_TYPE_MAP_UA_TO_RU = {
    "Синтетичний": "Синтетический",
    "Пух і перо": "Пух и перо",
    "SoftShell": "SoftShell",
    "Без утеплювача": "Без утеплителя"
}

SEASON_MAP_UA_TO_RU = {
    "Весна - Осінь": "Весна - Осень",
    "Зима": "Зима",
    "Літо": "Лето",
    "Всесезон": "Всесезон",
    "Весна - Осінь - Зима": "Весна - Осень - Зима",
    "Весна - Літо - Осінь": "Весна - Лето - Осень",
    "Демісезон": "Демисезон"
}

RAW_PRODUCT_TYPE_TO_OCFILTER: Dict[str, str] = {
    # Sets
    "Комплект (куртка+брюки)": "Комплект",
    "Комплект (куртка+полукомбинезон)": "Комплект",
    "Комплект - Дождевик": "Комплект",
    "Комплект": "Комплект",

    # Sleep sacks & Baby nests
    "Конверт - Спальный мешок": "Конверт",
    "Комбинезон - Спальный мешок": "Конверт",
    "Конверт для новорожденных": "Конверт",
    "Спальный мешок": "Конверт",
    "Конверт": "Конверт",

    # Overalls
    "Комбинезон Softshell": "Комбинезон Softshell",
    "Комбинезон": "Комбинезон",

    # Semi-overalls / Bib pants
    "Брюки - Полукомбинезон - Дождевик": "Полукомбинезон",
    "Брюки - Полукомбинезон": "Полукомбинезон",
    "Полукомбинезон": "Полукомбинезон",

    # Trousers
    "Штаны Softshell": "Штаны Softshell",
    "Брюки - Дождевик": "Штаны",
    "Брюки": "Штаны",
    "Шорты": "Штаны",
    "Штаны": "Штаны",

    # Parkas & Jackets
    "Пальто - Плащ - Куртка - Парка": "Парка",
    "Куртка - Парка": "Парка",
    "Парка": "Парка",
    "Куртка Softshell": "Куртка Softshell",
    "Лыжная куртка": "Лыжная куртка",
    "Ветровка": "Ветровка",
    "Куртка - Дождевик": "Куртка",
    "Дождевик": "Дождевик",
    "Куртка": "Куртка",
    "Жилет": "Куртка",

    # Coats & Raincoats
    "Пальто - Плащ": "Пальто",
    "Пальто": "Пальто",
    "Плащ": "Плащ",

    # Headwear
    "Шапка - Шлем": "Шапка-шлем",
    "Шапка шлем": "Шапка-шлем",
    "Шапка": "Шапка",
    "Повязка на голову": "Шапка",
    "Кепка": "Шапка",
    "Панама": "Шапка",

    # Accessories
    "Манишка": "Манишка",
    "Пинетки": "Пинетки",
    "Перчатки": "Перчатки",
    "Краги": "Краги",
    "Варежки": "Перчатки",

    # Fleece & Knitwear
    "Флисовый комбинезон": "Флисовый комбинезон",
    "Флисовые штаны": "Флисовые штаны",
    "Жакет - Кофта": "Флисовая кофта",
    "Жакет": "Флисовая кофта",
    "Джемпер": "Флисовая кофта",
    "Кардиган": "Флисовая кофта",
    "Флисовая кофта": "Флисовая кофта",
    "Термобелье": "Термобелье",
    "Флис": "Флисовая кофта",

    # Jersey / Knitted garments
    "Платье": "Платье",
    "Юбка": "Юбка",
    "Футболка": "Футболка",
}


def resolve_ocfilter_product_type(raw_type: Optional[str]) -> Optional[str]:
    """
    Resolves OCFilter 'Тип' directly from raw Excel supplier product type.
    Uses exact matching first, followed by substring matching (longest key first).
    """
    if not raw_type:
        return None
    clean = str(raw_type).strip().lower()

    # A. Exact match first
    for key, val in RAW_PRODUCT_TYPE_TO_OCFILTER.items():
        if key.lower() == clean:
            return val

    # B. Substring match (longest match first)
    sorted_keys = sorted(RAW_PRODUCT_TYPE_TO_OCFILTER.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if key.lower() in clean or clean in key.lower():
            return RAW_PRODUCT_TYPE_TO_OCFILTER[key]

def resolve_ocfilter_color(raw_color: Optional[str]) -> Optional[str]:
    """
    Deterministically resolves OCFilter 'Цвет' directly from supplier color strings.
    Handles compound values ('лайм с принтом/темно-серый'), print variations,
    and maps them to the 21 standard OpenCart database colors.
    """
    if not raw_color:
        return None
    clean = str(raw_color).strip().lower()

    # Exact match first against dictionary values
    for ua, ru in COLOR_MAP_UA_TO_RU.items():
        if clean == ua or clean == ru:
            return ru

    # Substring / keyword matches in descending specificity order
    color_patterns = [
        ("морська хвиля", "морская волна"),
        ("морская волна", "морская волна"),
        ("бирюзово-зелен", "бирюзовый"),
        ("бірюзово-зелен", "бирюзовый"),
        ("бирюз", "бирюзовый"),
        ("бірюз", "бирюзовый"),
        ("темно-синій", "тёмно-синий"),
        ("темно-синий", "тёмно-синий"),
        ("тёмно-синий", "тёмно-синий"),
        ("темно-серый", "серый"),
        ("тёмно-серый", "серый"),
        ("темно-сірий", "серый"),
        ("тено-сірий", "серый"),
        ("светло-серый", "серый"),
        ("светло-синий", "голубой"),
        ("светло-розовый", "розовый"),
        ("светло-бежевый", "бежевый"),
        ("светло-зелен", "зеленый"),
        ("золотисто-коричнев", "коричневый"),
        ("темно-лилов", "лиловый"),
        ("тёмно-лилов", "лиловый"),
        ("тёмно-лилoв", "лиловый"),  # Handles Latin 'o' in supplier typos
        ("лилов", "лиловый"),
        ("лілов", "лиловый"),
        ("пурпур", "лиловый"),
        ("фуксия", "фуксия"),
        ("фуксія", "фуксия"),
        ("фуксиа", "фуксия"),
        ("лайм", "лайм"),
        ("мята", "мятный"),
        ("м'ята", "мятный"),
        ("мятн", "мятный"),
        ("м'ятн", "мятный"),
        ("бордов", "бордовый"),
        ("бордо", "бордовый"),
        ("блакитн", "голубой"),
        ("голубой", "голубой"),
        ("коричнев", "коричневый"),
        ("помаранчев", "оранжевый"),
        ("жовто-гаряч", "оранжевый"),
        ("оранжев", "оранжевый"),
        ("фіолетов", "фиолетовый"),
        ("фиолетов", "фиолетовый"),
        ("чорн", "чёрный"),
        ("чёрн", "чёрный"),
        ("черн", "чёрный"),
        ("біл", "белый"),
        ("бел", "белый"),
        ("червон", "красный"),
        ("красн", "красный"),
        ("жовт", "жёлтый"),
        ("жёлт", "жёлтый"),
        ("желт", "жёлтый"),
        ("жолт", "жёлтый"),
        ("рожев", "розовый"),
        ("розов", "розовый"),
        ("бежев", "бежевый"),
        ("зелен", "зеленый"),
        ("син", "синий"),
        ("сір", "серый"),
        ("сер", "серый"),
    ]

    for pat, target_ru in color_patterns:
        if pat in clean:
            return target_ru

    return None


# ===========================================================================
# 2. AGENT 1 SCHEMA: NormalizedTaxonomy (Fact & Taxonomy Extraction)
# ===========================================================================
class NormalizedTaxonomy(BaseModel):
    """
    Output of Agent 1 (Taxonomy & Attributes Specialist).
    Uses strict Literals in Ukrainian so the LLM cannot hallucinate or introduce typos.
    Runs at temperature=0.0 for deterministic classification.
    """
    gender: List[Literal["Хлопчик", "Дівчинка", "Чоловікам", "Жінкам"]] = Field(
        default_factory=list,
        description="Цільова стать. Якщо модель унісекс для дітей, обов'язково включай і 'Хлопчик', і 'Дівчинка'."
    )
    product_type: Optional[Literal[
        "Штани", "Куртка", "Комбінезон", "Конверт", "Комплект", "Напівкомбінезон",
        "Парка", "Пальто", "Шапка", "Шапка-шолом", "Рукавиці", "Краги", "Пінетки",
        "Манішка", "Фліс", "Флісовий комбінезон", "Флісова кофта", "Флісові штани",
        "Спідниця", "Плаття", "Футболка", "Трикотаж"
    ]] = Field(
        default=None, 
        description=(
            "Стандартизований тип дитячого одягу. Орієнтуйся на 'product_type_hint'. "
            "Комплекти з 2 речей (куртка+штани/напівкомбінезон) -> 'Комплект'. "
            "Спальні мішки та конверти для немовлят -> 'Конверт'. "
            "Шоломи/балаклави -> 'Шапка-шолом'. "
            "Штани з лямками/підтяжками/високою спинкою -> 'Напівкомбінезон'. "
            "Подовжені куртки парки -> 'Парка'. "
            "Водонепроникні рукавиці з високою манжетою -> 'Краги'."
        )
    )

    age_group: List[Literal["Дітям", "Підліткам", "Дорослим"]] = Field(
        default_factory=list,
        description="Вікова категорія (може бути кілька при перехідних розмірах)"
    )

    color: Optional[Literal[
        "чорний", "темно-синій", "синій", "блакитний", "зелений", "лайм",
        "жовтий", "помаранчевий", "червоний", "бордовий", "рожевий", "фуксія",
        "фіолетовий", "ліловий", "бірюзовий", "м'ятний", "бежевий", "коричневий",
        "сірий", "білий", "морська хвиля"
    ]] = Field(default=None, description="Базовий уніфікований колір для фільтрації")

    insulation_type: Optional[Literal[
        "Синтетичний", "Пух і перо", "SoftShell", "Без утеплювача"
    ]] = Field(default=None, description="Вид утеплювача")

    temperature_range: Optional[Literal[
        "до +15°C", "до +10°C", "до +5°C", "до 0°C", "до -5°C", "до -10°C", "до -20°C", "до -30°C"
    ]] = Field(default=None, description="Температурний режим експлуатації")

    insulation_weight: Optional[Literal[
        "40г", "100г", "140г", "160г", "200г", "300г"
    ]] = Field(default=None, description="Точна щільність утеплювача в грамах")

    season: Optional[Literal[
        "Весна - Осінь", "Зима", "Літо", "Всесезон", "Весна - Осінь - Зима", "Весна - Літо - Осінь", "Демісезон"
    ]] = Field(default=None, description="Сезон експлуатації")

    # Storefront Technical Specifications Tab ('Characteristics' tab)
    attributes_ua: List[ProductAttributeLocalized] = Field(
        default_factory=list,
        description="Технічні характеристики українською (Склад, Водонепроникність, Догляд тощо)"
    )
    attributes_ru: List[ProductAttributeLocalized] = Field(
        default_factory=list,
        description="Технические характеристики на русском (Состав, Водонепроницаемость, Уход и т.д.)"
    )

    def to_ocfilter_dict(self, target_lang: str = "ru") -> Dict[str, List[str]]:
        """
        Converts the normalized taxonomy into an OCFilter-ready dictionary.
        Supports 'ru' (default for legacy stores) or 'ua'.
        """
        filters: Dict[str, List[str]] = {}

        if target_lang == "ua":
            if self.gender:
                filters["Стать"] = self.gender
            if self.product_type:
                filters["Тип"] = [self.product_type]
            if self.season:
                filters["Сезон"] = [self.season]
            if self.age_group:
                filters["Вік"] = self.age_group
            if self.color:
                filters["Колір"] = [self.color]
            if self.insulation_type:
                filters["Вид утеплювача"] = [self.insulation_type]
            if self.temperature_range:
                filters["Температурний режим"] = [self.temperature_range]
            if self.insulation_weight:
                filters["Кількість утеплювача"] = [self.insulation_weight]
        else:
            # Russian mappings for OpenCart OCFilter
            if self.gender:
                filters["Пол"] = [GENDER_MAP_UA_TO_RU.get(g, g) for g in self.gender]
            if self.product_type:
                filters["Тип"] = [PRODUCT_TYPE_MAP_UA_TO_RU.get(self.product_type, self.product_type)]
            if self.season:
                filters["Сезон"] = [SEASON_MAP_UA_TO_RU.get(self.season, self.season)]
            if self.age_group:
                filters["Возраст"] = [AGE_GROUP_MAP_UA_TO_RU.get(a, a) for a in self.age_group]
            if self.color:
                filters["Цвет"] = [COLOR_MAP_UA_TO_RU.get(self.color, self.color)]
            if self.insulation_type:
                filters["Вид утеплителя"] = [INSULATION_TYPE_MAP_UA_TO_RU.get(self.insulation_type, self.insulation_type)]
            if self.temperature_range:
                temp = self.temperature_range.replace("°C", "С")
                filters["Температурный режим"] = [temp]
            if self.insulation_weight:
                filters["Количество утеплителя"] = [self.insulation_weight]

        return filters


# ===========================================================================
# 3. AGENT 2 SCHEMA: Marketing & SEO Copy (Copywriter Agent)
# ===========================================================================
class LocalizedMarketingCopy(BaseModel):
    """
    Marketing text and SEO metadata generated by Agent 2 for a single language.
    Does NOT include technical attributes because Agent 1 already extracted them.
    """
    name: str = Field(description="Комерційна назва для вітрини ('Наименование')")
    meta_h1: str = Field(default="", description="HTML-тег H1 ('HTML-тег H1')")
    meta_title: str = Field(description="SEO meta title ('HTML-тег Title', до 70 символів)")
    meta_description: str = Field(description="SEO meta description ('Мета-тег Description', приблизно до 250 символів)")
    meta_keyword: str = Field(default="", description="Ключові слова через кому ('Мета-тег Keywords')")
    tag: str = Field(default="", description="Пошукові теги товару через кому ('Теги товара')")
    html_description: str = Field(description="Чистий HTML опис для ocStore 2.1.0.1 зі структурою блоків та компактним Schema.org JSON-LD")


class GeneratedDescriptions(BaseModel):
    """
    Output of Agent 2 (SEO & Copywriter Specialist).
    Runs at temperature=0.4 for natural, engaging e-commerce copy.
    """
    ua: LocalizedMarketingCopy
    ru: LocalizedMarketingCopy


# ===========================================================================
# 4. LANGGRAPH WORKFLOW STATE
# ===========================================================================
class ProductEnrichmentState(TypedDict):
    """
    Shared state container passed between LangGraph nodes:
    - START -> Agent 1 populates 'taxonomy'
    - Agent 2 reads 'product' + 'taxonomy' and populates 'descriptions'
    - Assembler combines 'taxonomy' + 'descriptions' into 'product.enriched'
    """
    product: ParentProduct
    taxonomy: Optional[NormalizedTaxonomy]
    descriptions: Optional[GeneratedDescriptions]