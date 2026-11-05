from django.core.management.base import BaseCommand


from manager.services.alert_manager import send_notification
from manager.services.backup_service import BackupService


class Command(BaseCommand):
    help = 'Operation of restore dump'

    def add_arguments(self, parser):
        parser.add_argument('operation_id', type=str, help='Operation Id')

    def handle(self, *args, **options):
        operation_id = options['operation_id']
        backup_service = BackupService(operation_id)
        success, error = backup_service.restore_dump()

        send_notification(operation_id, success, error)
