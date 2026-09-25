from django.db import migrations


def proveedores_a_la_central(apps, schema_editor):
    """25/09/2026: los proveedores ya cargados eran globales (sin
    sucursal). Al pasar a proveedores propios por sucursal (sin
    compartidos), se asignan a la Casa Matriz (codigo_sucursal=0) -- la
    Central es quien hace las compras grandes. Sin sucursales cargadas
    (instalacion vieja) no se toca nada."""
    Proveedor = apps.get_model('cmp', 'Proveedor')
    Sucursal = apps.get_model('fe', 'Sucursal')
    central = Sucursal.objects.filter(codigo_sucursal=0).order_by('id').first()
    if central is not None:
        Proveedor.objects.filter(sucursal__isnull=True).update(sucursal=central)


class Migration(migrations.Migration):

    dependencies = [
        ('cmp', '0018_precios_sucursal_y_proveedor_sin_compartidos'),
    ]

    operations = [
        migrations.RunPython(proveedores_a_la_central, migrations.RunPython.noop),
    ]
