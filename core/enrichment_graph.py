import re
import os
import json
import asyncio
from typing import List, Optional
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END

from tqdm import tqdm

from core.models import ParentProduct, DualLanguageContent, LocalizedCopy
from core.category_matcher import resolve_categories_for_product
from core.graph_schemas import (
    ProductEnrichmentState,
    NormalizedTaxonomy,
    GeneratedDescriptions,
    SEASON_MAP_UA_TO_RU,
    GENDER_MAP_UA_TO_RU,
    PRODUCT_TYPE_MAP_UA_TO_RU,
    COLOR_MAP_UA_TO_RU,
    resolve_ocfilter_product_type,
    resolve_ocfilter_color,
)

load_dotenv()

# ===========================================================================
# 1. LLM CLIENT INITIALIZATION
# ===========================================================================
# Agent 1 (Analyst): temperature=0.0 for strict, deterministic fact extraction
analyst_llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.0
).with_structured_output(NormalizedTaxonomy)

# Agent 2 (Copywriter): temperature=0.1 for strict adherence to exact HTML styling and template
copywriter_llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.1
).with_structured_output(GeneratedDescriptions)


# ===========================================================================
# 2. AGENT 1: TAXONOMY & ATTRIBUTES SPECIALIST
# ===========================================================================
TAXONOMY_SYSTEM_PROMPT = """Ти — головний технічний аналітик товарних даних для офіційного інтернет-магазину дитячого одягу HUPPA в Україні (huppa.com.ua).
Твоє завдання — проаналізувати сирі дані постачальника (назва, опис, табличні характеристики) та суворо класифікувати товар.

ПРАВИЛА:
1. Вибирай значення для полів ТІЛЬКИ із дозволених значень (Literal). Якщо точних даних немає — залишай None або порожній список.

2. Правила вибору типу товару та усунення неоднозначностей (Disambiguation Rules для product_type):
   - Якщо виріб складається з двох окремих частин (куртка + штани або куртка + напівкомбінезон) — це завжди "Комплект".
   - Якщо товар призначений для немовлят (спальний мішок, конверт, кокон, закритий мішок з ручками або прорізами для автокрісла) — це "Конверт".
   - Якщо виріб повністю закриває шию і голову суцільно (шолом, балаклава) — це "Шапка-шолом", а НЕ просто "Шапка".
   - Якщо штани мають високу спинку/грудку та регульовані підтяжки/лямки — це "Напівкомбінезон". Звичайні штани на поясі без грудки — це "Штани".
   - Якщо комбінезон виконаний із флісу (піддіва/проміжний шар) — це "Флісовий комбінезон", на відміну від верхнього вуличного "Комбінезон".
   - Якщо це кофта, жакет або толстовка з флісу — це "Флісова кофта".
   - Якщо це флісові штани — це "Флісові штани". Загальний флісовий одяг без уточнення крою — "Фліс".
   - Якщо це подовжена куртка з капюшоном та характерним прямим або приталеним кроєм — це "Парка".
   - Якщо це класичне подовжене пальто або плащ — це "Пальто".
   - Якщо це непромокаючі рукавиці з мембранної тканини з високою манжетою та утяжкою — це "Краги". Звичайні трикотажні/вовняні рукавички з роздільними пальцями — це "Рукавиці".
   - Взуття/шкарпетки для немовлят без жорсткої підошви — це "Пінетки".
   - Манішка/комір/горловина — це "Манішка".
   - Дощовики класифікуй відповідно до форми: куртка-дощовик -> "Куртка", штани-дощовик -> "Штани" або "Напівкомбінезон", комплект-дощовик -> "Комплект".
   - Трикотаж: спідниці -> "Спідниця", сукні -> "Плаття", футболки -> "Футболка".

3. Таблиця відповідності сирих термінів постачальника (Supplier Keyword Crosswalk для product_type_hint):
   Орієнтуйся на сире поле 'product_type_hint' постачальника як на пряму вказівку за такими правилами:
   * "Комплект (куртка+брюки)", "Комплект (куртка+полукомбинезон)", "Комплект - Дождевик" -> "Комплект"
   * "Конверт - Спальный мешок", "Комбинезон - Спальный мешок", "Конверт" -> "Конверт"
   * "Шапка - Шлем" -> "Шапка-шолом"
   * "Шапка", "Повязка на голову", "Кепка", "Панама" -> "Шапка"
   * "Брюки - Полукомбинезон", "Полукомбинезон", "Брюки - Полукомбинезон - Дождевик" -> "Напівкомбінезон"
   * "Брюки", "Брюки - Дождевик", "Шорты" -> "Штани"
   * "Куртка - Парка", "Пальто - Плащ - Куртка - Парка" -> "Парка"
   * "Куртка", "Куртка - Дождевик", "Дождевик" -> "Куртка"
   * "Пальто - Плащ", "Пальто" -> "Пальто"
   * "Жакет - Кофта", "Жакет", "Джемпер", "Кардиган" -> "Флісова кофта"
   * "Флис", "Фліс" -> "Фліс" (або "Флісовий комбінезон" / "Флісова кофта" за описом)
   * "Перчатки", "Краги" -> "Краги"
   * "Варежки" -> "Рукавиці"
   * "Пинетки" -> "Пінетки"
   * "Манишка" -> "Манішка"
   * "Платье" -> "Плаття"
   * "Юбка" -> "Спідниця"
   * "Футболка" -> "Футболка"
   * "Жилет" -> "Куртка"

4. Стать (gender): Орієнтуйся на gender_hint з даних постачальника. Якщо товар для хлопчиків — обирай ["Хлопчик"], для дівчаток — ["Дівчинка"]. Якщо товар підходить і хлопчикам, і дівчаткам (унісекс / хлопчики та дівчатка) — обов'язково обирай ОБИДВА: ["Хлопчик", "Дівчинка"].
5. Сезон (season): Орієнтуйся на season_hint постачальника. Вибирай із дозволених ("Весна - Осінь", "Зима", "Літо", "Всесезон", "Демісезон").
6. Характеристики (attributes_ua / attributes_ru):
   Сформуй обов'язкові пари характеристик для вітрини двома мовами:
   - "Стать" / "Пол" ("Для хлопчиків", "Для дівчаток", "Унісекс")
   - "Сезон" / "Сезон" ("Зима", "Демісезон", "Весна - Осінь")
   - "Склад" / "Состав" (напр., "100% поліестер")
   - "Водонепроникність" / "Водонепроницаемость" (напр., "10 000 мм", якщо зазначено в описі або характеристиках)
   - "Повітропроникність" / "Воздухопроницаемость" (напр., "10 000 г/м²/24г", якщо зазначено)
   - "Утеплювач" / "Утеплитель" (напр., "HuppaTherm 100 г/м² (100% поліестер)")
   - "Догляд" / "Уход" ("Ручне прання до 40°C. Машинне прання 30-40°C.")
7. Не вигадуй вигаданих технологій. Використовуй лише факти з вхідних даних постачальника.
"""

