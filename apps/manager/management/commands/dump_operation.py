from django.core.management.base import BaseCommand


from apps.manager.services.alert_manager import send_notification
from manager.services.backup_service import BackupService


class Command(BaseCommand):
    help = 'Operation of dump'

    def add_arguments(self, parser):
        parser.add_argument('operation_id', type=str, help='Operation Id')

    def handle(self, *args, **options):
        operation_id = options['operation_id']
        backup_service = BackupService(operation_id)
        success, error = backup_service.make_dump()

        send_notification(operation_id, success, error)
        # Проверка на max_cnt_keep
