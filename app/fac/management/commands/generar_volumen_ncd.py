"""
Genera volumen de "casos correctos" de Nota de Credito-Debito para
subir el porcentaje de las etapas de certificacion Piloto que dependen
de ella (IV. Emision Individual, VII. Anulacion, VIII. Firma Digital,
XI. Reversion -- ver instructivo NCD Etapas IV/VII/VIII/XI para el
detalle completo de como el dashboard del SIN cuenta cada una).

Etapa XI CONFIRMADA el 15/09/2026 via el dashboard real del SIN (fila
especifica de NCD: codigoDocumentoSector=24/tipoFacturaDocumento=3,
pide reversionAnulacionDocumentoAjuste igual que la de una factura
normal). --revertir-ncd suma esa etapa; implica --anular-ncd (no tiene
sentido revertir una anulacion que no se hizo).

Reutiliza los mismos servicios reales ya probados (emitir_factura_sin,
emitir_nota_credito_debito_sin, anular_nota_credito_debito_sin,
revertir_anulacion_nota_credito_debito_sin) -- no duplica logica, solo
la ejecuta en bucle con pausa entre llamadas.

IMPORTANTE -- cada ciclo genera una NCD real y (con --anular-ncd /
--revertir-ncd) una anulacion y/o reversion real ante el SIN Piloto.
Correr con --cantidad chico primero (1-3) para confirmar que un ciclo
entero funciona antes de pedir volumen grande.

Uso:
    python manage.py generar_volumen_ncd --cantidad 3
    python manage.py generar_volumen_ncd --cantidad 125 --anular-ncd --pausa 3
    python manage.py generar_volumen_ncd --cantidad 125 --revertir-ncd --pausa 3
    python manage.py generar_volumen_ncd --cantidad 125 --codigo-punto-venta 1
"""
import time

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User

from fac.models import Cliente, FacturaEnc, FacturaDet, NotaCreditoDebito
from inv.models import Producto, ajustar_stock_sucursal
from catalogos.models import CatalogoSIN
from fe.models import Sucursal, PuntoVenta
from fe.services import (
    emitir_factura_sin, emitir_nota_credito_debito_sin,
    anular_nota_credito_debito_sin, revertir_anulacion_nota_credito_debito_sin,
    EmisionSinError,
)


