import subprocess
from urllib.parse import urlparse

import psycopg2


class PostgresqlService:

    @staticmethod
    def check_connection(connection_string: str) -> bool:
        try:
            with psycopg2.connect(connection_string, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return True
        except Exception:
            return False

    def dump_database(self, connection_string, operation_id):
        output_file = f"/tmp/dump_{operation_id}.sql"
        pg_dump = "/usr/lib/postgresql/17/bin/pg_dump"
        # --clean   -> добавить DROP
        # --if-exists -> безопасные DROP IF EXISTS
        # --no-owner/--no-privileges -> не трогать владельцев/гранты
        command = [
            pg_dump, connection_string,
            "--clean", "--if-exists", "--no-owner", "--no-privileges",
            "-f", output_file,
        ]
        print("Выполняем команду dump")
        res = subprocess.run(command, capture_output=True, text=True)
        if res.returncode != 0:
            # stderr содержит реальную причину; пароль из строки подключения не светим
            stderr = res.stderr.strip()
            password = urlparse(connection_string).password
            if password:
                stderr = stderr.replace(password, "***")
            return None, f"Ошибка при создании дампа (код {res.returncode}): {stderr}"
        return output_file, None

    def load_dump(self, connection_string, filepath):
        try:
            with open(filepath, 'r'):
                pass
        except FileNotFoundError:
            return False, "Dump file not found"

        psql = "/usr/lib/postgresql/17/bin/psql"

        drop_cmd = f'{psql} "{connection_string}" -v ON_ERROR_STOP=1 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'

        filtered = f"{filepath}.filtered"
        sed_cmd = f"grep -v '^SET[[:space:]]\\+transaction_timeout' '{filepath}' > '{filtered}'"

        # 3) грузим дамп, стопимся на первой ошибке
        load_cmd = f'{psql} "{connection_string}" -v ON_ERROR_STOP=1 -f "{filtered}"'

        try:
            print("Drop schema...")
            subprocess.run(drop_cmd, shell=True, check=True)
            print("Filter transaction_timeout...")
            subprocess.run(sed_cmd, shell=True, check=True)
            print("Load dump...")
            subprocess.run(load_cmd, shell=True, check=True)
        except subprocess.CalledProcessError as e:
            return False, f"Ошибка при загрузке дампа: {e}"
        except Exception as e:
            return False, f"Неизвестная ошибка: {e}"
        return True, None
