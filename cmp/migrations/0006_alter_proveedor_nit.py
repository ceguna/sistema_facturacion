# Generated by Django 4.2.2 on 2023-09-16 15:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cmp', '0005_alter_proveedor_nit'),
    ]

    operations = [
        migrations.AlterField(
            model_name='proveedor',
            name='nit',
            field=models.CharField(max_length=30, unique=True),
        ),
    ]
