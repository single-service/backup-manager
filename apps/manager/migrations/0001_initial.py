# Generated by Django 5.1.3 on 2024-11-14 15:20
import os

from django.db import migrations


def create_superuser(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_superuser),
    ]
