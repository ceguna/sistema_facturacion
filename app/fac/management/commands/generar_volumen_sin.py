"""
Genera volumen de "casos correctos" para subir el porcentaje de las
etapas de certificacion Piloto (IV. Emision individual, VII. Anulacion,
VIII. Reversion, y de rebote III. CUFD, que se pide en cada paso).

Reutiliza los mismos servicios reales ya probados en produccion local
(emitir_factura_sin, anular_factura_sin, revertir_anulacion_sin) --
no duplica logica, solo la ejecuta en bucle con pausa entre llamadas.

Uso:
    python manage.py generar_volumen_sin --cantidad 10
    python manage.py generar_volumen_sin --cantidad 500 --pausa 3
    python manage.py generar_volumen_sin --cantidad 50 --sin-anular
"""
import time

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User

from fac.models import Cliente, FacturaEnc, FacturaDet
from inv.models import Producto
from catalogos.models import CatalogoSIN
from fe.services import emitir_factura_sin, anular_factura_sin, revertir_anulacion_sin, EmisionSinError


class Command(BaseCommand):
    help = (
        "Genera facturas de prueba (emision + anulacion + reversion) contra "
        "el SIN Piloto, para subir el volumen de casos correctos exigido en "
        "la certificacion. Usar SOLO contra la base de datos local de "
        "pruebas, nunca contra produccion."
    )

    def add_arguments(self, parser):
        parser.add_argument('--cantidad', type=int, default=10,
                             help='Cuantos ciclos completos (emitir+anular+revertir) ejecutar.')
        parser.add_argument('--pausa', type=float, default=3.0,
                             help='Segundos de espera entre cada llamada al SIN.')
        parser.add_argument('--sin-anular', action='store_true',
                             help='Solo emitir, sin anular ni revertir (para sumar volumen de la Etapa IV nada mas).')
        parser.add_argument('--usuario', type=str, default=None,
                             help='Username a usar para uc/usuario_anulacion. Por defecto, el primer superusuario.')

    def handle(self, *args, **options):
        cantidad = options['cantidad']
        pausa = options['pausa']
        con_anulacion = not options['sin_anular']

        usuario = None
        if options['usuario']:
            usuario = User.objects.filter(username=options['usuario']).first()
            if not usuario:
                raise CommandError(f"Usuario '{options['usuario']}' no existe.")
        else:
            usuario = User.objects.filter(is_superuser=True).first()
            if not usuario:
                raise CommandError("No hay ningun superusuario en la base. Indique --usuario.")

        cliente = Cliente.objects.first()
        if not cliente:
            raise CommandError("No hay ningun Cliente cargado. Cree uno antes de correr este comando.")

        producto = next((p for p in Producto.objects.filter(estado=True) if p.homologado_sin), None)
        if not producto:
            raise CommandError(
                "No hay ningun Producto homologado (actividad + codigo SIN + unidad con codigo_sin). "
                "Homologue al menos uno desde /inv/productos/ antes de correr este comando."
            )
        # Colchon de stock: cada ciclo completo (emitir+anular+revertir)
        # descuenta 1 unidad neta (no 0 -- el flujo real es -1/+1/-1).
        # Se sube la existencia lo suficiente para que nunca cruce a
        # negativo, sin importar cuantos ciclos se corran.
        stock_necesario = cantidad + 10
        if producto.existencia < stock_necesario:
            stock_original = producto.existencia
            producto.existencia = stock_necesario
            producto.save()
            self.stdout.write(self.style.WARNING(
                f"Existencia de '{producto.descripcion}' insuficiente para {cantidad} ciclos "
                f"(tenia {stock_original}). Se subio temporalmente a {stock_necesario} para la prueba."
            ))

        motivo = CatalogoSIN.objects.filter(
            tipo_catalogo=CatalogoSIN.TipoCatalogo.MOTIVOS_ANULACION, vigente=True
        ).order_by('codigo').first()
        if con_anulacion and not motivo:
            raise CommandError("No hay catalogo de MOTIVOS_ANULACION sincronizado.")

        self.stdout.write(self.style.WARNING(
            f"Generando {cantidad} ciclo(s) — cliente: {cliente}, producto: {producto.descripcion}, "
            f"pausa: {pausa}s entre llamadas, anulacion+reversion: {con_anulacion}"
        ))

        emitidas_ok = 0
        anuladas_ok = 0
        revertidas_ok = 0
        errores = []

        id_inicio = (FacturaEnc.objects.order_by('-id').first().id + 1) if FacturaEnc.objects.exists() else 1
        
        for i in range(1, cantidad + 1):
            self.stdout.write(f"\n--- Ciclo {i}/{cantidad} ---")

            # --- 1. Crear la factura de prueba ---
            enc = FacturaEnc.objects.create(cliente=cliente, uc=usuario)
            FacturaDet.objects.create(
                factura=enc, producto=producto, cantidad=1, precio=producto.precio, uc=usuario
            )
            enc.refresh_from_db()  # la señal post_save actualizo sub_total/total en la BD,
                                     # pero sobre otra instancia -- hay que releer para que
                                     # el objeto en memoria tenga el total real, no 0.

            # --- 2. Emitir ---
            try:
                emitir_factura_sin(enc)
                self.stdout.write(self.style.SUCCESS(
                    f"  Emitida: factura {enc.id}, estado {enc.estado_sin}"
                ))
                emitidas_ok += 1
            except EmisionSinError as e:
                self.stdout.write(self.style.ERROR(f"  ERROR al emitir factura {enc.id}: {e}"))
                errores.append(f"Ciclo {i} (emision): {e}")
                continue
            finally:
                time.sleep(pausa)

            if not con_anulacion:
                continue

            if enc.estado_sin != FacturaEnc.SIN_VALIDADA:
                self.stdout.write(self.style.WARNING(
                    f"  Factura {enc.id} no quedo VALIDADA (estado: {enc.estado_sin}), no se puede anular. Se omite."
                ))
                continue

            # --- 3. Anular ---
            try:
                anular_factura_sin(enc, int(motivo.codigo))
                detalles = FacturaDet.objects.filter(factura=enc)
                for det in detalles:
                    prod = det.producto
                    prod.existencia = int(prod.existencia) + int(det.cantidad)
                    prod.save()
                enc.anulado = True
                enc.motivo_anulacion = motivo.descripcion
                enc.usuario_anulacion = usuario
                enc.save()
                self.stdout.write(self.style.SUCCESS(f"  Anulada: factura {enc.id}"))
                anuladas_ok += 1
            except EmisionSinError as e:
                self.stdout.write(self.style.ERROR(f"  ERROR al anular factura {enc.id}: {e}"))
                errores.append(f"Ciclo {i} (anulacion): {e}")
                continue
            finally:
                time.sleep(pausa)

            # --- 4. Revertir la anulacion ---
            try:
                revertir_anulacion_sin(enc)
                detalles = FacturaDet.objects.filter(factura=enc)
                for det in detalles:
                    prod = det.producto
                    prod.existencia = int(prod.existencia) - int(det.cantidad)
                    prod.save()
                enc.anulado = False
                enc.save()
                self.stdout.write(self.style.SUCCESS(f"  Reversion OK: factura {enc.id}"))
                revertidas_ok += 1
            except EmisionSinError as e:
                self.stdout.write(self.style.ERROR(f"  ERROR al revertir factura {enc.id}: {e}"))
                errores.append(f"Ciclo {i} (reversion): {e}")
            finally:
                time.sleep(pausa)

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(
            f"RESUMEN: {emitidas_ok} emitidas, {anuladas_ok} anuladas, {revertidas_ok} revertidas "
            f"de {cantidad} ciclo(s) intentados."
        ))
        if errores:
            self.stdout.write(self.style.ERROR(f"\n{len(errores)} error(es):"))
            for err in errores:
                self.stdout.write(f"  - {err}")

        # Facturas que quedaron anuladas pero sin revertir (por timeout u
        # otro error puntual en el paso de reversion) -- se listan aparte
        # para poder reintentarlas a mano despues, sin tener que buscarlas.
        pendientes_revertir = FacturaEnc.objects.filter(
            anulado=True, estado_sin=FacturaEnc.SIN_ANULADA, id__gte=id_inicio
        )
        if pendientes_revertir.exists():
            self.stdout.write(self.style.WARNING(
                f"\n{pendientes_revertir.count()} factura(s) quedaron ANULADAS sin revertir "
                f"(reversion fallo, ej. timeout) -- IDs: "
                f"{', '.join(str(f.id) for f in pendientes_revertir)}"
            ))