async def taxonomy_agent_node(state: ProductEnrichmentState) -> dict:
    """Agent 1 node: extracts rigid taxonomy and technical attributes."""
    product = state["product"]

    payload = {
        "brand": product.brand,
        "model_name": product.model_name,
        "model_code": product.model_code,
        "color_code": product.color_code,
        "color_name": product.color_name,
        "gender_hint": product.gender,
        "season_hint": product.season,
        "product_type_hint": product.product_type,
        "raw_description": product.raw_description,
        "raw_specs": product.raw_specs,
        "available_sizes": [v.size for v in product.size_variants]
    }

    messages = [
        {"role": "system", "content": TAXONOMY_SYSTEM_PROMPT},
        {"role": "user", "content": f"Проаналізуй товар та структуруй дані:\n{json.dumps(payload, ensure_ascii=False)}"}
    ]

    taxonomy: NormalizedTaxonomy = await analyst_llm.ainvoke(messages)
    return {"taxonomy": taxonomy}


# ===========================================================================
# 3. AGENT 2: E-COMMERCE COPYWRITER & SEO SPECIALIST (ocStore 2.1.0.1 / HUPPA)
# ===========================================================================
COPYWRITER_SYSTEM_PROMPT = """Ти — професійний SEO-копірайтер та HTML-верстальник товарних сторінок офіційного інтернет-магазину HUPPA в Україні (huppa.com.ua).
Твоє завдання — на основі наданої інформації про товар створити унікальний SEO-оптимізований опис товару у вигляді готового HTML-коду для ocStore 2.1.0.1 ОДРАЗУ ДВОМА МОВАМИ: українською (ua) та російською (ru).

============================================================
1. МОВНІ ВЕРСІЇ
============================================================
- УКРАЇНСЬКА ВЕРСІЯ (ua): уся текстова інформація, заголовки, списки, характеристики та Schema.org — виключно чистою літературною українською мовою.
- РОСІЙСЬКА ВЕРСІЯ (ru): уся текстова інформація, заголовки, списки, характеристики та Schema.org — чистою російською мовою.
- Суворо заборонено змішувати українську та російську мови в межах однієї версії.

============================================================
2. СТРУКТУРА ПОЛІВ ТА МЕТАТЕГІВ (СУВОРО ЗА ЗРАЗКОМ)
============================================================
- НАЙВАЖЛИВІШЕ ПРАВИЛО ДЛЯ КОДУ ТОВАРУ:
  У ВСІХ випадках (name, meta_h1, meta_title, meta_description, meta_keyword, tag, та всередині опису товару) після назви бренду та моделі ЗАВЖДИ вказуй повний код товару РАЗОМ ІЗ кодом кольору через дефіс: [Бренд] [Модель] [Модель-Колір] (наприклад: "HUPPA ZIPPY 32130020-00020", а НЕ просто "32130020"). Код кольору обов'язково повинен містити всі 5 цифр із провідними нулями!

- name (Наименование) та meta_h1 (HTML-тег H1):
  * Формат: [Тип товару] для дітей (або для хлопчиків / для дівчаток) [Бренд] [Модель] [Код-Колір] [колір в узгодженій формі]
  * UA приклад: "Штани для дітей HUPPA FREJA 21700010-00009 чорні"
  * RU приклад: "Брюки для детей HUPPA FREJA 21700010-00009 черные"
  (ДУЖЕ ВАЖЛИВО: НЕ включай <h1> в HTML-код опису товару, оскільки H1 формується окремим полем в ocStore!)

- meta_title (HTML-тег Title):
  * Формат: [Тип товару] [Бренд] [Модель] [Артикул] [колір в узгодженій формі] [дитячі / для хлопчиків / для дівчаток]
  * НЕ додавай зайвих приписок на зразок "купити в інтернет-магазині"! Пиши чітко за формулою:
  * UA приклад: "Штани Huppa FREJA 21700010-00009 чорні дитячі"
  * RU приклад: "Брюки Huppa FREJA 21700010-00009 черные детские"

- meta_description (Мета-тег Description):
  * Формат: [Цільова група та тип товару] [Бренд] [Модель] [Артикул] [колір] кольору: мембранні характеристики [водонепроникність/паропроникність], утеплювач [Бренд та грамаж], [2-3 ключові особливості моделі].
  * UA приклад: "Дитячі штани Huppa FREJA 21700010-00009 чорного кольору: мембранні характеристики 10 000/10 000, утеплювач HUPPA TERM 100 г/м², регульовані підтяжки та снігозахист."
  * RU приклад: "Детские брюки Huppa FREJA 21700010-00009 черного цвета: мембранные характеристики 10 000/10 000, утеплитель HUPPA TERM 100 г/м², регулируемые подтяжки и снегозащита."

- meta_keyword (Мета-тег Keywords) та tag (Теги товара):
  * Формат: 5 релевантних пошукових фраз через кому:
    1. [Бренд] [Модель] [Артикул]
    2. [тип товару] [Бренд]
    3. дитячі [тип товару] [Бренд]
    4. [колір] [тип товару] [Бренд]
    5. утеплені [тип товару] дитячі
  * Значення в tag (Теги товара) повинно ТОЧНО збігатися з meta_keyword!
  * UA приклад: "Huppa FREJA 21700010-00009, штани Huppa, дитячі штани Huppa, чорні штани Huppa, утеплені штани дитячі"
  * RU приклад: "Huppa FREJA 21700010-00009, брюки Huppa, детские брюки Huppa, черные брюки Huppa, утепленные брюки детские"

============================================================
3. ТОЧНА СТРУКТУРА ТА СТИЛІ HTML-ОПИСУ (html_description)
============================================================
Суворо дотримуйся наступної структури блоків та inline-стилів:

1. Вступний абзац (назва на початку обов'язково виділена <strong>):
<p><strong>[Комерційна назва товару відповідною мовою]</strong> — [функціональний вступний опис на 2 речення про призначення, захист від вологи/вітру та комфорт].</p>

2. Особливості моделі (стилізований div із синьою рамкою зліва #6fa8dc):
UA:
<h2>Особливості моделі</h2>
<div style="padding:10px 12px;margin:8px 0;border-left:3px solid #6fa8dc;background:#f5f8fb;">
<ul>
<li><strong>Артикул:</strong> [Артикул моделі, наприклад: 21700010-00009]</li>
<li><strong>Модель:</strong> [Назва моделі, наприклад: FREJA]</li>
<li><strong>Колір:</strong> [Колір товару]</li>
<li><strong>Дизайн / Крій / Застібки:</strong> [наявні деталі крою, кишені, регулювання]</li>
<li><strong>Безпека:</strong> світловідбивні елементи</li>
</ul>
</div>
RU:
<h2>Особенности модели</h2>
<div style="padding:10px 12px;margin:8px 0;border-left:3px solid #6fa8dc;background:#f5f8fb;">
<ul>
<li><strong>Артикул:</strong> [Артикул модели]</li>
<li><strong>Модель:</strong> [Название модели]</li>
<li><strong>Цвет:</strong> [Цвет товара]</li>
<li><strong>Дизайн / Крой / Застежки:</strong> [детали кроя]</li>
<li><strong>Безопасность:</strong> светоотражающие элементы</li>
</ul>
</div>

3. Матеріали та утеплення (стилізований div із зеленою рамкою зліва #93c47d):
UA:
<h2>Матеріали та утеплення</h2>
<div style="padding:10px 12px;margin:8px 0;border-left:3px solid #93c47d;background:#f7fbf5;">
<p><strong>Утеплювач:</strong> [Назва та щільність утеплювача, наприклад: HuppaTherm 100 г/м² (100% поліестер)].</p>
<p>[Короткий опис комфорту утеплювача без зайвого об'єму та збереження тепла].</p>
</div>
RU:
<h2>Материалы и утепление</h2>
<div style="padding:10px 12px;margin:8px 0;border-left:3px solid #93c47d;background:#f7fbf5;">
<p><strong>Утеплитель:</strong> [Название и плотность утеплителя, например: HuppaTherm 100 г/м² (100% полиэстер)].</p>
<p>[Краткое описание комфорта утеплителя без лишнего объема].</p>
</div>

4. Технічні характеристики (стилізований div із сірими лініями #ddd зверху і знизу):
UA:
<h2>Технічні характеристики</h2>
<div style="padding:10px 12px;margin:8px 0;border-top:1px solid #ddd;border-bottom:1px solid #ddd;">
<p><strong>Водонепроникність:</strong> [значення, наприклад: 10 000 мм].</p>
<p><strong>Паропроникність:</strong> [значення, наприклад: 10 000 г/м²/24 год].</p>
<p><strong>Зносостійкість:</strong> [значення, наприклад: 60 000 циклів].</p>
<p><strong>Захист від вітру:</strong> вітронепроникний матеріал.</p>
</div>
RU:
<h2>Технические характеристики</h2>
<div style="padding:10px 12px;margin:8px 0;border-top:1px solid #ddd;border-bottom:1px solid #ddd;">
<p><strong>Водонепроницаемость:</strong> [значение, например: 10 000 мм].</p>
<p><strong>Паропроницаемость:</strong> [значение, например: 10 000 г/м²/24 ч].</p>
<p><strong>Износостойкость:</strong> [значение, например: 60 000 циклов].</p>
<p><strong>Защита от ветра:</strong> ветронепроницаемый материал.</p>
</div>

5. Переваги (стилізований div із сірими лініями #ddd зверху і знизу):
UA:
<h2>Переваги [Бренд Модель]</h2>
<div style="padding:10px 12px;margin:8px 0;border-top:1px solid #ddd;border-bottom:1px solid #ddd;">
<ul>
<li>[перевага 1 із крапкою з комою];</li>
<li>[перевага 2 із крапкою з комою];</li>
<li>[перевага 3 із крапкою з комою];</li>
<li>[перевага 4 із крапкою з комою];</li>
<li>[перевага 5 із крапкою в кінці].</li>
</ul>
</div>
RU:
<h2>Преимущества [Бренд Модель]</h2>
<div style="padding:10px 12px;margin:8px 0;border-top:1px solid #ddd;border-bottom:1px solid #ddd;">
<ul>
<li>[преимущество 1 с точкой с запятой];</li>
<li>[преимущество 2 с точкой с запятой];</li>
<li>[преимущество 3 с точкой с запятой];</li>
<li>[преимущество 4 с точкой с запятой];</li>
<li>[преимущество 5 с точкой в конце].</li>
</ul>
</div>

6. Догляд:
UA:
<h2>Догляд</h2>
<p>Ручне прання допускається при температурі до 40°C. Машинне прання — при температурі 30–40°C. Для збереження функціональних властивостей виробу дотримуйтеся позначень на етикетці.</p>
RU:
<h2>Уход</h2>
<p>Ручная стирка допускается при температуре до 40°C. Машинная стирка — при температуре 30–40°C. Для сохранения функциональных свойств изделия следуйте указаниям на этикетке.</p>

7. Чому варто купити в офіційному інтернет-магазині HUPPA?:
UA:
<h2>Чому варто купити в офіційному інтернет-магазині HUPPA?</h2>
<ul>
<li>100% оригінальна продукція бренду HUPPA (Естонія);</li>
<li>професійна консультація та допомога у підборі розміру;</li>
<li>швидка доставка замовлень по всій Україні;</li>
<li>офіційна гарантія якості від виробника;</li>
<li>прості та зручні умови обміну та повернення.</li>
</ul>
RU:
<h2>Почему стоит купить в официальном интернет-магазине HUPPA?</h2>
<ul>
<li>100% оригинальная продукция бренда HUPPA (Эстония);</li>
<li>профессиональная консультация и помощь в подборе размера;</li>
<li>быстрая доставка заказов по всей Украине;</li>
<li>официальная гарантия качества от производителя;</li>
<li>простые и удобные условия обмена и возврата.</li>
</ul>

8. Schema.org JSON-LD (в самому кінці опису):
UA:
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "[Комерційна назва українською]",
  "description": "[Короткий вступний опис українською]",
  "sku": "[Артикул товару]",
  "brand": {
    "@type": "Brand",
    "name": "HUPPA"
  },
  "color": "[Колір українською]"
}
</script>
RU:
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "[Коммерческое название на русском]",
  "description": "[Краткое вводное описание на русском]",
  "sku": "[Артикул товара]",
  "brand": {
    "@type": "Brand",
    "name": "HUPPA"
  },
  "color": "[Цвет на русском]"
}
</script>
"""

