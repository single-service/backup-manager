import uuid

from django.db import models
from django.utils.translation import gettext as _
from django.core.exceptions import ValidationError

from manager.choices import DBType, DumpTaskPeriodsChoices, DumpOperationStatusChoices


class AbstractBaseModel(models.Model):
    # Fields
    id = models.CharField(primary_key=True, default=uuid.uuid4,
                          editable=False, max_length=100, db_index=True)
    created_dt = models.DateTimeField(
        _('Date of creation'), auto_now_add=True, editable=False)
    updated_dt = models.DateTimeField(
        _('Date of update'), auto_now=True, editable=True)

    class Meta:
        abstract = True


class FileStorage(models.Model):
    TYPE_S3 = "s3"
    TYPE_YADISK = "yadisk"
    TYPE_FTP = "ftp"
    TYPE_SFTP = "sftp"
    TYPE_CHOICES = (
        (TYPE_S3, "S3"),
        (TYPE_YADISK, "Yandex Disk"),
        (TYPE_FTP, "FTP"),
        (TYPE_SFTP, "SFTP"),
    )

    name = models.CharField(max_length=255, unique=True)
    type = models.CharField(
        max_length=10, choices=TYPE_CHOICES, default=TYPE_S3)

    # Поля для различных типов хранилищ
    host = models.CharField(max_length=255, blank=True, null=True, help_text=_(
        "S3 endpoint / FTP/SFTP host. Для Yandex Disk можно оставить пустым"))
    bucket_name = models.CharField(max_length=255, blank=True, null=True, help_text=_(
        "S3 bucket (для S3). FTP/SFTP базовый путь"))
    access_key = models.CharField(max_length=255, blank=True, null=True, help_text=_(
        "S3 Access Key / FTP/SFTP username"))
    secret_key = models.CharField(max_length=255, blank=True, null=True,
                                  help_text=_("S3 Secret Key / OAuth-токен (Yandex Disk) / FTP/SFTP password"))

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("File storage")
        verbose_name_plural = _("File storages")

    def __str__(self):
        return f"{self.name} [{self.get_type_display()}]"

    def clean(self):
        # Валидация по типу
        t = (self.type or "").lower()
        if t == self.TYPE_S3:
            missing = []
            if not self.host:
                missing.append("host")
            if not self.bucket_name:
                missing.append("bucket_name")
            if not self.access_key:
                missing.append("access_key")
            if not self.secret_key:
                missing.append("secret_key")
            if missing:
                raise ValidationError({f: _("Required for S3")
                                      for f in missing})
        elif t == self.TYPE_YADISK:
            if not self.secret_key:
                raise ValidationError(
                    {"secret_key": _("OAuth token is required for Yandex Disk")})
        elif t in (self.TYPE_FTP, self.TYPE_SFTP):
            missing = []
            if not self.host:
                missing.append("host")
            if not self.access_key:
                missing.append("access_key")
            if not self.secret_key:
                missing.append("secret_key")
            if missing:
                storage_type = "FTP" if t == self.TYPE_FTP else "SFTP"
                raise ValidationError({f: _(f"Required for {storage_type}")
                                      for f in missing})


class UserDatabase(AbstractBaseModel):
    name = models.CharField(_("Name"), max_length=100)
    db_type = models.IntegerField(_("Type"), choices=DBType.choices)
    connection_string = models.TextField(_("Connection Link"))

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _('Database')
        verbose_name_plural = _('Databases')


class DumpTask(AbstractBaseModel):
    # Relations
    database = models.ForeignKey(
        "manager.UserDatabase", on_delete=models.CASCADE)
    file_storage = models.ForeignKey(
        "manager.FileStorage", on_delete=models.CASCADE)

    # Fields
    task_period = models.IntegerField(
        _("Task Period"), choices=DumpTaskPeriodsChoices.choices)
    max_dumpfiles_keep = models.PositiveIntegerField(
        _("Max Dump files count to keep"), default=1)

    def __str__(self):
        return str(self.id)

    class Meta:
        verbose_name = _('Dump Task')
        verbose_name_plural = _('Dump Tasks')


class DumpTaskOperation(AbstractBaseModel):
    # Relations
    task = models.ForeignKey("manager.DumpTask", on_delete=models.CASCADE)

    # Fields
    status = models.IntegerField(
        _("Status"), choices=DumpOperationStatusChoices.choices, default=DumpOperationStatusChoices.CREATED)
    error_text = models.TextField(
        _("Error text"), blank=True, default=None, null=True)
    dump_path = models.CharField(
        _("Dump File Path"), max_length=250, null=True, blank=True, default=None)

    def __str__(self):
        return str(self.id)

    class Meta:
        verbose_name = _('Dump Task Operation')
        verbose_name_plural = _('Dump Tasks Operations')


class RecoverBackupOperation(AbstractBaseModel):
    # Relations
    dump_operation = models.ForeignKey(
        "manager.DumpTaskOperation", on_delete=models.CASCADE)

    # Fields
    status = models.IntegerField(
        _("Status"), choices=DumpOperationStatusChoices.choices, default=DumpOperationStatusChoices.CREATED)
    error_text = models.TextField(
        _("Error text"), blank=True, default=None, null=True)

    def __str__(self):
        return str(self.id)

    class Meta:
        verbose_name = _('Recover Backup Operation')
        verbose_name_plural = _('Recover Backup Operations')
