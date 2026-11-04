from manager.choices import DBType
from manager.services.databases.clickhouse import ClickhouseService
from manager.services.databases.mysql import MySQLService
from manager.services.databases.postgres import PostgresqlService
from manager.services.databases.s3 import S3ServiceDB

DB_INTERFACE = {
    DBType.POSTGRESQL: PostgresqlService,
    DBType.CLICKHOUSE: ClickhouseService,
    DBType.MYSQL: MySQLService,
    DBType.S3: S3ServiceDB,
}
