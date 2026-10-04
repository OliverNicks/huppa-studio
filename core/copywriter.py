import os
import json
import asyncio
from typing import List, Optional
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm

from core.models import ParentProduct, DualLanguageContent

load_dotenv()

SYSTEM_PROMPT = """Ти — провідний e-commerce копірайтер та SEO-спеціаліст для дитячого інтернет-магазину HUPPA в Україні.
Твоє завдання — згенерувати контент для товару ОДРАЗУ ДВОМА МОВАМИ: українською (ua) та російською (ru), а також сформувати словник фільтрів 'ocfilters'.

============================================================
1. МОВНА ЧИСТОТА ТА СТИЛЬ
============================================================
- У блоці 'ua' ВСІ тексти, назви характеристик ТА ЇХНІ ЗНАЧЕННЯ мають бути виключно літературною українською мовою!
- Якщо характеристики вказані російською ("Стать: Унисекс;Мальчик;Девочка" або "Утеплитель: 100% полиэстер"), ти ПОВИНЕН перекласти їх:
  * "Унісекс / Для хлопчиків / Для дівчаток"
  * "100% поліестер"
  * Одиниці виміру: "10 000 мм", "100 г/м²".
- У блоці 'ru' всі тексти та характеристики — чистою російською мовою.

============================================================
2. СТРУКТУРА ОПИСУ ТА ПОЛІВ (Вкладка 'Общие')
============================================================
1. name (Наименование):
   - UA: [Тип] [Бренд] [Модель] [код кольору] [колір в узгодженій формі]
     Приклад: "Штани для дітей HUPPA FREJA 21700010-00009 чорні"
   - RU: "Брюки для детей HUPPA FREJA 21700010-00009 черные"
   - Узгоджуйте прикметник кольору (штани — чорні/черные, куртка — чорна/черная, комбінезон — чорний/черный).

2. meta_h1 (HTML-тег H1):
   - Повинен збігатися з комерційною назвою `name` (наприклад, "Штани для дітей HUPPA FREJA 21700010-00009 чорні").

3. meta_title (HTML-тег Title):
   - Шаблон: "[Назва товару] — купити в інтернет-магазині HUPPA" (до 70 символів).

4. meta_description (Мета-тег Description):
   - Чіткий заклик до дії, ключові мембранні властивості, утеплювач, підтяжки, снігозахист (до 160 символів).

5. meta_keyword (Мета-тег Keywords) та tag (Теги товара):
   - 4-7 цільових пошукових запитів через кому (наприклад: "Huppa FREJA 21700010-00009, штани Huppa, дитячі штани Huppa, чорні штани Huppa, утеплені штани дитячі").

6. html_description (Опис товару):
   - Обов'язково формуй чистий семантичний HTML за такою структурою:
     <p><strong>[Головне речення з вигодою]</strong> — опис призначення моделі для активних прогулянок у прохолодну погоду, захисту від вітру та вологи.</p>
     <h3>Особливості моделі</h3>
     <ul>
       <li><strong>Артикул:</strong> [Артикул або код моделі]</li>
       <li><strong>Модель:</strong> [Назва моделі]</li>
       <li><strong>Колір:</strong> [Колір]</li>
       <li><strong>Підтяжки / Регулювання:</strong> [Опис фурнітури / талії]</li>
       <li><strong>Снігозахист:</strong> [Наявність внутрішніх спідниць/манжетів]</li>
       <li><strong>Безпека:</strong> світловідбивні елементи</li>
     </ul>
     <h3>Матеріали та утеплення</h3>
     <p><strong>Утеплювач:</strong> [Точна назва і щільність утеплювача, наприклад: HuppaTherm 100 г/м² (100% поліестер)].</p>
     <p>[Коротке речення про терморегуляцію та свободу рухів].</p>

7. attributes (Характеристики для вкладки 'Атрибуты'):
   Сформуй стандартизований перелік:
   - "Пол" / "Стать": "Унісекс", "Для хлопчиків", "Для дівчаток" (RU: "Унисекс", "Мальчик", "Девочка")
   - "Сезон": "Зима", "Демісезон" або "Весна - Осінь - Зима"
   - "Возраст" / "Вік": наприклад, "від 13 років, підлітки та дорослі" або "3-6 років"
   - "Состав" / "Склад": "100% поліестер" (RU: "100% полиэстер")
   - "Уход" / "Догляд": "Ручне прання або делікатний режим 30-40°C без використання кондиціонерів"

============================================================
3. СЛОВНИК ФІЛЬТРІВ 'ocfilters' (Вкладка 'Опции фильтра')
============================================================
Сформуй словник `ocfilters`, де ключі та значення СТРОГО відповідають налаштованим значенням OCFilter магазину:
- "Пол": вибирай ТІЛЬКИ з ["Мальчик", "Девочка", "Мужчина", "Женщина"]. Якщо унісекс для дітей — вказуй ОБИДВА: ["Мальчик", "Девочка"].
- "Тип": вибирай ТІЛЬКИ з ["Штаны", "Куртка", "Комбинезон", "Полукомбинезон", "Парка", "Пальто", "Шапка", "Шапка-шлем", "Варежки", "Перчатки", "Манишка", "Флисовый комбинезон"].
- "Возраст": вибирай ТІЛЬКИ з ["Детям", "Подросткам", "Взрослым"]. Якщо перехідний розмір — можна кілька.
- "Цвет": вибирай базовий колір із списку ["чёрный", "тёмно-синий", "синий", "зеленый", "жёлтый", "розовый", "серый", "красный", "белый", "фиолетовый", "бежевый"].
- "Вид утеплителя": вибирай ТІЛЬКИ з ["Синтетический", "Пух и перо", "SoftShell", "Без утеплителя"].
- "Температурный режим": вибирай ТІЛЬКИ з ["до +15С", "до +10С", "до +5С", "до 0С", "до -5С", "до -10С", "до -20С", "до -30С"].
- "Количество утеплителя": вибирай ТІЛЬКИ з ["40г", "100г", "140г", "160г", "200г", "300г"].
"""


