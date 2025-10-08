# Базовый образ
FROM python:3.12-bookworm

# Небуферизованный вывод и без .pyc
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# Базовые утилиты (включая ca-certificates и gpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    wget \
    gnupg \
    lsb-release \
 && rm -rf /var/lib/apt/lists/*

# Подключаем официальный репозиторий PostgreSQL 17 через keyring
RUN install -d -m 0755 /etc/apt/keyrings \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    | gpg --dearmor -o /etc/apt/keyrings/postgresql.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/postgresql.gpg] http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list

# Ставим системные зависимости и Postgres 17
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    git \
    gettext \
    netcat-openbsd \
    wkhtmltopdf \
    fonts-noto-color-emoji \
    cron \
    nginx \
    supervisor \
    postgresql-17 \
    postgresql-client-17 \
    default-mysql-client \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Устанавливаем clickhouse-backup
RUN wget -q https://github.com/Altinity/clickhouse-backup/releases/download/v2.6.3/clickhouse-backup-linux-amd64.tar.gz \
 && tar -zxf clickhouse-backup-linux-amd64.tar.gz \
 && mv build/linux/amd64/clickhouse-backup /usr/local/bin/clickhouse-backup \
 && rm -rf clickhouse-backup-linux-amd64.tar.gz build \
 && mkdir -p /etc/clickhouse-backup

# Рабочая директория
ENV HOME=/backup_manager/
WORKDIR $HOME

# Python-зависимости
COPY requirements.txt requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# Скрипт запуска
COPY ./compose/start /start
RUN sed -i 's/\r$//g' /start && chmod +x /start

# Cron
COPY ./compose/cronfile /etc/cron.d/dump_cron
RUN chmod 0644 /etc/cron.d/dump_cron && crontab /etc/cron.d/dump_cron

# Приложение
COPY ./apps .

# Логи/директории
RUN mkdir -p /backup_manager/logs && touch /var/log/cron.log

# Nginx и Supervisor
RUN rm /etc/nginx/nginx.conf
COPY compose/nginx.conf /etc/nginx/nginx.conf
COPY compose/default.conf /etc/nginx/conf.d/default.conf
COPY compose/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Порты
EXPOSE 80 8009

# Старт
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
