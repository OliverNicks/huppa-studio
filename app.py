"""
Huppa.com.ua — OpenCart Management Studio (Streamlit Dashboard)
==============================================================
An intuitive local web dashboard for managing the Huppa OpenCart catalog:
- Drag-and-drop supplier Excel files
- Intelligent Delta Sync (generates SQL ONLY for items with actual changes)
- Real-time preview of detected changes (price, promos, stock, sizes)
- Automated AI enrichment for new products
- Direct database synchronization or one-click SQL download
- Image verification & pipeline controls
"""
import sys
import os
import json
import asyncio
from pathlib import Path
from datetime import datetime
import pandas as pd
import streamlit as st
from dotenv import load_dotenv, set_key
from typing import List

# Configure page layout
st.set_page_config(
    page_title="Huppa OpenCart Studio",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Workspace paths
WORKSPACE_DIR = Path(__file__).resolve().parent
DATA_DIR = WORKSPACE_DIR / "data"
OUTPUT_DIR = WORKSPACE_DIR / "output"
CACHE_FILE = DATA_DIR / "enriched_cache.jsonl"
IMAGES_DIR = WORKSPACE_DIR / "opencart_images"
ENV_FILE = WORKSPACE_DIR / ".env"

DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Load environment configuration
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)

# Import internal modules
try:
    from adapters.registry import registry
    from core.aggregator import aggregate_canonical_df
    from core.models import ParentProduct
    from core.image_resolver import OpenCartImageResolver
    from sync_weekly import (
        load_cached_catalog,
        detect_product_changes,
        generate_weekly_sync_sql,
        update_cache_snapshots,
    )
    from run_batch_pipeline import enrich_with_retry, EnrichmentCacheManager, OpenCartSQLExporter
    from core.sftp_auditor import (
        MirohostSFTPClient,
        audit_products_against_remote,
        AuditSummary,
    )
    from core.db_sync_executor import (
        execute_sql_migration,
        test_db_connection,
    )
    from core.photo_uploader import (
        DirectPhotoUploader,
        ImageUploadTask,
        link_uploaded_images_in_opencart_db,
    )
    from core.cache_backup import (
        create_cache_backup,
        list_cache_backups,
        restore_cache_backup,
    )
except Exception as e:
    st.error(f"Помилка завантаження модулів бекенду: {e}")


# ==============================================================================
# Helper Functions
# ==============================================================================
def run_weekly_analysis(catalog_path: Path):
    """
    Parses Excel, compares with baseline cache, and detects
    ONLY products with real changes (price, promo, stock, sizes).
    """
    cached_catalog = load_cached_catalog(CACHE_FILE)
    df = registry.load_and_normalize(str(catalog_path))
    fresh_products = aggregate_canonical_df(df)

    fresh_dict = {p.parent_id: p for p in fresh_products}
    changed = []
    unchanged = []
    new_prods = []

    for p in fresh_products:
        if p.parent_id in cached_catalog:
            cached_p = cached_catalog[p.parent_id]
            has_changed, change_list = detect_product_changes(fresh=p, cached=cached_p)
            if has_changed:
                changed.append((p, change_list))
            else:
                unchanged.append(p)
        else:
            new_prods.append(p)

    # Products in cache with stock > 0 that disappeared from fresh supplier sheet
    discontinued = [
        f"{cached_prod.model_code}-{cached_prod.color_code}"
        for parent_id, cached_prod in cached_catalog.items()
        if parent_id not in fresh_dict and cached_prod.total_stock > 0
    ]

    return {
        "df_raw": df,
        "fresh_products": fresh_products,
        "changed": changed,
        "unchanged": unchanged,
        "new": new_prods,
        "discontinued": discontinued,
        "cached_count": len(cached_catalog)
    }


async def enrich_new_products_async(new_products, concurrency=5, progress_bar=None, status_text=None):
    """Enriches new products using the paced AI graph with real-time UI progress updates."""
    cache_mgr = EnrichmentCacheManager(CACHE_FILE)
    sem = asyncio.Semaphore(concurrency)
    resolver = OpenCartImageResolver(images_dir=str(IMAGES_DIR), opencart_prefix="catalog/product/")
    for p in new_products:
        p.local_image_paths = resolver.resolve_for_product(p)

    tasks = [enrich_with_retry(p, sem, cache_mgr) for p in new_products]
    completed = []
    total = len(new_products)
    done_count = 0

    for fut in asyncio.as_completed(tasks):
        res = await fut
        completed.append(res)
        done_count += 1
        if progress_bar is not None and total > 0:
            progress_bar.progress(done_count / total)
        if status_text is not None:
            status_text.caption(f"✨ AI-збагачення: **{done_count}/{total}** | {res.model_code}-{res.color_code} ({res.model_name})")

    return [p for p in completed if p.enriched is not None]


# ==============================================================================
# Sidebar Navigation & Settings
# ==============================================================================
with st.sidebar:
    st.title("🛍️ Huppa Studio")
    st.caption("Керування каталогом **huppa.com.ua**")
    st.divider()

    menu = st.radio(
        "Навігація:",
        [
            "🔄 Щотижнева синхронізація (Delta)",
            "📸 Аудит зображень",
            "⚙️ Налаштування та База"
        ]
    )

    st.divider()
    # Cache status widget
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cached_count = sum(1 for line in f if line.strip())
        st.success(f"Кеш бази: **{cached_count:,}** карток")
        try:
            b_list = list_cache_backups()
            st.caption(f"📦 Резервних копій: **{len(b_list)} / 10**")
        except Exception:
            pass
    else:
        st.warning("Кеш товарів не знайдено.")

    # Status of photos
    if IMAGES_DIR.exists():
        photo_count = len(list(IMAGES_DIR.glob("*.jpg")) + list(IMAGES_DIR.glob("*.png")))
        st.info(f"Локальних фото: **{photo_count:,}** шт.")