class AsyncProductCopywriter:
    def __init__(self, model_name: str = "gpt-4o-mini", max_concurrency: int = 5):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set in environment or .env file.")
        self.client = AsyncOpenAI(api_key=api_key)
        self.model_name = model_name
        self.semaphore = asyncio.Semaphore(max_concurrency)

    async def enrich_single_product(self, product: ParentProduct) -> ParentProduct:
        """Call LLM with structured outputs to generate dual-language copy and OCFilter data."""
        if product.enriched is not None:
            return product

        user_content = {
            "brand": product.brand,
            "model_name": product.model_name,
            "model_code": product.model_code,
            "color_code": product.color_code,
            "color_name": product.color_name,
            "parent_id": product.parent_id,
            "product_type": product.product_type,
            "raw_description": product.raw_description,
            "raw_specs": product.raw_specs,
            "available_sizes": [v.size for v in product.size_variants]
        }

        async with self.semaphore:
            for attempt in range(3):
                try:
                    response = await self.client.beta.chat.completions.parse(
                        model=self.model_name,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": json.dumps(user_content, ensure_ascii=False)}
                        ],
                        response_format=DualLanguageContent,
                        temperature=0.2
                    )
                    product.enriched = response.choices[0].message.parsed
                    return product
                except Exception as e:
                    if attempt == 2:
                        print(f"\n[!] Failed to enrich {product.parent_id}: {e}")
                        return product
                    await asyncio.sleep(2 ** attempt)

    async def enrich_catalog_batch(
        self, products: List[ParentProduct], max_items: Optional[int] = None
    ) -> List[ParentProduct]:
        """Process a batch of products concurrently with a progress bar."""
        target_products = products[:max_items] if max_items else products
        tasks = [self.enrich_single_product(p) for p in target_products]
        enriched_results = await tqdm.gather(*tasks, desc="Dual-Language AI Copywriting")

        if max_items and len(products) > max_items:
            return enriched_results + products[max_items:]
        return enriched_results