async def copywriter_agent_node(state: ProductEnrichmentState) -> dict:
    """Agent 2 node: writes bilingual marketing copy and SEO tags based on verified taxonomy and prompt_description.docx rules."""
    product = state["product"]
    taxonomy = state["taxonomy"]

    clean_model = product.model_code.strip() if product.model_code else product.parent_id.split('_')[0]
    clean_color = product.color_code.strip() if product.color_code else (product.parent_id.split('_')[1] if '_' in product.parent_id else "")
    color_padded = clean_color.zfill(5) if clean_color.isdigit() and len(clean_color) < 5 else clean_color
    product_code = f"{clean_model}-{color_padded}" if color_padded else clean_model

    payload = {
        "brand": product.brand,
        "model_name": product.model_name,
        "model_code": clean_model,
        "color_code": color_padded,
        "product_code": product_code,
        "article": product_code,
        "color_name": product.color_name,
        "base_price": product.base_price,
        "special_price": product.special_price,
        "total_stock": product.total_stock,
        "is_in_stock": product.is_in_stock,
        "available_sizes": product.available_sizes,
        "verified_taxonomy": taxonomy.model_dump(exclude={"attributes_ua", "attributes_ru"}) if taxonomy else {},
        "raw_description": product.raw_description,
        "raw_specs": product.raw_specs,
    }

    messages = [
        {"role": "system", "content": COPYWRITER_SYSTEM_PROMPT},
        {"role": "user", "content": f"Створи SEO-опис та метатеги для товару відповідно до правил ocStore для офіційного магазину HUPPA (huppa.com.ua). ЗАВЖДИ вказуй повний код товару з кодом кольору '{product_code}' (наприклад: '{product.brand} {product.model_name} {product_code}'):\n{json.dumps(payload, ensure_ascii=False)}"}
    ]

    descriptions: GeneratedDescriptions = await copywriter_llm.ainvoke(messages)
    return {"descriptions": descriptions}


