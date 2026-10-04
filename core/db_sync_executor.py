"""
Direct OpenCart MySQL Database Synchronization Executor
======================================================
Executes generated SQL migrations directly in the remote Mirohost OpenCart database
using pymysql with multi-statement support.
"""

import time
from typing import Tuple, Dict, Any, Optional
import pymysql
import pymysql.constants.CLIENT as CLIENT


def execute_sql_migration(
    sql_content: str,
    host: str,
    user: str,
    password: str,
    database: str,
    port: int = 3306,
    timeout: int = 15
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Connects to MySQL and executes the entire SQL migration script.
    Preserves MySQL user variables (@current_product_id, etc.) and transaction safety.
    
    Returns:
        (success: bool, message: str, stats: dict)
    """
    clean_sql = sql_content.strip()
    if not clean_sql:
        return False, "SQL-скрипт порожній.", {}

    start_time = time.perf_counter()
    statements_count = 0
    total_affected = 0

    try:
        connection = pymysql.connect(
            host=host.strip(),
            user=user.strip(),
            password=password,
            database=database.strip(),
            port=int(port),
            charset="utf8mb4",
            client_flag=CLIENT.MULTI_STATEMENTS,
            connect_timeout=timeout,
            autocommit=True  # SQL script itself controls transactions (START TRANSACTION ... COMMIT)
        )

        with connection.cursor() as cursor:
            # Execute the multi-statement script
            cursor.execute(clean_sql)
            statements_count += 1
            if cursor.rowcount > 0:
                total_affected += cursor.rowcount

            # Iterate through all query results in the multi-statement batch
            while cursor.nextset():
                statements_count += 1
                if cursor.rowcount > 0:
                    total_affected += cursor.rowcount

        connection.close()
        elapsed = time.perf_counter() - start_time

        stats = {
            "elapsed_seconds": round(elapsed, 3),
            "statements_executed": statements_count,
            "total_affected_rows": total_affected,
        }

        return (
            True,
            f"Базу успішно оновлено за {elapsed:.2f} сек! Виконано {statements_count} блоків запитів.",
            stats
        )

    except pymysql.err.OperationalError as e:
        code, msg = e.args if len(e.args) >= 2 else (0, str(e))
        if code in (1045, 1130):
            return (
                False,
                f"Помилка доступу до MySQL (Код {code}): {msg}. "
                "Переконайтеся, що в панелі Mirohost дозволено віддалений доступ для вашого IP або користувача.",
                {}
            )
        elif code == 1049:
            return False, f"Базу даних '{database}' не знайдено на сервері {host}.", {}
        elif code == 2003:
            return False, f"Не вдалося підключитися до хоста {host}:{port} — перевірте інтернет або статус сервера.", {}
        return False, f"Помилка MySQL ({code}): {msg}", {}

    except pymysql.err.ProgrammingError as e:
        code, msg = e.args if len(e.args) >= 2 else (0, str(e))
        return False, f"Синтаксична помилка SQL (Код {code}): {msg}", {}

    except Exception as e:
        return False, f"Непередбачена помилка виконання SQL: {e}", {}


def test_db_connection(
    host: str,
    user: str,
    password: str,
    database: str,
    port: int = 3306,
    timeout: int = 5
) -> Tuple[bool, str]:
    """Tests connection to the OpenCart MySQL database."""
    try:
        conn = pymysql.connect(
            host=host.strip(),
            user=user.strip(),
            password=password,
            database=database.strip(),
            port=int(port),
            connect_timeout=timeout
        )
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            ver = cur.fetchone()
            db_version = ver[0] if ver else "unknown"
        conn.close()
        return True, f"Успішне з'єднання! MySQL версія: {db_version}"
    except Exception as e:
        return False, f"Помилка з'єднання: {e}"
