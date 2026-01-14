import os
from ftplib import FTP, error_perm as FTPError
import boto3
import yadisk
import paramiko
from botocore.exceptions import NoCredentialsError, PartialCredentialsError


class S3StorageSerivce:
    def __init__(self, storage_instance):
        self.storage_instance = storage_instance
        self.s3 = None

    def _connect(self):
        self.s3 = boto3.client(
            's3',
            endpoint_url=self.storage_instance.host,
            aws_access_key_id=self.storage_instance.access_key,
            aws_secret_access_key=self.storage_instance.secret_key,
        )

    def upload_dump(self, filepath, operation_id):
        error = None
        s3_file_path = None
        fileformat = filepath.split(".")[-1]
        try:
            self._connect()
            key = f'dumps/{operation_id}.{fileformat}'
            self.s3.upload_file(filepath, self.storage_instance.bucket_name, key)
            s3_file_path = key
        except FileNotFoundError:
            error = "File not found"
        except (NoCredentialsError, PartialCredentialsError):
            error = "Credentials are not valid"
        except Exception as e:
            error = str(e)
        return s3_file_path, error

    def delete_dump(self, filepath):
        try:
            self._connect()
            self.s3.delete_object(Bucket=self.storage_instance.bucket_name, Key=filepath)
        except Exception:
            return False
        return True

    def download_dump(self, s3_file_path):
        filename = s3_file_path.split("/")[-1]
        local_filepath = f"/tmp/{filename}"
        try:
            self._connect()
            self.s3.download_file(
                Bucket=self.storage_instance.bucket_name,
                Key=s3_file_path,
                Filename=local_filepath
            )
        except getattr(self.s3, "exceptions", object()).__dict__.get("NoSuchKey", Exception) as _:  # noqa
            return None, "File not found in S3"
        except (NoCredentialsError, PartialCredentialsError):
            return None, "Credentials are not valid"
        except Exception as e:
            return None, str(e)
        return local_filepath, None


class YandexDiskStorageSerivce:
    """
    Использует secret_key как OAuth-токен.
    Кладём в /dumps/<operation_id>.<ext>
    """

    def __init__(self, storage_instance):
        self.storage_instance = storage_instance
        if not self.storage_instance.secret_key:
            raise RuntimeError("Yandex Disk OAuth token is empty (use secret_key)")
        self._y = yadisk.YaDisk(token=self.storage_instance.secret_key)

    def upload_dump(self, filepath, operation_id):
        error = None
        remote_path = None
        fileformat = filepath.split(".")[-1]
        try:
            base = "/dumps"
            if not self._y.exists(base):
                self._y.mkdir(base)
            remote_path = f"{base}/{operation_id}.{fileformat}"
            self._y.upload(filepath, remote_path)
        except FileNotFoundError:
            error = "File not found"
        except Exception as e:
            error = str(e)
        return remote_path, error

    def delete_dump(self, filepath):
        try:
            if self._y.exists(filepath):
                self._y.remove(filepath, permanently=True)
            return True
        except Exception:
            return False

    def download_dump(self, remote_path):
        filename = remote_path.split("/")[-1]
        local_filepath = f"/tmp/{filename}"
        try:
            if not self._y.exists(remote_path):
                return None, "File not found in Yandex Disk"
            self._y.download(remote_path, local_filepath)
        except Exception as e:
            return None, str(e)
        return local_filepath, None


class FTPStorageService:
    """
    Использует FTP для хранения дампов.
    host - FTP сервер
    access_key - username
    secret_key - password
    bucket_name - базовый путь (например: /, /p1, /backups)
    Кладём в {bucket_name}/dumps/<operation_id>.<ext>
    """

    def __init__(self, storage_instance):
        self.storage_instance = storage_instance
        if not self.storage_instance.host:
            raise RuntimeError("FTP host is required")
        if not self.storage_instance.access_key:
            raise RuntimeError("FTP username is required (use access_key)")
        if not self.storage_instance.secret_key:
            raise RuntimeError("FTP password is required (use secret_key)")

        # Получаем базовый путь из bucket_name, по умолчанию "/"
        self.base_path = (self.storage_instance.bucket_name or "/").rstrip("/")
        if not self.base_path:
            self.base_path = "/"

    def _connect(self):
        """Создает и возвращает FTP соединение."""
        ftp = FTP()
        # Парсим host и port
        host_parts = self.storage_instance.host.split(":")
        host = host_parts[0]
        port = int(host_parts[1]) if len(host_parts) > 1 else 21

        ftp.connect(host, port)
        ftp.login(self.storage_instance.access_key, self.storage_instance.secret_key)
        return ftp

    def _ensure_directory(self, ftp, path):
        """Создает директорию если её нет."""
        dirs = path.strip("/").split("/")
        current = ""
        for d in dirs:
            if not d:
                continue
            current = f"{current}/{d}"
            try:
                ftp.cwd(current)
            except FTPError:
                try:
                    ftp.mkd(current)
                    ftp.cwd(current)
                except FTPError:
                    pass

    def upload_dump(self, filepath, operation_id):
        error = None
        remote_path = None
        fileformat = filepath.split(".")[-1]

        try:
            ftp = self._connect()
            try:
                # Формируем полный путь: base_path/dumps
                dumps_dir = f"{self.base_path}/dumps".replace("//", "/")

                # Создаем директорию dumps если нужно
                self._ensure_directory(ftp, dumps_dir)
                ftp.cwd(dumps_dir)

                # Загружаем файл
                filename = f"{operation_id}.{fileformat}"
                with open(filepath, "rb") as f:
                    ftp.storbinary(f"STOR {filename}", f)

                remote_path = f"{dumps_dir}/{filename}".replace("//", "/")
            finally:
                ftp.quit()
        except FileNotFoundError:
            error = "File not found"
        except FTPError as e:
            error = f"FTP error: {e}"
        except Exception as e:
            error = str(e)

        return remote_path, error

    def delete_dump(self, filepath):
        try:
            ftp = self._connect()
            try:
                ftp.delete(filepath)
                return True
            finally:
                ftp.quit()
        except Exception:
            return False

    def download_dump(self, remote_path):
        filename = remote_path.split("/")[-1]
        local_filepath = f"/tmp/{filename}"

        try:
            ftp = self._connect()
            try:
                with open(local_filepath, "wb") as f:
                    ftp.retrbinary(f"RETR {remote_path}", f.write)
            finally:
                ftp.quit()
        except FTPError as e:
            if "550" in str(e):
                return None, "File not found on FTP"
            return None, f"FTP error: {e}"
        except Exception as e:
            return None, str(e)

        return local_filepath, None


