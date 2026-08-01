"""
Limpia los datos de PRUEBA cargados durante el desarrollo (orientados
a una textileria de ejemplo), dejando intacto todo lo que corresponde
a la operacion real de la libreria:

    SE MANTIENEN:
      - Clientes (fac.Cliente)
      - Usuarios y Roles (auth.User, auth.Group)
      - Configuracion SIN (fe.Empresa, fe.Sucursal, fe.PuntoVenta)
      - Catalogos SIN sincronizados (catalogos.CatalogoSIN, SincronizacionLog)

    SE BORRAN:
      - Facturas de venta (fac.FacturaDet, fac.FacturaEnc)
      - Compras (cmp.ComprasDet, cmp.ComprasEnc, cmp.Proveedor)
      - Productos e inventario (inv.Producto, inv.Subcategoria,
        inv.Categoria, inv.Marca)

Por defecto corre en modo VISTA PREVIA (no borra nada, solo cuenta).
Para ejecutar el borrado real hay que agregar --confirmar.

Uso:
    python manage.py limpiar_datos_prueba                (vista previa)
    python manage.py limpiar_datos_prueba --confirmar     (borra de verdad)
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.apps import apps


class Command(BaseCommand):
    help = "Limpia datos de prueba (textileria), preservando clientes, usuarios y configuracion SIN."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Ejecuta el borrado real. Sin esta bandera, solo muestra una vista previa.",
        )

    def handle(self, *args, **options):
        confirmar = options["confirmar"]

        # Orden importante: primero el detalle, despues la cabecera,
        # despues las tablas de las que dependen (para no chocar con
        # relaciones protegidas, sin importar el on_delete configurado).
        modelos_a_limpiar = [
            ("fac", "FacturaDet"),
            ("fac", "FacturaEnc"),
            ("cmp", "ComprasDet"),
            ("cmp", "ComprasEnc"),
            ("cmp", "Proveedor"),
            ("inv", "Producto"),
            ("inv", "Subcategoria"),
            ("inv", "Categoria"),
            ("inv", "Marca"),
        ]

        self.stdout.write(self.style.WARNING(
            "\n=== VISTA PREVIA: esto es lo que se va a borrar ===\n"
            if not confirmar else
            "\n=== BORRANDO DATOS DE PRUEBA ===\n"
        ))

        conteos = {}
        for app_label, model_name in modelos_a_limpiar:
            Modelo = apps.get_model(app_label, model_name)
            cantidad = Modelo.objects.count()
            conteos[(app_label, model_name)] = cantidad
            self.stdout.write(f"  {app_label}.{model_name}: {cantidad} registros")

        total = sum(conteos.values())

        if not confirmar:
            self.stdout.write(self.style.WARNING(
                f"\nTotal a borrar: {total} registros.\n"
                "Nada se borro todavia. Para ejecutar el borrado real, "
                "corre: python manage.py limpiar_datos_prueba --confirmar"
            ))
            return

        if total == 0:
            self.stdout.write(self.style.SUCCESS("\nNo hay nada que borrar."))
            return

        with transaction.atomic():
            for app_label, model_name in modelos_a_limpiar:
                Modelo = apps.get_model(app_label, model_name)
                cantidad_borrada, _ = Modelo.objects.all().delete()
                self.stdout.write(
                    f"  {app_label}.{model_name}: {cantidad_borrada} registros borrados"
                )

        self.stdout.write(self.style.SUCCESS(
            f"\nListo. Se borraron {total} registros de prueba.\n"
            "Se mantuvieron intactos: Clientes, Usuarios/Roles, "
            "configuracion SIN (fe), y catalogos sincronizados."
        ))