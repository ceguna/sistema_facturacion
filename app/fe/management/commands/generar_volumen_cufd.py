"""
Pide CUFD repetidamente contra el SIN Piloto, para subir el volumen de
casos correctos de la Etapa III de certificacion (200 casos: 100 con
codigoPuntoVenta=0, 100 con codigoPuntoVenta=1).

A diferencia de CUIS, el CUFD SI admite pedidos repetidos sin rechazo
por "ya existe uno vigente" -- confirmado en la corrida de volumen de
facturas anterior (10 ciclos completos pidieron 30 CUFD sin problema),
justamente porque esta pensado para pedirse todo el tiempo (es el
codigo "diario", no uno de larga duracion como el CUIS).

Uso:
    python manage.py generar_volumen_cufd --veces 50
    python manage.py generar_volumen_cufd --veces 50 --codigo-punto-venta 1
"""
import time

from decouple import config
from zeep import Client
from zeep.transports import Transport
from zeep.helpers import serialize_object
from requests import Session
from django.core.management.base import BaseCommand, CommandError

from fe.models import Empresa, Sucursal, PuntoVenta

WSDL_CODIGOS = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"


class Command(BaseCommand):
    help = (
        "Pide CUFD repetidamente contra el SIN Piloto, para subir el "
        "volumen de casos correctos de la Etapa III de certificacion."
    )

    def add_arguments(self, parser):
        parser.add_argument('--veces', type=int, default=50,
                             help='Cuantas veces pedir CUFD.')
        parser.add_argument('--pausa', type=float, default=3.0,
                             help='Segundos de espera entre cada pedido.')
        parser.add_argument(
            '--codigo-punto-venta', type=int, default=0,
            help='Punto de venta a usar. 0 (default) = casa matriz implicito, '
                 'usa el CUIS de la Sucursal. Cualquier otro valor busca el '
                 'PuntoVenta correspondiente y usa SU PROPIO CUIS.'
        )

    def handle(self, *args, **options):
        veces = options['veces']
        pausa = options['pausa']
        codigo_punto_venta = options['codigo_punto_venta']

        empresa = Empresa.objects.first()
        if not empresa or not empresa.nit or not empresa.codigo_sistema:
            raise CommandError("Empresa sin NIT o codigo_sistema cargado.")

        sucursal = Sucursal.objects.filter(empresa=empresa, codigo_sucursal=0).first()
        if not sucursal:
            raise CommandError("No existe la Sucursal casa matriz (codigo_sucursal=0).")

        # Mismo criterio que en sincronizar_catalogos.py / generar_volumen_catalogos.py:
        # 0 usa el CUIS de la Sucursal, cualquier otro valor usa el CUIS
        # PROPIO de ese PuntoVenta.
        if codigo_punto_venta == 0:
            if not sucursal.codigo_cuis:
                raise CommandError("Sucursal casa matriz sin CUIS cargado.")
            cuis = sucursal.codigo_cuis
        else:
            punto_venta = PuntoVenta.objects.filter(
                sucursal=sucursal, codigo_punto_venta=codigo_punto_venta
            ).first()
            if not punto_venta:
                raise CommandError(
                    f"No existe un PuntoVenta con código {codigo_punto_venta} "
                    "registrado localmente para la sucursal casa matriz."
                )
            if not punto_venta.codigo_cuis:
                raise CommandError(
                    f"El PuntoVenta {codigo_punto_venta} ('{punto_venta.nombre}') "
                    "no tiene CUIS propio cargado todavía."
                )
            cuis = punto_venta.codigo_cuis

        try:
            token = config("SIN_TOKEN_DELEGADO")
        except Exception:
            raise CommandError("Falta la variable de entorno SIN_TOKEN_DELEGADO (.env).")

        codigo_ambiente = 1 if empresa.ambiente == Empresa.PRODUCCION else 2

        session = Session()
        session.headers.update({"apikey": f"TokenApi {token}"})
        client = Client(wsdl=WSDL_CODIGOS, transport=Transport(session=session))

        solicitud = {
            "codigoAmbiente": codigo_ambiente,
            "codigoModalidad": 1,
            "codigoPuntoVenta": codigo_punto_venta,
            "codigoSistema": empresa.codigo_sistema,
            "codigoSucursal": sucursal.codigo_sucursal,
            "cuis": cuis,
            "nit": empresa.nit,
        }

        self.stdout.write(self.style.WARNING(
            f"Pidiendo CUFD {veces} veces (punto de venta {codigo_punto_venta}), "
            f"con {pausa}s de pausa entre pedidos."
        ))

        exitosos = 0
        fallidos = 0

        for i in range(1, veces + 1):
            try:
                resp = client.service.cufd(SolicitudCufd=solicitud)
                resp = serialize_object(resp)
                if resp.get("transaccion"):
                    self.stdout.write(self.style.SUCCESS(f"[{i}/{veces}] OK"))
                    exitosos += 1
                else:
                    self.stdout.write(self.style.ERROR(
                        f"[{i}/{veces}] RECHAZADO: {resp.get('mensajesList')}"
                    ))
                    fallidos += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[{i}/{veces}] EXCEPCION: {e}"))
                fallidos += 1

            if i < veces:
                time.sleep(pausa)

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(
            f"RESUMEN: {exitosos} exitosos, {fallidos} fallidos, de {veces} intentados."
        ))