"""
Repite la sincronizacion de catalogos varias veces, con pausa entre
cada corrida, para subir el volumen de casos correctos de la Etapa II
de certificacion Piloto (1800 casos requeridos -- cada corrida exitosa
suma 16, ya que 16 de los 17 catalogos sincronizan correctamente).

No parsea texto de salida (es fragil -- Django le agrega codigos de
color ANSI invisibles al capturar stdout de un comando corrido desde
otro comando). En su lugar, llama directo a sincronizar_todos_los_catalogos,
la misma funcion de servicio que usa sincronizar_catalogos.py, replicando
la misma construccion de credenciales.

Uso:
    python manage.py generar_volumen_catalogos --veces 20
    python manage.py generar_volumen_catalogos --veces 50 --pausa 5
    python manage.py generar_volumen_catalogos --veces 20 --codigo-punto-venta 1
"""
import time

from decouple import config
from django.core.management.base import BaseCommand, CommandError

from catalogos.services import sincronizar_todos_los_catalogos, SOAPClienteSIN
from fe.models import Empresa, Sucursal, PuntoVenta


class Command(BaseCommand):
    help = (
        "Corre la sincronizacion de catalogos repetidamente, con pausa entre "
        "cada corrida, para subir el volumen de casos correctos de la Etapa II "
        "de certificacion Piloto."
    )

    def add_arguments(self, parser):
        parser.add_argument('--veces', type=int, default=20,
                             help='Cuantas veces correr la sincronizacion completa.')
        parser.add_argument('--pausa', type=float, default=5.0,
                             help='Segundos de espera entre cada corrida completa.')
        parser.add_argument(
            '--codigo-punto-venta', type=int, default=0,
            help='Punto de venta a usar. 0 (default) = casa matriz implicito, '
                 'usa el CUIS de la Sucursal. Cualquier otro valor busca el '
                 'PuntoVenta correspondiente (ya registrado localmente) y usa '
                 'SU PROPIO CUIS.'
        )

    def handle(self, *args, **options):
        veces = options['veces']
        pausa = options['pausa']
        codigo_punto_venta = options['codigo_punto_venta']

        # Misma validacion y armado de credenciales que sincronizar_catalogos.py
        empresa = Empresa.objects.first()
        if not empresa or not empresa.nit or not empresa.codigo_sistema:
            raise CommandError("Empresa sin NIT o codigo_sistema cargado.")

        sucursal_matriz = Sucursal.objects.filter(empresa=empresa, codigo_sucursal=0).first()
        if not sucursal_matriz:
            raise CommandError("No existe la Sucursal casa matriz (codigo_sucursal=0).")

        # Mismo criterio que en sincronizar_catalogos.py: 0 usa el CUIS de
        # la Sucursal, cualquier otro valor usa el CUIS PROPIO de ese
        # PuntoVenta -- nunca se reutiliza un CUIS entre combinaciones
        # distintas de Sucursal+PuntoVenta.
        if codigo_punto_venta == 0:
            if not sucursal_matriz.codigo_cuis:
                raise CommandError("Sucursal casa matriz sin CUIS cargado.")
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
                    f"El PuntoVenta {codigo_punto_venta} ('{punto_venta.nombre}') "
                    "no tiene CUIS propio cargado todavía."
                )
            cuis = punto_venta.codigo_cuis

        try:
            token = config("SIN_TOKEN_DELEGADO")
        except Exception:
            raise CommandError("Falta la variable de entorno SIN_TOKEN_DELEGADO (.env).")

        codigo_ambiente = 1 if empresa.ambiente == Empresa.PRODUCCION else 2

        self.stdout.write(self.style.WARNING(
            f"Corriendo sincronizacion de catalogos {veces} veces (punto de venta "
            f"{codigo_punto_venta}), con {pausa}s de pausa entre corridas."
        ))

        exitosas = 0
        con_error = 0

        for i in range(1, veces + 1):
            cliente_soap = SOAPClienteSIN(
                token=token,
                nit=empresa.nit,
                codigo_sistema=empresa.codigo_sistema,
                cuis=cuis,
                codigo_sucursal=sucursal_matriz.codigo_sucursal,
                codigo_punto_venta=codigo_punto_venta,
                codigo_ambiente=codigo_ambiente,
            )

            try:
                exitosa, mensaje = sincronizar_todos_los_catalogos(cliente_soap)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[{i}/{veces}] EXCEPCION: {e}"))
                con_error += 1
                if i < veces:
                    time.sleep(pausa)
                continue

            # El "exitosa" real de la funcion de servicio -- no se parsea texto.
            # Nota: 16/17 catalogos con ACT_DOC_SECTOR fallando a proposito
            # (ver services.py) hace que 'exitosa' de la funcion sea False
            # tecnicamente (hay errores en la lista), aunque 16 catalogos si
            # se hayan sincronizado con exito real ante el SIN. Por eso acá
            # se cuenta como corrida "util" en base a que la mayoria de
            # catalogos sí sincronizo, no en base al booleano estricto.
            if "16/17" in mensaje or "17/17" in mensaje:
                self.stdout.write(self.style.SUCCESS(f"[{i}/{veces}] {mensaje}"))
                exitosas += 1
            else:
                self.stdout.write(self.style.WARNING(f"[{i}/{veces}] {mensaje}"))
                con_error += 1

            if i < veces:
                time.sleep(pausa)

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(
            f"RESUMEN: {exitosas} corridas utiles (16 o 17 de 17 catalogos), "
            f"{con_error} con error mayor, de {veces} intentadas."
        ))