import os
from manager.choices import DumpOperationStatusChoices
from manager.models import (DumpTaskOperation, FileStorage,
                            RecoverBackupOperation)
from manager.services.databases import DB_INTERFACE
from manager.services.storage_factory import get_storage_service


class BackupService:

    def __init__(self, operation_id):
        self.operation_id = operation_id

    def _set_error4operation(self, operation, error):
        print(error)
        operation.status = DumpOperationStatusChoices.FAIL
        operation.error_text = error
        operation.save()

    def make_dump(self):
        operation = DumpTaskOperation.objects.filter(id=self.operation_id).first()
        if not operation:
            return False, f"Operation {self.operation_id} doesn't exist"

        operation.status = DumpOperationStatusChoices.IN_PROCESS
        operation.error_text = None
        operation.save()

        db = operation.task.database
        storage = operation.task.file_storage  # теперь это FileStorage

        # bucket обязателен только для S3
        if storage.type == FileStorage.TYPE_S3 and not storage.bucket_name:
            error = "Need to add bucket name to storage"
            self._set_error4operation(operation, error)
            return False, error

        db_interface = DB_INTERFACE[db.db_type]()
        is_connected = db_interface.check_connection(db.connection_string)
        if not is_connected:
            error = "Database connection failed"
            self._set_error4operation(operation, error)
            return False, error

        filepath, error = db_interface.dump_database(db.connection_string, operation.id)
        if error:
            self._set_error4operation(operation, error)
            return False, error

        # получаем нужный сервис (S3 или Yandex) по типу
        try:
            storage_service = get_storage_service(storage)

            remote_path, error = storage_service.upload_dump(filepath, operation.id)
            if error:
                self._set_error4operation(operation, error)
                return False, error
        finally:
            # удаляем временный файл
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception as e:
                    print(f"Failed to remove temp file {filepath}: {e}")

        print(f"File uploaded successfully to {remote_path}")
        operation.status = DumpOperationStatusChoices.SUCCESS
        operation.error_text = None
        operation.dump_path = remote_path
        operation.save()

        # max_files_keep (чуть поправил off-by-one: держим ровно max_files_cnt последних)
        previous_dump_operations = DumpTaskOperation.objects.filter(
            task=operation.task,
            status=DumpOperationStatusChoices.SUCCESS,
        ).order_by("-created_dt")

        max_files_cnt = operation.task.max_dumpfiles_keep or 0
        files2delete = []
        operations2delete = []

        for idx, dump_operation in enumerate(previous_dump_operations):
            if idx < max_files_cnt:
                continue
            files2delete.append(dump_operation.dump_path)
            operations2delete.append(dump_operation.id)

        # delete files
        if files2delete:
            for file_backup_path in files2delete:
                try:
                    storage_service.delete_dump(file_backup_path)
                except Exception:
                    pass
        if operations2delete:
            DumpTaskOperation.objects.filter(id__in=operations2delete).delete()

        print("Dump Success")
        return True, None

    def restore_dump(self):
        operation = RecoverBackupOperation.objects.filter(id=self.operation_id).first()
        if not operation:
            return False, f"Operation {self.operation_id} doesn't exist"

        operation.status = DumpOperationStatusChoices.IN_PROCESS
        operation.error_text = None
        operation.save()

        dump_operation = operation.dump_operation
        db = dump_operation.task.database
        storage = dump_operation.task.file_storage  # FileStorage

        if storage.type == FileStorage.TYPE_S3 and not storage.bucket_name:
            error = "Need to add bucket name to storage"
            self._set_error4operation(operation, error)
            return False, error

        db_interface = DB_INTERFACE[db.db_type]()
        is_connected = db_interface.check_connection(db.connection_string)
        if not is_connected:
            # Для восстановления допускаем отсутствие самой БД: важно, чтобы сервер/учётка были доступны
            if hasattr(db_interface, "server_alive") and db_interface.server_alive(db.connection_string):
                is_connected = True

        if not is_connected:
            error = "Database connection failed"
            self._set_error4operation(operation, error)
            return False, error

        storage_service = get_storage_service(storage)
        # DOWNLOAD DUMP
        filepath, error = storage_service.download_dump(dump_operation.dump_path)
        if error:
            self._set_error4operation(operation, error)
            return False, error

        # RESTORE DUMP
        try:
            _, error = db_interface.load_dump(
                filepath=filepath,
                connection_string=db.connection_string
            )
            if error:
                self._set_error4operation(operation, error)
                return False, error
        finally:
            # удаляем временный файл
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception as e:
                    print(f"Failed to remove temp file {filepath}: {e}")

        print("File restored successfully")
        operation.status = DumpOperationStatusChoices.SUCCESS
        operation.error_text = None
        operation.save()
        return True, None