# ===========================================================================
# 4. ASSEMBLER NODE (DETERMINISTIC CODE)
# ===========================================================================
def assemble_enriched_product_node(state: ProductEnrichmentState) -> dict:
    """
    Assembler node: merges Agent 1's technical attributes and OCFilter facets
    with Agent 2's marketing copy into DualLanguageContent, setting product.enriched.
    """
    product = state["product"]
    taxonomy = state["taxonomy"]
    descriptions = state["descriptions"]

    clean_model = product.model_code.strip() if product.model_code else product.parent_id.split('_')[0]
    clean_color = product.color_code.strip() if product.color_code else (product.parent_id.split('_')[1] if '_' in product.parent_id else "")
    color_padded = clean_color.zfill(5) if clean_color.isdigit() and len(clean_color) < 5 else clean_color
    product_code = f"{clean_model}-{color_padded}" if color_padded else clean_model

    def _enforce_full_code(text: str) -> str:
        if not text or not clean_model or not color_padded:
            return text
        pattern = rf"\b{re.escape(clean_model)}\b(?!-{re.escape(color_padded)})"
        return re.sub(pattern, product_code, text)

    # 1. Build Ukrainian LocalizedCopy
    ua_copy = LocalizedCopy(
        name=_enforce_full_code(descriptions.ua.name),
        meta_h1=_enforce_full_code(descriptions.ua.meta_h1 or descriptions.ua.name),
        meta_title=_enforce_full_code(descriptions.ua.meta_title),
        meta_description=_enforce_full_code(descriptions.ua.meta_description),
        meta_keyword=descriptions.ua.meta_keyword,
        tag=descriptions.ua.tag,
        html_description=_enforce_full_code(descriptions.ua.html_description),
        attributes=taxonomy.attributes_ua if taxonomy else []
    )

    # 2. Build Russian LocalizedCopy
    ru_copy = LocalizedCopy(
        name=_enforce_full_code(descriptions.ru.name),
        meta_h1=_enforce_full_code(descriptions.ru.meta_h1 or descriptions.ru.name),
        meta_title=_enforce_full_code(descriptions.ru.meta_title),
        meta_description=_enforce_full_code(descriptions.ru.meta_description),
        meta_keyword=descriptions.ru.meta_keyword,
        tag=descriptions.ru.tag,
        html_description=_enforce_full_code(descriptions.ru.html_description),
        attributes=taxonomy.attributes_ru if taxonomy else []
    )

    # 3. Generate OCFilter dictionary (defaults to 'ru' for OpenCart database compatibility)
    ocfilters = taxonomy.to_ocfilter_dict(target_lang="ru") if taxonomy else {}

    # Determine effective gender: parse product.gender first as deterministic source of truth
    supplier_genders = []
    if product.gender:
        raw_g = str(product.gender).lower()
        if "хлопч" in raw_g or "мальч" in raw_g:
            supplier_genders.append("Хлопчик")
        if "дівчат" in raw_g or "девоч" in raw_g:
            supplier_genders.append("Дівчинка")
        if "чоловік" in raw_g or "мужчин" in raw_g:
            supplier_genders.append("Чоловікам")
        if "жінок" in raw_g or "женщин" in raw_g:
            supplier_genders.append("Жінкам")

    effective_genders = supplier_genders if supplier_genders else (taxonomy.gender if (taxonomy and taxonomy.gender) else [])

    # Ensure 'Gender' (DB: 'Пол') is populated in OCFilter
    if effective_genders:
        ocfilters["Пол"] = [GENDER_MAP_UA_TO_RU.get(g, g) for g in effective_genders]

    # Determine effective Season (DB: 'Сезон')
    raw_season_str = str(product.season or "").lower()
    normalized_season = None

    if "зим" in raw_season_str or "winter" in raw_season_str:
        normalized_season = "Зима"
    elif any(k in raw_season_str for k in ["дем", "весна", "осінь", "осень", "spring", "autumn"]):
        normalized_season = "Демисезон"
    elif "літ" in raw_season_str or "лет" in raw_season_str or "summer" in raw_season_str:
        normalized_season = "Лето"
    elif taxonomy and taxonomy.season:
        mapped = SEASON_MAP_UA_TO_RU.get(taxonomy.season, taxonomy.season)
        if mapped in ["Весна - Осень", "Весна - Осень - Зима", "Весна - Лето - Осень"]:
            normalized_season = "Демисезон"
        else:
            normalized_season = mapped
    else:
        for attr in (taxonomy.attributes_ru if taxonomy else []):
            if attr.name.lower() == "сезон" and attr.value:
                val_l = attr.value.lower()
                if "зим" in val_l:
                    normalized_season = "Зима"
                elif any(k in val_l for k in ["дем", "весна", "осен"]):
                    normalized_season = "Демисезон"
                elif "лет" in val_l:
                    normalized_season = "Лето"
                else:
                    normalized_season = attr.value
                break

    if normalized_season:
        ocfilters["Сезон"] = [normalized_season]

    # Attach only available in-stock sizes to OCFilter under 'Size' (DB: 'Размер')
    if product.size_variants:
        in_stock_sizes = [str(v.size).strip() for v in product.size_variants if v.size and v.stock > 0]
        if in_stock_sizes:
            ocfilters["Размер"] = in_stock_sizes

    # Determine effective Product Type for OCFilter (DB: 'Тип')
    # Step 1: Deterministic resolution from raw Excel (ParentProduct.product_type)
    effective_type = resolve_ocfilter_product_type(product.product_type)

    # Step 2: Fallback to AI NormalizedTaxonomy if raw Excel was empty/unrecognized
    if not effective_type and taxonomy and taxonomy.product_type:
        effective_type = PRODUCT_TYPE_MAP_UA_TO_RU.get(taxonomy.product_type, taxonomy.product_type)

    if effective_type:
        ocfilters["Тип"] = [effective_type]

    # Determine effective Color for OCFilter (DB: 'Цвет')
    # Step 1: Deterministic resolution from raw Excel (product.color_name)
    effective_color = resolve_ocfilter_color(product.color_name)

    # Step 2: Fallback to AI NormalizedTaxonomy
    if not effective_color and taxonomy and taxonomy.color:
        effective_color = COLOR_MAP_UA_TO_RU.get(taxonomy.color, taxonomy.color)

    if effective_color:
        ocfilters["Цвет"] = [effective_color]

    # 4. Attach as single source of truth
    product.enriched = DualLanguageContent(
        ua=ua_copy,
        ru=ru_copy,
        ocfilters=ocfilters
    )

    # 5. Automatically resolve main category and parent/sub categories
    # Step 1: Decide category based on raw supplier type (ParentProduct.product_type)
    main_cat, cat_ids = resolve_categories_for_product(
        product,
        product_type=product.product_type,
        genders=effective_genders
    )

    # Step 2: Fallback to AI NormalizedTaxonomy if unresolved
    if not main_cat and taxonomy and taxonomy.product_type:
        fallback_main, fallback_cats = resolve_categories_for_product(
            product,
            product_type=taxonomy.product_type,
            genders=effective_genders
        )
        if fallback_main:
            main_cat, cat_ids = fallback_main, fallback_cats

    product.main_category_id = main_cat
    product.category_ids = cat_ids

    return {"product": product}


