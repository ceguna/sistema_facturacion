from decouple import config
from django.core.management.base import BaseCommand, CommandError

from catalogos.services import sincronizar_todos_los_catalogos, SOAPClienteSIN
from fe.models import Empresa, Sucursal, PuntoVenta


class Command(BaseCommand):
    help = (
        "Sincroniza los catálogos paramétricos del SIN. Debe ejecutarse "
        "diariamente antes de solicitar el CUFD (Art. 19/20 RND "
        "101800000026). Pensado para correr vía Render Cron Jobs, igual "
        "que en el proyecto OJO ALERTA."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--codigo-punto-venta', type=int, default=0,
            help='Punto de venta a usar para la sincronizacion. 0 (default) = '
                 'casa matriz implicito, usa el CUIS de la Sucursal. Cualquier '
                 'otro valor busca el PuntoVenta correspondiente (ya registrado '
                 'localmente) y usa SU PROPIO CUIS -- cada combinacion '
                 'Sucursal+PuntoVenta tiene un CUIS distinto ante el SIN.'
        )

    def handle(self, *args, **options):
        codigo_punto_venta = options['codigo_punto_venta']

        empresa = Empresa.objects.first()
        if not empresa:
            raise CommandError(
                "No hay configuración de Empresa cargada todavía. "
                "Completar /fe/ antes de poder sincronizar catálogos."
            )
        if not empresa.nit:
            raise CommandError("La Empresa no tiene NIT cargado todavía.")
        if not empresa.codigo_sistema:
            raise CommandError(
                "La Empresa no tiene codigo_sistema cargado todavía "
                "(se completa al aprobar la Autorización de Sistemas ante el SIN)."
            )

        sucursal_matriz = Sucursal.objects.filter(
            empresa=empresa, codigo_sucursal=0
        ).first()
        if not sucursal_matriz:
            raise CommandError(
                "No existe la Sucursal casa matriz (codigo_sucursal=0). "
                "Cargarla antes de sincronizar catálogos."
            )

        # El CUIS correcto depende del punto de venta pedido -- 0 usa el
        # de la Sucursal (comportamiento de siempre, sin cambios);
        # cualquier otro busca el CUIS PROPIO de ese PuntoVenta, nunca
        # el de la Sucursal (son combinaciones distintas ante el SIN).
        if codigo_punto_venta == 0:
            if not sucursal_matriz.codigo_cuis:
                raise CommandError(
                    "La Sucursal casa matriz no tiene CUIS cargado todavía "
                    "(se obtiene del servicio 'cuis' del SIN, ver prototipo/sin/probar_cuis.py)."
                )
            cuis = sucursal_matriz.codigo_cuis
        else:
            punto_venta = PuntoVenta.objects.filter(
                sucursal=sucursal_matriz, codigo_punto_venta=codigo_punto_venta
            ).first()
            if not punto_venta:
                raise CommandError(
                    f"No existe un PuntoVenta con código {codigo_punto_venta} "
                    "registrado localmente para la sucursal casa matriz."
                )
            if not punto_venta.codigo_cuis:
                raise CommandError(
                    f"El PuntoVenta {codigo_punto_venta} ('{punto_venta.nombre}') no tiene "
                    "CUIS propio cargado todavía. Cada combinación Sucursal+PuntoVenta "
                    "necesita su propio CUIS (obtenido con ese mismo codigoPuntoVenta en "
                    "el servicio 'cuis' del SIN)."
                )
            cuis = punto_venta.codigo_cuis

        try:
            token = config("SIN_TOKEN_DELEGADO")
        except Exception:
            raise CommandError(
                "Falta la variable de entorno SIN_TOKEN_DELEGADO (.env)."
            )

        codigo_ambiente = 1 if empresa.ambiente == Empresa.PRODUCCION else 2

        cliente_soap = SOAPClienteSIN(
            token=token,
            nit=empresa.nit,
            codigo_sistema=empresa.codigo_sistema,
            cuis=cuis,
            codigo_sucursal=sucursal_matriz.codigo_sucursal,
            codigo_punto_venta=codigo_punto_venta,
            codigo_ambiente=codigo_ambiente,
        )

        exitosa, mensaje = sincronizar_todos_los_catalogos(cliente_soap)
        if exitosa:
            self.stdout.write(self.style.SUCCESS(mensaje))
        else:
            self.stdout.write(self.style.ERROR(mensaje))