class SFTPStorageService:
    """
    Использует SFTP (SSH File Transfer Protocol) для хранения дампов.
    host - SFTP сервер (может содержать порт: host:port)
    access_key - username
    secret_key - password
    bucket_name - базовый путь (например: /, /p1, /backups)
    Кладём в {bucket_name}/dumps/<operation_id>.<ext>
    """

    def __init__(self, storage_instance):
        self.storage_instance = storage_instance
        if not self.storage_instance.host:
            raise RuntimeError("SFTP host is required")
        if not self.storage_instance.access_key:
            raise RuntimeError("SFTP username is required (use access_key)")
        if not self.storage_instance.secret_key:
            raise RuntimeError("SFTP password is required (use secret_key)")

        # Получаем базовый путь из bucket_name, по умолчанию "/"
        self.base_path = (self.storage_instance.bucket_name or "/").rstrip("/")
        if not self.base_path:
            self.base_path = "/"

    def _connect(self):
        """Создает и возвращает SFTP соединение."""
        # Парсим host и port
        host_parts = self.storage_instance.host.split(":")
        host = host_parts[0]
        port = int(host_parts[1]) if len(host_parts) > 1 else 22

        # Создаем SSH клиент
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=host,
            port=port,
            username=self.storage_instance.access_key,
            password=self.storage_instance.secret_key,
            timeout=30
        )

        # Открываем SFTP сессию
        sftp = ssh.open_sftp()
        # Сохраняем ссылку на SSH для правильного закрытия
        sftp._ssh_client = ssh
        return sftp

    def _ensure_directory(self, sftp, path):
        """Создает директорию если её нет."""
        dirs = path.strip("/").split("/")
        current = ""
        for d in dirs:
            if not d:
                continue
            current = f"{current}/{d}" if current else f"/{d}"
            try:
                sftp.stat(current)
            except IOError:
                try:
                    sftp.mkdir(current)
                except IOError:
                    pass

    def upload_dump(self, filepath, operation_id):
        error = None
        remote_path = None
        fileformat = filepath.split(".")[-1]

        try:
            sftp = self._connect()
            try:
                # Формируем полный путь: base_path/dumps
                dumps_dir = f"{self.base_path}/dumps".replace("//", "/")

                # Создаем директорию dumps если нужно
                self._ensure_directory(sftp, dumps_dir)

                # Загружаем файл
                filename = f"{operation_id}.{fileformat}"
                remote_file_path = f"{dumps_dir}/{filename}".replace("//", "/")
                sftp.put(filepath, remote_file_path)

                remote_path = remote_file_path
            finally:
                sftp.close()
                if hasattr(sftp, '_ssh_client'):
                    sftp._ssh_client.close()
        except FileNotFoundError:
            error = "File not found"
        except paramiko.SSHException as e:
            error = f"SSH error: {e}"
        except Exception as e:
            error = str(e)

        return remote_path, error

    def delete_dump(self, filepath):
        try:
            sftp = self._connect()
            try:
                sftp.remove(filepath)
                return True
            finally:
                sftp.close()
                if hasattr(sftp, '_ssh_client'):
                    sftp._ssh_client.close()
        except Exception:
            return False

    def download_dump(self, remote_path):
        filename = remote_path.split("/")[-1]
        local_filepath = f"/tmp/{filename}"

        try:
            sftp = self._connect()
            try:
                sftp.get(remote_path, local_filepath)
            finally:
                sftp.close()
                if hasattr(sftp, '_ssh_client'):
                    sftp._ssh_client.close()
        except IOError as e:
            if e.errno == 2:  # No such file
                return None, "File not found on SFTP"
            return None, f"SFTP IO error: {e}"
        except paramiko.SSHException as e:
            return None, f"SSH error: {e}"
        except Exception as e:
            return None, str(e)

        return local_filepath, None