# ===========================================================================
# 5. WORKFLOW GRAPH COMPILATION
# ===========================================================================
workflow = StateGraph(ProductEnrichmentState)

workflow.add_node("taxonomy_agent", taxonomy_agent_node)
workflow.add_node("copywriter_agent", copywriter_agent_node)
workflow.add_node("assembler", assemble_enriched_product_node)

workflow.add_edge(START, "taxonomy_agent")
workflow.add_edge("taxonomy_agent", "copywriter_agent")
workflow.add_edge("copywriter_agent", "assembler")
workflow.add_edge("assembler", END)

enrichment_app = workflow.compile()


# ===========================================================================
# 6. PIPELINE RUNNERS & BATCH EXECUTION
# ===========================================================================
async def enrich_single_product_graph(product: ParentProduct) -> ParentProduct:
    """Run a single product through the double-agent workflow."""
    if product.enriched is not None:
        return product

    initial_state: ProductEnrichmentState = {
        "product": product,
        "taxonomy": None,
        "descriptions": None
    }

    final_state = await enrichment_app.ainvoke(initial_state)
    return final_state["product"]


async def enrich_catalog_batch_graph(
    products: List[ParentProduct],
    max_concurrency: int = 5,
    max_items: Optional[int] = None
) -> List[ParentProduct]:
    """
    Concurrently enrich a list of ParentProducts through the LangGraph workflow
    with semaphore-based rate limiting and a progress bar.
    """
    target_products = products[:max_items] if max_items else products
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _safe_enrich(p: ParentProduct) -> ParentProduct:
        async with semaphore:
            for attempt in range(3):
                try:
                    return await enrich_single_product_graph(p)
                except Exception as e:
                    if attempt == 2:
                        print(f"\n[!] Failed to enrich {p.parent_id}: {e}")
                        return p
                    await asyncio.sleep(2 ** attempt)

    tasks = [_safe_enrich(p) for p in target_products]
    enriched_results = await tqdm.gather(*tasks, desc="Double-Agent LangGraph Enrichment")

    if max_items and len(products) > max_items:
        return enriched_results + products[max_items:]
    return enriched_results