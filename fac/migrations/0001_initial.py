# Generated by Django 4.2.6 on 2023-10-16 21:57

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Cliente',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('estado', models.BooleanField(default=True)),
                ('fc', models.DateTimeField(auto_now_add=True)),
                ('fm', models.DateTimeField(auto_now=True)),
                ('um', models.IntegerField(blank=True, null=True)),
                ('nombres', models.CharField(max_length=100)),
                ('apellidos', models.CharField(max_length=100)),
                ('ci', models.CharField(max_length=20, null=True, unique=True)),
                ('nit', models.CharField(max_length=30, null=True, unique=True)),
                ('razon', models.CharField(max_length=100, null=True, unique=True)),
                ('celular', models.CharField(blank=True, max_length=20, null=True)),
                ('tipo', models.CharField(choices=[('Natural', 'Natural'), ('Juridica', 'Juridica')], default='Natural', max_length=10)),
                ('uc', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name_plural': 'Clientes',
            },
        ),
    ]
