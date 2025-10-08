from manager.choices import DBType
from manager.services.databases.clickhouse import ClickhouseService
from manager.services.databases.mysql import MySQLService
from manager.services.databases.postgres import PostgresqlService

DB_INTERFACE = {
    DBType.POSTGRESQL: PostgresqlService,
    DBType.CLICKHOUSE: ClickhouseService,
    DBType.MYSQL: MySQLService
}