# ==============================================================================
# TAB 1: Weekly Delta Synchronization (Delta Sync)
# ==============================================================================
if menu == "🔄 Щотижнева синхронізація (Delta)":
    st.header("🔄 Розумна Delta-синхронізація")
    st.write(
        "Завантажте свіжий щотижневий Excel від постачальника. "
        "Додаток порівняє ціни, залишки та розміри з попереднім станом і згенерує "
        "запити **виключно для тих товарів, які дійсно змінилися**."
    )

    # Persistent session state for uploaded catalog
    if "weekly_catalog_file_name" not in st.session_state:
        st.session_state.weekly_catalog_file_name = None
    if "weekly_catalog_path" not in st.session_state:
        st.session_state.weekly_catalog_path = None

    uploaded_file = st.file_uploader(
        "Оберіть або перетягніть Excel-файл постачальника (.xlsx)",
        type=["xlsx", "xls"],
        key="weekly_excel_uploader"
    )

    if uploaded_file is not None:
        saved_file_name = st.session_state.get("weekly_catalog_file_name")
        if saved_file_name != uploaded_file.name:
            target_path = DATA_DIR / f"temp_{uploaded_file.name}"
            with open(target_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.session_state.weekly_catalog_file_name = uploaded_file.name
            st.session_state.weekly_catalog_path = target_path
            # Reset previous analysis when a brand-new file is uploaded
            st.session_state.pop("analysis_data", None)
            st.session_state.pop("ready_sql_path", None)

    active_file_name = st.session_state.get("weekly_catalog_file_name")
    active_catalog_path = st.session_state.get("weekly_catalog_path")
    has_active_file = (
        active_catalog_path is not None
        and Path(active_catalog_path).exists()
    )

    if has_active_file:
        col_status, col_clear = st.columns([4, 1])
        with col_status:
            st.success(f"Активний файл прайсу: **{active_file_name}**")
        with col_clear:
            if st.button("🗑️ Очистити файл", help="Видалити поточний файл із пам'яті та скинути результати"):
                st.session_state.pop("weekly_catalog_file_name", None)
                st.session_state.pop("weekly_catalog_path", None)
                st.session_state.pop("analysis_data", None)
                st.session_state.pop("ready_sql_path", None)
                st.session_state.pop("weekly_excel_uploader", None)
                st.rerun()
    else:
        st.info("👆 Будь ласка, завантажте або перетягніть файл прайсу вище, щоб активувати аналіз.")

    is_disabled = not has_active_file

    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        analyze_clicked = st.button(
            "📊 Проаналізувати зміни",
            use_container_width=True,
            type="primary",
            disabled=is_disabled,
            help="Завантажте файл вище для активації" if is_disabled else "Розпочати аналіз змін"
        )

    if has_active_file and (analyze_clicked or "analysis_data" in st.session_state):
        if analyze_clicked:
            with st.spinner("Аналізуємо прайс та шукаємо реальні зміни..."):
                st.session_state.analysis_data = run_weekly_analysis(active_catalog_path)

        data = st.session_state.analysis_data

        # Metrics Row - Intelligent Delta Summary
        m1, m2, m3, m4, m5 = st.columns(5)
        with m1:
            st.metric("Всього у прайсі", f"{len(data['fresh_products'])}", help="Унікальних комбінацій Модель+Колір")
        with m2:
            st.metric("Реально змінилося ⚡", f"{len(data['changed'])}", delta="Йдуть у SQL", delta_color="normal")
        with m3:
            st.metric("Без змін (Skip) ⏸️", f"{len(data['unchanged'])}", delta="Пропущено")
        with m4:
            st.metric("Зникли з прайсу ❌", f"{len(data['discontinued'])}", delta="В stock = 0", delta_color="inverse")
        with m5:
            st.metric("Нових моделей ✨", f"{len(data['new'])}", delta="Потребують AI")

        # Tabs for details
        t1, t2, t3, t4 = st.tabs([
            "⚡ Список виявлених змін",
            "🏷️ Товари на акції",
            "❌ Закінчились на складі",
            "✨ Новинки в прайсі"
        ])

        with t1:
            if data['changed']:
                changed_table = [
                    {
                        "Код товару": f"{p.model_code}-{p.color_code}",
                        "Модель": p.model_name,
                        "Колір": p.color_name,
                        "Ціна, грн": p.base_price,
                        "Залишок": p.total_stock,
                        "Виявлені зміни": " • ".join(chg)
                    }
                    for p, chg in data['changed']
                ]
                st.dataframe(pd.DataFrame(changed_table), use_container_width=True)
            else:
                st.success("🎉 Жодних змін у цінах або залишках не виявлено! База на сайті повністю актуальна.")

        with t2:
            sale_items = [
                {
                    "Код товару": f"{p.model_code}-{p.color_code}",
                    "Модель": p.model_name,
                    "Колір": p.color_name,
                    "Базова ціна, грн": p.base_price,
                    "Акційна ціна, грн": p.special_price,
                    "Знижка %": f"{round((1 - p.special_price / p.base_price) * 100)}%" if p.base_price else "0%",
                    "Залишок": p.total_stock
                }
                for p in data['fresh_products']
                if p.special_price and 0 < p.special_price < p.base_price
            ]
            if sale_items:
                st.dataframe(pd.DataFrame(sale_items), use_container_width=True)
            else:
                st.info("Акційних товарів не виявлено.")

        with t3:
            out_items = [
                {
                    "Код товару": f"{p.model_code}-{p.color_code}",
                    "Модель": p.model_name,
                    "Колір": p.color_name,
                    "Ціна, грн": p.base_price,
                    "Залишок": p.total_stock
                }
                for p in data['fresh_products']
                if p.total_stock <= 0
            ]
            if out_items:
                st.dataframe(pd.DataFrame(out_items), use_container_width=True)
            else:
                st.success("Всі товари в прайсі мають залишок більше нуля!")

        with t4:
            if data['new']:
                new_table = [
                    {
                        "Артикул": np.parent_id,
                        "Модель": np.model_name,
                        "Колір": np.color_name,
                        "Тип товару": np.product_type,
                        "Ціна": np.base_price,
                        "Залишок": np.total_stock
                    }
                    for np in data['new']
                ]
                st.dataframe(pd.DataFrame(new_table), use_container_width=True)
            else:
                st.info("Нових товарів немає. Всі моделі вже присутні в базі.")

        st.divider()

        # Actions section
        st.subheader("⚙️ Застосування оновлення")
        auto_enrich_new = False
        if data['new']:
            auto_enrich_new = st.checkbox(
                f"✨ Автоматично збагатити {len(data['new'])} нових моделей через OpenAI та додати їх до імпорту",
                value=True
            )

        col_act1, col_act2 = st.columns([1, 1])

        # Current DB settings
        cur_db_h = os.getenv("DB_HOST", "ez1036.mirohost.net")
        cur_db_u = os.getenv("DB_USER", "u_huppaqnk")
        cur_db_p = os.getenv("DB_PASS", "pB3SpMDnhduz")
        cur_db_n = os.getenv("DB_NAME", "huppaqnk")
        cur_db_port = int(os.getenv("DB_PORT", "3306"))
        db_is_configured = bool(cur_db_u and cur_db_p and cur_db_n)

        with col_act1:
            total_to_update = len(data['changed']) + len(data['discontinued']) + (len(data['new']) if auto_enrich_new else 0)
            btn_gen_label = f"💾 Тільки згенерувати SQL ({total_to_update} операцій)"
            gen_clicked = st.button(btn_gen_label, use_container_width=True)

        with col_act2:
            btn_upload_label = f"🚀 Одразу оновити сайт ({total_to_update} операцій на huppa.com.ua)"
            direct_upload_clicked = st.button(
                btn_upload_label,
                type="primary",
                use_container_width=True,
                help="Сформує Delta-запити та миттєво виконає їх у базі даних OpenCart на Mirohost"
            )

        if "show_quick_db_setup" not in st.session_state:
            st.session_state.show_quick_db_setup = False

        if direct_upload_clicked and not db_is_configured:
            st.session_state.show_quick_db_setup = True

        if st.session_state.show_quick_db_setup and not db_is_configured:
            st.warning("⚠️ Для автоматичного завантаження в базу потрібно вказати пароль та назву бази даних MySQL. Введіть їх нижче або збережіть у вкладці '⚙️ Налаштування та База'.")
            with st.expander("🔑 Швидке налаштування бази даних MySQL (Mirohost)", expanded=True):
                with st.form("quick_db_form"):
                    q_col1, q_col2 = st.columns(2)
                    with q_col1:
                        q_db_h = st.text_input("MySQL Хост:", value=cur_db_h)
                        q_db_n = st.text_input("Назва бази даних:", value=cur_db_n, placeholder="huppar_opencart")
                    with q_col2:
                        q_db_u = st.text_input("Користувач бази:", value=cur_db_u)
                        q_db_p = st.text_input("Пароль бази:", value=cur_db_p, type="password")

                    btn_c1, btn_c2 = st.columns([2, 1])
                    with btn_c1:
                        save_clicked = st.form_submit_button("💾 Зберегти реквізити бази в .env", type="primary", use_container_width=True)
                    with btn_c2:
                        cancel_clicked = st.form_submit_button("Скасувати", use_container_width=True)

                    if save_clicked:
                        set_key(str(ENV_FILE), "DB_HOST", q_db_h.strip())
                        set_key(str(ENV_FILE), "DB_NAME", q_db_n.strip())
                        set_key(str(ENV_FILE), "DB_USER", q_db_u.strip())
                        set_key(str(ENV_FILE), "DB_PASS", q_db_p.strip())
                        os.environ["DB_HOST"] = q_db_h.strip()
                        os.environ["DB_NAME"] = q_db_n.strip()
                        os.environ["DB_USER"] = q_db_u.strip()
                        os.environ["DB_PASS"] = q_db_p.strip()
                        st.session_state.show_quick_db_setup = False
                        st.success("✅ Реквізити збережено! Тепер натисніть кнопку '🚀 Одразу оновити сайт'.")
                        st.rerun()
                    elif cancel_clicked:
                        st.session_state.show_quick_db_setup = False
                        st.rerun()

        if gen_clicked or (direct_upload_clicked and db_is_configured):
            today_str = datetime.now().strftime("%Y_%m_%d")
            output_sql_path = OUTPUT_DIR / f"weekly_sync_{today_str}.sql"

            # Handle new products enrichment if checked
            enriched_new = []
            if auto_enrich_new and data['new']:
                st.info(f"✨ Запуск автоматичного AI-збагачення для **{len(data['new'])}** нових моделей...")
                prog_bar = st.progress(0.0)
                stat_text = st.empty()
                enriched_new = asyncio.run(
                    enrich_new_products_async(
                        data['new'],
                        concurrency=5,
                        progress_bar=prog_bar,
                        status_text=stat_text
                    )
                )
                prog_bar.empty()
                stat_text.empty()
                st.success(f"✨ Успішно збагачено {len(enriched_new)} з {len(data['new'])} новинок через OpenAI!")

            with st.spinner("Формування SQL-файлу..."):
                bytes_written = generate_weekly_sync_sql(
                    changed_products=data['changed'],
                    discontinued_models=data['discontinued'],
                    output_sql_path=output_sql_path
                )

                # Update cache snapshot so next week compares against these new values
                if data['changed']:
                    update_cache_snapshots(CACHE_FILE, [p for p, _ in data['changed']])

                # If new products were enriched, append their full INSERTs
                if auto_enrich_new and enriched_new:
                    exporter = OpenCartSQLExporter(table_prefix="oc_", lang_ua_id=3, lang_ru_id=1)
                    temp_new_sql = OUTPUT_DIR / "temp_new.sql"
                    exporter.generate_sql(enriched_new, str(temp_new_sql))
                    if temp_new_sql.exists():
                        with open(temp_new_sql, "r", encoding="utf-8") as f_in:
                            new_sql_text = f_in.read()
                        with open(output_sql_path, "a", encoding="utf-8") as f_out:
                            f_out.write("\n\n-- ======================================================\n")
                            f_out.write("-- ПОВНЕ ДОДАВАННЯ НОВИХ ТОВАРІВ (INSERT)\n")
                            f_out.write("-- ======================================================\n")
                            f_out.write(new_sql_text)
                        temp_new_sql.unlink(missing_ok=True)

                file_size_kb = output_sql_path.stat().st_size / 1024
                st.session_state.ready_sql_path = output_sql_path

            # Direct MySQL Execution
            if direct_upload_clicked:
                with st.spinner("🚀 Підключення до MySQL на Mirohost та застосування оновлень..."):
                    with open(output_sql_path, "r", encoding="utf-8") as f_in:
                        sql_to_run = f_in.read()
                    success, msg, stats = execute_sql_migration(
                        sql_content=sql_to_run,
                        host=cur_db_h,
                        user=cur_db_u,
                        password=cur_db_p,
                        database=cur_db_n,
                        port=cur_db_port
                    )
                    if success:
                        st.balloons()
                        st.success(f"🎉 **{msg}**")
                        st.info(f"Файл оновлень збережено локально: `{output_sql_path.name}` ({file_size_kb:.1f} КБ)")
                    else:
                        st.error(f"❌ {msg}")
                        st.warning("⚠️ Файл SQL збережено локально, ви можете завантажити його або повторити спробу.")
            else:
                st.success(f"Точковий Delta SQL створено: `{output_sql_path.name}` ({file_size_kb:.1f} КБ)!")

        # Download / Apply to DB buttons for generated SQL
        if "ready_sql_path" in st.session_state and st.session_state.ready_sql_path.exists():
            st.divider()
            with open(st.session_state.ready_sql_path, "r", encoding="utf-8") as f:
                sql_content = f.read()

            col_res1, col_res2 = st.columns([1, 1])
            with col_res1:
                st.download_button(
                    label=f"📥 Завантажити SQL-файл ({st.session_state.ready_sql_path.name})",
                    data=sql_content,
                    file_name=st.session_state.ready_sql_path.name,
                    mime="text/plain",
                    use_container_width=True
                )
            with col_res2:
                if st.button("🚀 Відправити цей SQL в базу Mirohost зараз", type="primary", use_container_width=True):
                    if not db_is_configured:
                        st.warning("⚠️ Будь ласка, вкажіть назву та пароль бази даних у вкладці '⚙️ Налаштування та База'.")
                    else:
                        with st.spinner("Застосовуємо SQL-файл у базі OpenCart..."):
                            success, msg, stats = execute_sql_migration(
                                sql_content=sql_content,
                                host=cur_db_h,
                                user=cur_db_u,
                                password=cur_db_p,
                                database=cur_db_n,
                                port=cur_db_port
                            )
                            if success:
                                st.balloons()
                                st.success(f"🎉 **{msg}**")
                            else:
                                st.error(f"❌ {msg}")


# ==============================================================================
# TAB 2: Image Audit (Mirohost)
# ==============================================================================
elif menu == "📸 Аудит зображень":
    st.header("📸 Аудит фотографій каталогу на Mirohost")
    st.write(
        "Пряма перевірка наявності головних фото та галерей ракурсів на сервері Mirohost "
        "(швидке сканування файлів безпосередньо у теці OpenCart без завантаження гігабайтів на ваш ПК)."
    )

    sftp_host = os.getenv("MIROHOST_SFTP_HOST", "ez1036.mirohost.net")
    sftp_port = int(os.getenv("MIROHOST_SFTP_PORT", "21"))
    sftp_user = os.getenv("MIROHOST_SFTP_USER", "huppar")
    sftp_pass = os.getenv("MIROHOST_SFTP_PASS", "")
    sftp_dir = os.getenv("MIROHOST_SFTP_DIR", "image/catalog/product")

    with st.expander("🔑 Параметри підключення до Mirohost (FTP / SFTP)", expanded=not bool(sftp_user and sftp_pass)):
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            cur_host = st.text_input("Хост / Сервер:", value=sftp_host, key="sftp_h")
            cur_port = st.number_input("Порт (21 = FTP, 22 = SFTP):", value=sftp_port, step=1, key="sftp_p")
            cur_dir = st.text_input("Директорія фото на сервері:", value=sftp_dir, key="sftp_d", help="Зазвичай image/catalog/product")
        with col_c2:
            cur_user = st.text_input("Користувач:", value=sftp_user, key="sftp_u")
            cur_pass = st.text_input("Пароль:", value=sftp_pass, type="password", key="sftp_pw")

        if st.button("💾 Зберегти реквізити підключення в .env", key="save_sftp_env"):
            set_key(str(ENV_FILE), "MIROHOST_SFTP_HOST", cur_host)
            set_key(str(ENV_FILE), "MIROHOST_SFTP_PORT", str(cur_port))
            set_key(str(ENV_FILE), "MIROHOST_SFTP_USER", cur_user)
            set_key(str(ENV_FILE), "MIROHOST_SFTP_PASS", cur_pass)
            set_key(str(ENV_FILE), "MIROHOST_SFTP_DIR", cur_dir)
            os.environ["MIROHOST_SFTP_HOST"] = cur_host
            os.environ["MIROHOST_SFTP_PORT"] = str(cur_port)
            os.environ["MIROHOST_SFTP_USER"] = cur_user
            os.environ["MIROHOST_SFTP_PASS"] = cur_pass
            os.environ["MIROHOST_SFTP_DIR"] = cur_dir
            st.success("✅ Реквізити збережено в .env!")

    # Choice of product source
    col_s1, col_s2 = st.columns([2, 1])
    with col_s1:
        sources_available = ["Кеш каталогу (всі збережені товари бази)"]
        if "analysis_data" in st.session_state and st.session_state.analysis_data:
            sources_available.append("Свіжий щотижневий прайс (з аналізу Delta)")

        selected_source = st.selectbox(
            "Які товари перевіряти на наявність фото на сервері?",
            sources_available
        )

    with col_s2:
        st.write("")
        st.write("")
        start_sftp_audit = st.button("🚀 Сканувати фото на Mirohost", type="primary", use_container_width=True)

    if start_sftp_audit:
        # 1. Resolve products to test
        products_to_check: List[ParentProduct] = []
        if selected_source.startswith("Кеш"):
            cached_dict = load_cached_catalog(CACHE_FILE)
            products_to_check = list(cached_dict.values())
        elif "analysis_data" in st.session_state:
            products_to_check = st.session_state.analysis_data.get("fresh_products", [])

        if not products_to_check:
            st.error("❌ Не знайдено товарів для перевірки. Завантажте прайс або переконайтеся у наявності кешу.")
        else:
            target_user = cur_user if 'cur_user' in locals() and cur_user else sftp_user
            target_pass = cur_pass if 'cur_pass' in locals() and cur_pass else sftp_pass
            target_host = cur_host if 'cur_host' in locals() and cur_host else sftp_host
            target_port = cur_port if 'cur_port' in locals() and cur_port else sftp_port
            target_dir = cur_dir if 'cur_dir' in locals() and cur_dir else sftp_dir

            if not target_user or not target_pass:
                st.warning("⚠️ Будь ласка, вкажіть логін та пароль у блоці 'Параметри підключення' вище.")
            else:
                proto_name = "FTP" if target_port == 21 else "SFTP"
                with st.spinner(f"Підключення до {target_host}:{target_port} ({proto_name})..."):
                    client = MirohostSFTPClient(
                        host=target_host,
                        port=target_port,
                        username=target_user,
                        password=target_pass,
                        timeout=15
                    )
                    connected, conn_msg = client.connect()

                if not connected:
                    st.error(f"❌ {conn_msg}")
                else:
                    with st.spinner("Пошук каталогу зображень та зчитування списку файлів на Mirohost..."):
                        remote_folder = client.resolve_remote_dir(target_dir)
                        if not remote_folder:
                            client.close()
                            st.error(f"❌ Не вдалося знайти директорію із зображеннями '{target_dir}' на сервері.")
                        else:
                            remote_images = client.list_remote_images(remote_folder)
                            client.close()

                            audit_res = audit_products_against_remote(products_to_check, remote_images)
                            st.session_state.sftp_audit_summary = audit_res
                            st.session_state.sftp_remote_folder = remote_folder
                            st.session_state.sftp_remote_images = set(remote_images.keys())
                            st.session_state.sftp_products_checked = products_to_check
                            st.success(f"✅ Зчитано {len(remote_images):,} фото з '{remote_folder}'. Аудит завершено!")

    # Display audit results if available
    if "sftp_audit_summary" in st.session_state:
        res: AuditSummary = st.session_state.sftp_audit_summary
        st.divider()
        st.subheader(f"📊 Результати аудиту фото на сервері Mirohost (`{st.session_state.get('sftp_remote_folder', '')}`)")

        # Metrics
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        with m1:
            st.metric("Фото на сервері", f"{res.total_remote_images:,}", f"{res.total_remote_size_mb:.1f} МБ")
        with m2:
            st.metric("Товарів перевірено", f"{res.total_products_checked:,}")
        with m3:
            st.metric("Повний комплект ✅", f"{res.products_with_all_photos:,}", delta="Готові")
        with m4:
            st.metric("Тільки 1 фото 🟡", f"{res.products_main_only:,}", delta="Без ракурсів", delta_color="off")
        with m5:
            st.metric("Без фото ❌", f"{res.products_missing_all + res.products_missing_main:,}", delta="Критично", delta_color="inverse")
        with m6:
            st.metric("Зайві файли 🗑️", f"{res.orphaned_files_count:,}", f"{res.orphaned_files_size_mb:.1f} МБ", delta_color="inverse")

        # Auto-upload missing photos from URL / Foto columns directly to Mirohost FTP
        uploader = DirectPhotoUploader()
        remote_set = set(st.session_state.get("sftp_remote_images", set()))
        tasks_to_upload = []

        if "analysis_data" in st.session_state and st.session_state.analysis_data:
            tasks_to_upload, _ = uploader.build_tasks_from_dataframe(
                st.session_state.analysis_data["df_raw"],
                existing_remote_files=remote_set
            )
        elif "sftp_products_checked" in st.session_state:
            tasks_to_upload, _ = uploader.build_tasks_from_products(
                st.session_state.sftp_products_checked,
                existing_remote_files=remote_set
            )

        if tasks_to_upload:
            with st.expander(f"🚀 Завантажити відсутні фото ({len(tasks_to_upload)} шт.) за лінками з прайсу ➔ Mirohost", expanded=True):
                st.write(
                    f"Знайдено **{len(tasks_to_upload)}** фотографій, яких бракує на сервері Mirohost, "
                    "але для них є робочі посилання в колонках `URL` (головне) та `Foto 1, 2...` (галерея). "
                    "Зображення завантажуються в пам'ять (RAM) і напряму передаються по FTP на Mirohost."
                )

                col_up1, col_up2 = st.columns([2, 1])
                with col_up1:
                    auto_db_link = st.checkbox(
                        "🔗 Також автоматично оновити прив'язку в базі OpenCart (oc_product.image та oc_product_image)",
                        value=True,
                        key="auto_link_photos_cb"
                    )
                with col_up2:
                    start_upload_photos = st.button(
                        f"⬆️ Завантажити {len(tasks_to_upload)} фото на сервер",
                        type="primary",
                        use_container_width=True,
                        key="start_ftp_upload_btn"
                    )

                if start_upload_photos:
                    st.info("Розпочато стрімінг зображень на сервер Mirohost...")
                    prog_bar = st.progress(0.0)
                    stat_caption = st.empty()

                    target_user = cur_user if 'cur_user' in locals() and cur_user else sftp_user
                    target_pass = cur_pass if 'cur_pass' in locals() and cur_pass else sftp_pass
                    target_host = cur_host if 'cur_host' in locals() and cur_host else sftp_host
                    target_port = cur_port if 'cur_port' in locals() and cur_port else sftp_port
                    target_dir = st.session_state.get('sftp_remote_folder', sftp_dir)

                    gen = uploader.upload_missing_photos_generator(
                        tasks=tasks_to_upload,
                        ftp_host=target_host,
                        ftp_user=target_user,
                        ftp_pass=target_pass,
                        ftp_port=target_port,
                        remote_dir=target_dir
                    )

                    last_res = None
                    last_uploaded_tasks = []

                    for event in gen:
                        if event["type"] == "progress":
                            prog_bar.progress(event["current"] / event["total"])
                            status_ico = "✅" if event["status"] == "success" else "❌"
                            stat_caption.caption(
                                f"{status_ico} Завантаження **{event['current']}/{event['total']}**: "
                                f"`{event['filename']}` ({event['parent_id']})"
                            )
                        elif event["type"] == "complete":
                            last_res = event["result"]
                            last_uploaded_tasks = event.get("uploaded_tasks", [])
                        elif event["type"] == "error":
                            st.error(event["message"])

                    prog_bar.empty()
                    stat_caption.empty()

                    if last_res:
                        st.balloons()
                        st.success(f"🎉 Успішно завантажено на Mirohost: **{last_res.uploaded_success}** фото!")
                        if last_res.failed > 0:
                            st.warning(f"⚠️ Не вдалося завантажити {last_res.failed} фото (помилки джерела або мережі).")

                        # Auto database linking if requested
                        if auto_db_link and last_uploaded_tasks:
                            cur_db_h = os.getenv("DB_HOST", "ez1036.mirohost.net")
                            cur_db_u = os.getenv("DB_USER", "huppar")
                            cur_db_p = os.getenv("DB_PASS", "")
                            cur_db_n = os.getenv("DB_NAME", "")
                            cur_db_port = int(os.getenv("DB_PORT", "3306"))
                            if cur_db_u and cur_db_p and cur_db_n:
                                with st.spinner("Оновлення зв'язків фото в базі даних OpenCart..."):
                                    m_up, g_up, db_msg = link_uploaded_images_in_opencart_db(
                                        uploaded_tasks=last_uploaded_tasks,
                                        host=cur_db_h,
                                        user=cur_db_u,
                                        password=cur_db_p,
                                        database=cur_db_n,
                                        port=cur_db_port
                                    )
                                    st.success(f"🗄️ {db_msg}")

                        # Update session state remote files set with newly uploaded filenames
                        for t in last_uploaded_tasks:
                            st.session_state.sftp_remote_images.add(t.filename.lower())

        tab_missing, tab_main_only, tab_complete, tab_orphaned = st.tabs([
            "❌ Без фото або без головного",
            "🟡 Тільки головне фото",
            "🟢 Повний комплект",
            "🗑️ Зайві файли на сервері"
        ])

        with tab_missing:
            crit_items = [
                {
                    "Артикул": r.parent_id,
                    "Модель": r.model_name,
                    "Колір": r.color_name,
                    "Статус": "Повністю без фото" if r.status == "missing_all" else "Відсутнє головне фото",
                    "Очікуваний файл": r.expected_main
                }
                for r in res.results if r.status in ("missing_all", "missing_main")
            ]
            if crit_items:
                df_crit = pd.DataFrame(crit_items)
                st.dataframe(df_crit, use_container_width=True)
                csv_data = df_crit.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="📥 Завантажити список відсутніх фото (CSV)",
                    data=csv_data,
                    file_name="missing_photos_mirohost.csv",
                    mime="text/csv"
                )
            else:
                st.success("🎉 Відмінно! Всі товари мають головне фото на сервері.")

        with tab_main_only:
            main_only_items = [
                {
                    "Артикул": r.parent_id,
                    "Модель": r.model_name,
                    "Колір": r.color_name,
                    "Головне фото": r.found_main,
                    "Галерея": "Відсутня"
                }
                for r in res.results if r.status == "main_only"
            ]
            if main_only_items:
                st.caption("Ці товари мають головне зображення в каталозі, але не мають додаткових ракурсів у галереї:")
                st.dataframe(pd.DataFrame(main_only_items), use_container_width=True)
            else:
                st.info("Товарів без галереї не виявлено.")

        with tab_complete:
            complete_items = [
                {
                    "Артикул": r.parent_id,
                    "Модель": r.model_name,
                    "Колір": r.color_name,
                    "Головне фото": r.found_main,
                    "Ракурсів у галереї": len(r.found_gallery)
                }
                for r in res.results if r.status == "ok"
            ]
            if complete_items:
                st.dataframe(pd.DataFrame(complete_items), use_container_width=True)

        with tab_orphaned:
            st.caption(
                f"Знайдено **{res.orphaned_files_count:,}** файлів ({res.orphaned_files_size_mb:.1f} МБ), "
                "які присутні на сервері Mirohost, але не співставлені з жодною активною моделлю в каталозі."
            )
            if res.orphaned_files:
                st.dataframe(pd.DataFrame({"Назва файлу на сервері": res.orphaned_files[:500]}), use_container_width=True)
                if len(res.orphaned_files) > 500:
                    st.info(f"Показано перші 500 файлів із {len(res.orphaned_files):,}.")


