from django.contrib.sites import requests
from django.conf import settings

from apps.manager.models import DumpTaskOperation


def send_notification(operation_id, success, error=None):
    operation = (
        DumpTaskOperation.objects
        .select_related("task", "task__database")
        .filter(id=operation_id)
        .first()
    )
    if not operation:
        return

    task = operation.task
    if not task.is_webhook:
        return

    url = settings.ALERT_MANAGER_URL
    api_key = settings.ALERT_MANAGER_APIKEY
    if not url or not api_key:
        return

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "operation_id": operation.id,
        "task_id": task.id,
        "database": task.database.name,
        "status": "success" if success else "failed",
        "dump_path": operation.dump_path if success else None,
        "error": str(error) if error else None,
    }
    try:
        requests.post(url, headers=headers, json=payload, timeout=10)
    except Exception as e:
        print(f"send_notification data:{payload} ; Error {e}")