class Command(BaseCommand):
    help = (
        "Genera facturas de prueba + Nota de Credito-Debito (y opcionalmente su "
        "anulacion) contra el SIN Piloto, para subir el volumen de casos correctos "
        "de las Etapas IV/VII/VIII. Usar SOLO contra la base de datos local de "
        "pruebas, nunca contra produccion."
    )

    def add_arguments(self, parser):
        parser.add_argument('--cantidad', type=int, default=3,
                             help='Cuantos ciclos completos (factura + NCD [+ anulacion]) ejecutar.')
        parser.add_argument('--pausa', type=float, default=3.0,
                             help='Segundos de espera entre cada llamada al SIN.')
        parser.add_argument('--anular-ncd', action='store_true',
                             help='Ademas de emitir la NCD, anularla (suma Etapa VII). '
                                  'Sin este flag, solo se emite (Etapa IV/VIII).')
        parser.add_argument('--revertir-ncd', action='store_true',
                             help='Ademas de anular la NCD, revertir esa anulacion (suma Etapa XI). '
                                  'Implica --anular-ncd.')
        parser.add_argument('--usuario', type=str, default=None,
                             help='Username a usar para uc/usuario_autorizacion. Por defecto, el primer superusuario.')
        parser.add_argument(
            '--codigo-punto-venta', type=int, default=0,
            help='Punto de venta a usar en emision de factura, NCD y anulacion. 0 (default) = '
                 'casa matriz implicito. Cualquier otro valor requiere que ese PuntoVenta '
                 'ya este registrado localmente con su propio CUIS cargado.'
        )

    def handle(self, *args, **options):
        cantidad = options['cantidad']
        pausa = options['pausa']
        con_reversion_ncd = options['revertir_ncd']
        con_anulacion_ncd = options['anular_ncd'] or con_reversion_ncd
        codigo_punto_venta = options['codigo_punto_venta']

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
        if not cliente.nit and not cliente.ci:
            raise CommandError(f"El cliente '{cliente}' no tiene CI ni NIT cargado -- la NCD lo exige.")

        producto = next((p for p in Producto.objects.filter(estado=True) if p.homologado_sin), None)
        if not producto:
            raise CommandError(
                "No hay ningun Producto homologado (actividad + codigo SIN + unidad con codigo_sin). "
                "Homologue al menos uno desde /inv/productos/ antes de correr este comando."
            )

        if codigo_punto_venta != 0:
            sucursal = Sucursal.objects.filter(codigo_sucursal=0).first()
            punto_venta = PuntoVenta.objects.filter(
                sucursal=sucursal, codigo_punto_venta=codigo_punto_venta
            ).first() if sucursal else None
            if not punto_venta:
                raise CommandError(
                    f"No existe un PuntoVenta con código {codigo_punto_venta} registrado localmente."
                )
            if not punto_venta.codigo_cuis:
                raise CommandError(
                    f"El PuntoVenta {codigo_punto_venta} ('{punto_venta.nombre}') "
                    "no tiene CUIS propio cargado todavía."
                )

        # Colchon de stock: la factura descuenta 1, la NCD validada
        # devuelve esa misma unidad -- neto 0 por ciclo. Igual se sube
        # un colchon chico por si algun ciclo queda a medias (factura
        # emitida pero NCD rechazada, por ejemplo).
        stock_necesario = cantidad + 10
        if producto.existencia < stock_necesario:
            stock_original = producto.existencia
            # Fase 2 (20/09/2026): existencia ya no se asigna directo --
            # ver el mismo comentario en generar_volumen_sin.py.
            casa_matriz = Sucursal.objects.filter(codigo_sucursal=0).first()
            ajustar_stock_sucursal(producto.id, casa_matriz, stock_necesario - stock_original)
            producto.refresh_from_db(fields=['existencia'])
            self.stdout.write(self.style.WARNING(
                f"Existencia de '{producto.descripcion}' insuficiente para {cantidad} ciclos "
                f"(tenia {stock_original}). Se subio temporalmente a {stock_necesario} para la prueba."
            ))

        motivo_ncd = None
        if con_anulacion_ncd:
            # Motivo especifico para NCD -- confirmado en el catalogo
            # sincronizado (MOTIVOS_ANULACION incluye 'NOTA DE
            # CREDITO-DEBITO MAL EMITIDA' como entrada propia).
            motivo_ncd = CatalogoSIN.objects.filter(
                tipo_catalogo=CatalogoSIN.TipoCatalogo.MOTIVOS_ANULACION,
                vigente=True, descripcion__icontains='CREDITO-DEBITO'
            ).order_by('codigo').first()
            if not motivo_ncd:
                raise CommandError(
                    "No se encontro en el catalogo local un motivo de anulacion para NCD "
                    "('...CREDITO-DEBITO...' en MOTIVOS_ANULACION). Sincronice el catalogo "
                    "(sincronizar_catalogos) antes de usar --anular-ncd."
                )

        self.stdout.write(self.style.WARNING(
            f"Generando {cantidad} ciclo(s) de NCD — cliente: {cliente}, producto: {producto.descripcion}, "
            f"punto de venta: {codigo_punto_venta}, pausa: {pausa}s entre llamadas, "
            f"anular NCD: {con_anulacion_ncd}, revertir anulacion NCD: {con_reversion_ncd}"
        ))

        facturas_ok = 0
        ncd_emitidas_ok = 0
        ncd_anuladas_ok = 0
        ncd_revertidas_ok = 0
        errores = []

        id_inicio_ncd = (NotaCreditoDebito.objects.order_by('-id').first().id + 1) \
            if NotaCreditoDebito.objects.exists() else 1

        for i in range(1, cantidad + 1):
            self.stdout.write(f"\n--- Ciclo {i}/{cantidad} ---")

            # --- 1. Crear y emitir la factura base ---
            enc = FacturaEnc.objects.create(cliente=cliente, uc=usuario)
            FacturaDet.objects.create(
                factura=enc, producto=producto, cantidad=1, precio=producto.precio, uc=usuario
            )
            enc.refresh_from_db()

            try:
                emitir_factura_sin(enc, codigo_punto_venta=codigo_punto_venta)
                self.stdout.write(self.style.SUCCESS(
                    f"  Factura {enc.id} emitida, estado {enc.estado_sin}"
                ))
                facturas_ok += 1
            except EmisionSinError as e:
                self.stdout.write(self.style.ERROR(f"  ERROR al emitir factura {enc.id}: {e}"))
                errores.append(f"Ciclo {i} (emision factura): {e}")
                continue
            finally:
                time.sleep(pausa)

            if enc.estado_sin != FacturaEnc.SIN_VALIDADA:
                self.stdout.write(self.style.WARNING(
                    f"  Factura {enc.id} no quedo VALIDADA (estado: {enc.estado_sin}), "
                    "no se le puede emitir una NCD. Se omite este ciclo."
                ))
                continue

            # --- 2. Crear y emitir la NCD (devolucion total) ---
            monto_efectivo = round(enc.total * 0.13, 2)
            ncd = NotaCreditoDebito.objects.create(
                factura_original=enc,
                motivo='Generado por generar_volumen_ncd (certificacion Piloto)',
                monto_total_original=enc.total,
                monto_total_devuelto=enc.total,
                monto_descuento_credito_debito=0,
                monto_efectivo_credito_debito=monto_efectivo,
                usuario_autorizacion=usuario,
                uc=usuario,
            )
            try:
                emitir_nota_credito_debito_sin(ncd, codigo_punto_venta=codigo_punto_venta)
                self.stdout.write(self.style.SUCCESS(
                    f"  NCD {ncd.id} emitida sobre factura {enc.id}, estado {ncd.estado_sin}"
                ))
                ncd_emitidas_ok += 1
            except EmisionSinError as e:
                self.stdout.write(self.style.ERROR(f"  ERROR al emitir NCD {ncd.id}: {e}"))
                errores.append(f"Ciclo {i} (emision NCD {ncd.id}): {e}")
                continue
            finally:
                time.sleep(pausa)

            if not con_anulacion_ncd:
                continue

            if ncd.estado_sin != NotaCreditoDebito.SIN_VALIDADA:
                self.stdout.write(self.style.WARNING(
                    f"  NCD {ncd.id} no quedo VALIDADA (estado: {ncd.estado_sin}), "
                    "no se puede anular. Se omite."
                ))
                continue

            # --- 3. Anular la NCD (Etapa VII) ---
            try:
                anular_nota_credito_debito_sin(ncd, int(motivo_ncd.codigo), codigo_punto_venta=codigo_punto_venta)
                ncd.anulada = True
                ncd.motivo_anulacion = motivo_ncd.descripcion
                ncd.usuario_anulacion = usuario
                ncd.save()
                self.stdout.write(self.style.SUCCESS(f"  NCD {ncd.id} anulada ante el SIN."))
                ncd_anuladas_ok += 1
            except EmisionSinError as e:
                self.stdout.write(self.style.ERROR(f"  ERROR al anular NCD {ncd.id}: {e}"))
                errores.append(f"Ciclo {i} (anulacion NCD {ncd.id}): {e}")
                continue
            finally:
                time.sleep(pausa)

            if not con_reversion_ncd:
                continue

            # --- 4. Revertir la anulacion de la NCD (Etapa XI) ---
            try:
                revertir_anulacion_nota_credito_debito_sin(ncd, codigo_punto_venta=codigo_punto_venta)
                ncd.anulada = False
                ncd.save()
                self.stdout.write(self.style.SUCCESS(f"  Anulacion de NCD {ncd.id} revertida ante el SIN."))
                ncd_revertidas_ok += 1
            except EmisionSinError as e:
                self.stdout.write(self.style.ERROR(f"  ERROR al revertir anulacion de NCD {ncd.id}: {e}"))
                errores.append(f"Ciclo {i} (reversion anulacion NCD {ncd.id}): {e}")
            finally:
                time.sleep(pausa)

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(
            f"RESUMEN: {facturas_ok} factura(s) emitidas, {ncd_emitidas_ok} NCD emitidas, "
            f"{ncd_anuladas_ok} NCD anuladas, {ncd_revertidas_ok} anulaciones de NCD revertidas, "
            f"de {cantidad} ciclo(s) intentados."
        ))
        if errores:
            self.stdout.write(self.style.ERROR(f"\n{len(errores)} error(es):"))
            for err in errores:
                self.stdout.write(f"  - {err}")

        self.stdout.write(self.style.WARNING(
            "\nRecordatorio: el dashboard del SIN puede ir adelantado respecto a este "
            "resumen si algun timeout hizo perder la confirmacion aunque el envio se "
            "haya procesado del lado de ellos -- revisar el dashboard real, no solo "
            "este resumen impreso, antes de decidir si hace falta correr mas volumen."
        ))

        ncds_generadas = NotaCreditoDebito.objects.filter(id__gte=id_inicio_ncd)
        pendientes = ncds_generadas.filter(estado_sin=NotaCreditoDebito.SIN_PENDIENTE)
        if pendientes.exists():
            self.stdout.write(self.style.WARNING(
                f"\n{pendientes.count()} NCD quedaron PENDIENTE (901, paquete en revision) -- "
                f"IDs: {', '.join(str(n.id) for n in pendientes)}. No hay todavia un mecanismo "
                "para volver a consultarlas mas tarde (verificacionEstadoDocumentoAjuste, ver "
                "seccion 6 del instructivo -- mejora futura, no bloqueante)."
            ))