# ==============================================================================
# TAB 3: Settings & Database
# ==============================================================================
elif menu == "⚙️ Налаштування та База":
    st.header("⚙️ Налаштування доступу до Mirohost та Бази Даних")
    st.write("Керування реквізитами SFTP для фотографій та MySQL для прямого зв'язку з каталогом OpenCart.")

    tab_set_sftp, tab_set_mysql, tab_set_backups = st.tabs([
        "📁 Доступ SFTP / SSH (Mirohost)",
        "🗄️ База даних MySQL (OpenCart)",
        "📦 Резервні копії кешу (10 останніх)"
    ])

    with tab_set_sftp:
        st.subheader("📁 SFTP / SSH параметри сервера")
        st.caption("Використовується для швидкого аудиту та завантаження фото безпосередньо у теку OpenCart.")

        col_sftp1, col_sftp2 = st.columns(2)
        with col_sftp1:
            st_host = st.text_input("SFTP Хост:", value=os.getenv("MIROHOST_SFTP_HOST", "huppa.com.ua"))
            st_port = st.number_input("SFTP Порт:", value=int(os.getenv("MIROHOST_SFTP_PORT", "22")), step=1)
            st_dir = st.text_input("Шлях до каталогу фото на сервері:", value=os.getenv("MIROHOST_SFTP_DIR", "image/catalog/product"))
        with col_sftp2:
            st_user = st.text_input("SFTP Користувач:", value=os.getenv("MIROHOST_SFTP_USER", ""))
            st_pass = st.text_input("SFTP Пароль:", value=os.getenv("MIROHOST_SFTP_PASS", ""), type="password")

        col_b_sftp1, col_b_sftp2 = st.columns(2)
        with col_b_sftp1:
            if st.button("🔌 Перевірити з'єднання по SFTP", use_container_width=True):
                if not st_user or not st_pass:
                    st.warning("Вкажіть логін та пароль SFTP.")
                else:
                    with st.spinner("Перевірка з'єднання з Mirohost..."):
                        c = MirohostSFTPClient(st_host, st_user, st_pass, port=st_port, timeout=10)
                        ok, msg = c.connect()
                        if ok:
                            resolved = c.resolve_remote_dir(st_dir)
                            if resolved:
                                count = len(c.list_remote_images(resolved))
                                st.success(f"✅ Успішне підключення! Знайдено теку `{resolved}` ({count:,} фотографій).")
                            else:
                                st.warning(f"✅ Підключено до SSH/SFTP, але теку `{st_dir}` не знайдено.")
                            c.close()
                        else:
                            st.error(f"❌ {msg}")

        with col_b_sftp2:
            if st.button("💾 Зберегти налаштування SFTP", use_container_width=True, type="primary"):
                set_key(str(ENV_FILE), "MIROHOST_SFTP_HOST", st_host)
                set_key(str(ENV_FILE), "MIROHOST_SFTP_PORT", str(st_port))
                set_key(str(ENV_FILE), "MIROHOST_SFTP_USER", st_user)
                set_key(str(ENV_FILE), "MIROHOST_SFTP_PASS", st_pass)
                set_key(str(ENV_FILE), "MIROHOST_SFTP_DIR", st_dir)
                os.environ["MIROHOST_SFTP_HOST"] = st_host
                os.environ["MIROHOST_SFTP_PORT"] = str(st_port)
                os.environ["MIROHOST_SFTP_USER"] = st_user
                os.environ["MIROHOST_SFTP_PASS"] = st_pass
                os.environ["MIROHOST_SFTP_DIR"] = st_dir
                st.success("✅ Налаштування SFTP збережено в .env!")

    with tab_set_mysql:
        st.subheader("🗄️ MySQL з'єднання з OpenCart")
        st.caption("Вкажіть реквізити бази даних Mirohost для прямого застосування змін без відкриття phpMyAdmin.")

        col_db1, col_db2 = st.columns(2)
        with col_db1:
            db_host = st.text_input("MySQL Host (Mirohost):", value=os.getenv("DB_HOST", "ez1036.mirohost.net"))
            db_name = st.text_input("Назва бази даних:", value=os.getenv("DB_NAME", "huppaqnk"))
            db_user = st.text_input("Користувач бази:", value=os.getenv("DB_USER", "u_huppaqnk"))
        with col_db2:
            db_pass = st.text_input("Пароль бази:", type="password", value=os.getenv("DB_PASS", "pB3SpMDnhduz"))
            db_port = st.number_input("Порт MySQL:", value=int(os.getenv("DB_PORT", "3306")))
            table_prefix = st.text_input("Префікс таблиць:", value=os.getenv("DB_PREFIX", "oc_"))

        col_b_db1, col_b_db2 = st.columns(2)
        with col_b_db1:
            if st.button("🔌 Перевірити з'єднання з базою", use_container_width=True):
                if not db_user or not db_pass or not db_name:
                    st.warning("⚠️ Вкажіть користувача, пароль та назву бази даних.")
                else:
                    with st.spinner("Перевірка підключення до MySQL на Mirohost..."):
                        ok, conn_msg = test_db_connection(
                            host=db_host,
                            user=db_user,
                            password=db_pass,
                            database=db_name,
                            port=int(db_port)
                        )
                        if ok:
                            st.success(f"✅ {conn_msg}")
                        else:
                            st.error(f"❌ {conn_msg}")

        with col_b_db2:
            if st.button("💾 Зберегти реквізити MySQL", use_container_width=True, type="primary"):
                set_key(str(ENV_FILE), "DB_HOST", db_host)
                set_key(str(ENV_FILE), "DB_NAME", db_name)
                set_key(str(ENV_FILE), "DB_USER", db_user)
                set_key(str(ENV_FILE), "DB_PASS", db_pass)
                set_key(str(ENV_FILE), "DB_PORT", str(db_port))
                set_key(str(ENV_FILE), "DB_PREFIX", table_prefix)
                os.environ["DB_HOST"] = db_host
                os.environ["DB_NAME"] = db_name
                os.environ["DB_USER"] = db_user
                os.environ["DB_PASS"] = db_pass
                os.environ["DB_PORT"] = str(db_port)
                os.environ["DB_PREFIX"] = table_prefix
                st.success("✅ Реквізити MySQL збережено в .env!")

    with tab_set_backups:
        st.subheader("📦 Автоматичні резервні копії кешу (10 останніх)")
        st.write(
            "Система автоматично зберігає **до 10 останніх знімків** файлу `data/enriched_cache.jsonl` "
            "із фіксацією точної дати та часу завантаження. "
            "Старіші копії автоматично ротуються, зберігаючи дисковий простір."
        )

        b_col1, b_col2 = st.columns([1, 3])
        with b_col1:
            if st.button("💾 Створити бекап зараз", use_container_width=True, type="primary"):
                if CACHE_FILE.exists():
                    created = create_cache_backup(CACHE_FILE, max_backups=10, tag="manual")
                    if created:
                        st.success(f"✅ Бекап створено: `{created.name}`")
                        st.rerun()
                else:
                    st.warning("Кеш ще не створено.")

        backups = list_cache_backups()
        if backups:
            backup_table_data = [
                {
                    "№": idx,
                    "Дата і час завантаження / створення": b["formatted_date"],
                    "Назва файлу": b["filename"],
                    "Розмір, МБ": f"{b['size_mb']:.2f} МБ",
                    "Товарів у кеші": f"{b['lines_count']:,} шт."
                }
                for idx, b in enumerate(backups, start=1)
            ]
            st.dataframe(pd.DataFrame(backup_table_data), use_container_width=True, hide_index=True)

            st.divider()
            st.subheader("🔄 Відновлення стану каталогу з бекапу")
            st.caption("Оберіть потрібний знімок, якщо потрібно повернутися до попереднього стану каталогу:")

            backup_options = {
                f"{b['formatted_date']} — {b['filename']} ({b['lines_count']} товарів, {b['size_mb']} МБ)": b["path"]
                for b in backups
            }
            selected_backup_label = st.selectbox("Оберіть версію для відновлення:", list(backup_options.keys()))
            selected_backup_path = backup_options[selected_backup_label]

            col_rest1, col_rest2 = st.columns([1, 1])
            with col_rest1:
                if st.button("⏪ Відновити цей бекап як активний кеш", type="secondary", use_container_width=True):
                    with st.spinner("Відновлюємо кеш із резервної копії..."):
                        ok = restore_cache_backup(selected_backup_path, CACHE_FILE)
                        if ok:
                            st.success(f"✅ Кеш успішно відновлено з файлу: `{selected_backup_path.name}`!")
                            st.rerun()
                        else:
                            st.error("❌ Не вдалося відновити файл бекапу.")

            with col_rest2:
                with open(selected_backup_path, "rb") as f_down:
                    st.download_button(
                        label=f"📥 Завантажити цей файл ({selected_backup_path.name})",
                        data=f_down.read(),
                        file_name=selected_backup_path.name,
                        mime="application/json",
                        use_container_width=True
                    )
        else:
            st.info("Поки що немає збережених резервних копій. Натисніть кнопку вище, щоб створити першу копію.")

