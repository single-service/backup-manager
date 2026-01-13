from django.db.models import IntegerChoices
from django.utils.translation import gettext as _


class DBType(IntegerChoices):
    POSTGRESQL = 1, 'Postgres'
    CLICKHOUSE = 2, 'ClickHouse'
    MYSQL = 3, 'Mysql'


class DumpTaskPeriodsChoices(IntegerChoices):
    NEVER = 1, _('Never')
    EVERYDAY = 2, _('Every day')
    EVERYWEEK = 3, _('Every week')
    EVERYMONTH = 4, _('Every month')


class DumpOperationStatusChoices(IntegerChoices):
    CREATED = 1, _('Created')
    IN_PROCESS = 2, _('In Process')
    FAIL = 3, _('Fail')
    SUCCESS = 4, _('Success')
