import shlex
import shutil
import subprocess
from urllib.parse import unquote, urlparse

import pymysql
from pymysql.err import OperationalError


class MySQLService:
    """
    Поддерживаем строку подключения формата:
      mysql://user:pass@host:3306/dbname?charset=utf8mb4

    Примечания:
    - Пароль и имя БД экранируем; пароль передаём через аргумент --password=...
    - Для дампа используем --single-transaction (без блокировок на InnoDB),
      плюс триггеры/ивенты/рутины.
    """

    @staticmethod
    def _supports_flag(binary: str, flag: str) -> bool:
        """
        Возвращает True, если бинарь поддерживает указанный флаг (ищем в --help).
        """
        try:
            out = subprocess.check_output([binary, "--help"], stderr=subprocess.STDOUT, text=True)
            return flag in out
        except Exception:
            return False

    @staticmethod
    def _brand(binary: str) -> str:
        """
        Определяем бренд клиента: 'mariadb' или 'mysql' по выводу --version.
        """
        try:
            out = subprocess.check_output([binary, "--version"], stderr=subprocess.STDOUT, text=True).lower()
            if "mariadb" in out:
                return "mariadb"
            return "mysql"
        except Exception:
            return "unknown"

    @staticmethod
    def _parse_connection_string(connection_string: str):
        parsed = urlparse(connection_string)
        if parsed.scheme != "mysql":
            raise ValueError("Ожидается URI со схемой mysql://")

        user = unquote(parsed.username or "")
        password = unquote(parsed.password or "")
        host = parsed.hostname or "localhost"
        port = parsed.port or 3306
        database = parsed.path.lstrip("/") or None
        if not database:
            raise ValueError("В URI MySQL должен быть указан database, например mysql://u:p@h:3306/db")

        return user, password, host, port, database

    @staticmethod
    def _bin(name_fallbacks):
        """
        Находим первый доступный бинарник по списку кандидатов.
        Например: ["mysqldump", "mariadb-dump"].
        """
        for name in name_fallbacks:
            path = shutil.which(name)
            if path:
                return path
        # Вернём просто имя — пусть ОС попробует найти (на случай PATH в рантайме)
        return name_fallbacks[0]

    @staticmethod
    def server_alive(connection_string: str) -> bool:
        user, password, host, port, database = MySQLService._parse_connection_string(connection_string)
        try:
            conn = pymysql.connect(
                host=host, port=port, user=user, password=password,
                connect_timeout=5, charset="utf8mb4"
            )
            conn.close()
            return True
        except Exception:
            return False

    @staticmethod
    def check_connection(connection_string: str) -> bool:
        """Строгая проверка: подключиться именно к указанной БД.
        Для restore будем использовать server_alive(), если тут False из-за 1049.
        """
        try:
            user, password, host, port, database = MySQLService._parse_connection_string(connection_string)
            conn = pymysql.connect(
                host=host, port=port, user=user, password=password, database=database,
                connect_timeout=5, charset="utf8mb4"
            )
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return True
        except OperationalError as e:
            # 1049 = Unknown database '<db>'
            if getattr(e, "args", None) and e.args and e.args[0] == 1049:
                return False  # для dump — это действительно проблема
            return False
        except Exception:
            return False

    def dump_database(self, connection_string: str, operation_id: int):
        user, password, host, port, database = self._parse_connection_string(connection_string)

        output_file = f"/tmp/dump_{operation_id}.sql"
        mysqldump = self._bin(["mysqldump", "mariadb-dump"])

        _ = self._brand(mysqldump)

        # Базовые безопасные флаги
        cmd = [
            mysqldump,
            f"--host={host}",
            f"--port={port}",
            f"--user={user}",
            f"--password={password}",
            "--single-transaction",
            "--triggers",
            "--routines",
            "--events",
            "--skip-add-locks",
            "--default-character-set=utf8mb4",
        ]

        # MySQL 8-клиент против старых серверов: отключаем column-statistics, если флаг поддерживается
        if self._supports_flag(mysqldump, "--column-statistics"):
            cmd.append("--column-statistics=0")

        # GTID: добавляем ТОЛЬКО если флаг поддерживается (обычно это Oracle MySQL)
        if self._supports_flag(mysqldump, "--set-gtid-purged"):
            cmd.append("--set-gtid-purged=OFF")

        # Логируем без пароля
        safe_cmd = [x if not x.startswith("--password=") else "--password=****" for x in cmd]
        print("Выполняем команду mysqldump:", " ".join(shlex.quote(x) for x in safe_cmd), f"{database=}")

        try:
            with open(output_file, "wb") as f:
                subprocess.run(cmd + [database], check=True, stdout=f)
        except subprocess.CalledProcessError as e:
            # Доп. фолбэк: если упало из-за неизвестного флага — повторим без спорных ключей
            msg = str(e)
            if "unknown option" in msg.lower() or "unknown variable" in msg.lower():
                print("Повтор дампа без спорных ключей (--set-gtid-purged/--column-statistics).")
                fallback = [a for a in cmd if not a.startswith(
                    "--set-gtid-purged") and not a.startswith("--column-statistics")]
                with open(output_file, "wb") as f:
                    subprocess.run(fallback + [database], check=True, stdout=f)
            else:
                return None, f"Ошибка при создании дампа MySQL: {e}"
        except Exception as e:
            return None, f"Неизвестная ошибка дампа MySQL: {e}"

        return output_file, None

    def load_dump(self, connection_string: str, filepath: str):
        try:
            with open(filepath, "rb"):
                pass
        except FileNotFoundError:
            return False, "Dump file not found"

        user, password, host, port, database = self._parse_connection_string(connection_string)
        mysql_bin = self._bin(["mysql", "mariadb"])

        # Список коллаций по убыванию "современности"
        collations = ["utf8mb4_0900_ai_ci", "utf8mb4_unicode_ci", "utf8mb4_general_ci"]

        # 1) Создать БД, если нет (без DROP DATABASE!)
        create_ok = False
        last_err = None
        for collation in collations:
            create_cmd = [
                mysql_bin,
                f"--host={host}",
                f"--port={port}",
                f"--user={user}",
                f"--password={password}",
                "-e",
                f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE {collation};"
            ]
            try:
                print(f"Ensure database exists with collation {collation} ...")
                subprocess.run(create_cmd, check=True)
                create_ok = True
                break
            except subprocess.CalledProcessError as e:
                last_err = e
                print(f"Collation {collation} not supported, trying next...")

        if not create_ok:
            return False, f"Не удалось создать БД: {last_err}"

        # 2) Очистить БД: дропаем все объекты внутри (без удаления самой БД)
        #    Это безопасно даже при ограниченных правах.
        cleanup_sql = rf"""
        SET FOREIGN_KEY_CHECKS=0;
        SELECT CONCAT('DROP TABLE IF EXISTS `', table_name, '`;')
        FROM information_schema.tables
        WHERE table_schema = '{database}' AND table_type='BASE TABLE'
        INTO OUTFILE '/tmp/drop_tables.sql';
        """
        # Не у всех есть FILE-права. Тогда делаем однокомандно:
        list_cmd = [
            mysql_bin, f"--host={host}", f"--port={port}",
            f"--user={user}", f"--password={password}",
            "-Nse",
            f"SELECT CONCAT('DROP TABLE IF EXISTS `', table_name, '`;') "
            f"FROM information_schema.tables WHERE table_schema='{database}' AND table_type='BASE TABLE';"
        ]
        try:
            print("Listing tables to drop...")
            out = subprocess.check_output(list_cmd, text=True)
            if out.strip():
                drop_cmd = [
                    mysql_bin, f"--host={host}", f"--port={port}",
                    f"--user={user}", f"--password={password}", database
                ]
                print("Dropping existing tables...")
                subprocess.run(drop_cmd, input="SET FOREIGN_KEY_CHECKS=0;\n"+out, text=True, check=True)
        except subprocess.CalledProcessError as e:
            # Не критично: если таблиц нет — ничего не дропнем
            print(f"Warn: cleanup step failed/non-critical: {e}")

        # 3) Импорт дампа
        load_cmd = [
            mysql_bin,
            f"--host={host}",
            f"--port={port}",
            f"--user={user}",
            f"--password={password}",
            "--default-character-set=utf8mb4",
            database,
        ]
        try:
            print("Load dump...")
            with open(filepath, "rb") as f:
                subprocess.run(load_cmd, check=True, stdin=f)
        except subprocess.CalledProcessError as e:
            return False, f"Ошибка при загрузке дампа MySQL: {e}"
        except Exception as e:
            return False, f"Неизвестная ошибка MySQL: {e}"

        return True, None
