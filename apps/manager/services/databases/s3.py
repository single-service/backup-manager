from urllib.parse import urlparse, unquote
import json
import os
import shutil
import subprocess
import tempfile
import tarfile

import boto3
from botocore.config import Config


class S3ServiceDB:
    @staticmethod
    def check_connection(connection_string: str) -> bool:
        try:
            parsed = urlparse(connection_string)
            endpoint = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port:
                endpoint += f":{parsed.port}"

            client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=unquote(parsed.username or ""),
                aws_secret_access_key=unquote(parsed.password or ""),
                config=Config(
                    connect_timeout=5,
                    read_timeout=5,
                    retries={"max_attempts": 1},
                ),
            )
            client.list_buckets()
            return True
        except Exception:
            return False

    @staticmethod
    def _run_mc(args: list[str], env: dict) -> subprocess.CompletedProcess:
        res = subprocess.run(
            ["mc", *args], env=env, capture_output=True, text=True
        )
        if res.returncode != 0:
            # В args нет секретов: доступ передаётся через env MC_HOST_src
            raise RuntimeError(
                f"mc {' '.join(args)} failed ({res.returncode}): {res.stderr.strip()}"
            )
        return res

    def dump_database(self, connection_string: str, operation_id):
        """
        connection_string: https://access_key:secret_key@host[:port]
        (спецсимволы в ключах должны быть percent-encoded)
        Возвращает (путь_к_архиву, None) или (None, текст_ошибки).
        """
        if shutil.which("mc") is None:
            return None, "Ошибка при создании дампа: утилита mc не найдена"

        archive_base = f"/tmp/dump_{operation_id}"
        archive_path = f"{archive_base}.tar.gz"

        work = tempfile.mkdtemp(prefix="s3_dump_")
        cfg = tempfile.mkdtemp(prefix="mc_cfg_")
        env = {**os.environ, "MC_HOST_src": connection_string, "MC_CONFIG_DIR": cfg}

        print("Выполняем команду dump")
        try:
            res = self._run_mc(["--json", "ls", "src"], env)
            buckets = [
                json.loads(line)["key"].rstrip("/")
                for line in res.stdout.splitlines()
                if line.strip()
            ]

            for bucket in buckets:
                bucket_dir = os.path.join(work, bucket)
                os.makedirs(bucket_dir, exist_ok=True)
                self._run_mc(["mirror", "--quiet", f"src/{bucket}", bucket_dir], env)

            shutil.make_archive(archive_base, "gztar", work)
            return archive_path, None

        except Exception as e:
            print("S3 dump failed")
            if os.path.exists(archive_path):
                os.remove(archive_path)
            return None, f"Ошибка при создании дампа: {e}"
        finally:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(cfg, ignore_errors=True)

    @staticmethod
    def _safe_extract(archive_path: str, dest: str) -> None:
        """Распаковка tar.gz с защитой от path traversal."""
        with tarfile.open(archive_path, "r:gz") as tar:
            if hasattr(tarfile, "data_filter"):  # Python 3.12+ и бэкпорты
                tar.extractall(dest, filter="data")
                return
            dest_real = os.path.realpath(dest)
            for member in tar.getmembers():
                target = os.path.realpath(os.path.join(dest, member.name))
                if not target.startswith(dest_real + os.sep) and target != dest_real:
                    raise RuntimeError(f"Небезопасный путь в архиве: {member.name}")
                if member.issym() or member.islnk():
                    raise RuntimeError(f"Ссылки в архиве не поддерживаются: {member.name}")
            tar.extractall(dest)

    def load_dump(self, connection_string: str, filepath: str):
        """
        connection_string: https://access_key:secret_key@host[:port]
        filepath: путь к tar.gz архиву, созданному dump_database.
        Возвращает (True, None) или (False, текст_ошибки).
        """
        if not os.path.isfile(filepath):
            return False, "Dump file not found"

        if shutil.which("mc") is None:
            return False, "Ошибка при загрузке дампа: утилита mc не найдена"

        work = tempfile.mkdtemp(prefix="s3_restore_")
        cfg = tempfile.mkdtemp(prefix="mc_cfg_")
        env = {**os.environ, "MC_HOST_dst": connection_string, "MC_CONFIG_DIR": cfg}

        try:
            print("Extract archive...")
            self._safe_extract(filepath, work)

            buckets = sorted(
                d for d in os.listdir(work)
                if os.path.isdir(os.path.join(work, d))
            )
            if not buckets:
                return False, "Архив не содержит бакетов"

            for bucket in buckets:
                bucket_dir = os.path.join(work, bucket)

                print(f"Create bucket {bucket}...")
                self._run_mc(["mb", "--ignore-existing", f"dst/{bucket}"], env)

                # --overwrite: перезаписать существующие объекты
                # --remove: удалить в целевом бакете то, чего нет в дампе
                #           (аналог DROP SCHEMA: получаем точную копию дампа)
                print(f"Load bucket {bucket}...")
                self._run_mc(
                    ["mirror", "--quiet", "--overwrite", "--remove",
                     bucket_dir, f"dst/{bucket}"],
                    env,
                )

            return True, None

        except (tarfile.TarError, RuntimeError) as e:
            print("S3 restore failed")
            return False, f"S3 restore failed Ошибка при загрузке дампа: {e}"
        except Exception as e:
            print("S3 restore unexpected error")
            return False, f"S3 restore unexpected error Неизвестная ошибка: {e}"
        finally:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(cfg, ignore_errors=True)
