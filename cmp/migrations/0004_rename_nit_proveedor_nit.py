# Generated by Django 4.2.2 on 2023-09-16 12:11

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('cmp', '0003_alter_proveedor_direccion'),
    ]

    operations = [
        migrations.RenameField(
            model_name='proveedor',
            old_name='NIT',
            new_name='nit',
        ),
    ]
