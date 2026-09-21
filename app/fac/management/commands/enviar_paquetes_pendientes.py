"""
Fase C (contingencia, 21/09/2026): tarea programada que cierra
eventos significativos abiertos (arma y envia el paquete de las
facturas offline pendientes) y valida los paquetes ya enviados, sin
que nadie tenga que invocar fe.services a mano -- es lo que hace que
la SALIDA del modo offline sea de verdad automatica (checklist SIN
Fase II, punto 14; el punto 8 -- envio del paquete dentro de 48h -- ya
se cumple en el momento en que cerrar_evento_y_enviar_paquete tiene
exito, no hace falta esperar a la validacion para eso).

Pensada para correr sola, sin supervision, cada 15-30 minutos. En
desarrollo (Windows) se puede agregar al Task Scheduler; en produccion
el hosting real es Hetzner Cloud con Docker (ver CLAUDE.md), asi que
ahi corresponde un cron -- por ejemplo, un cron del propio contenedor
o del host llamando "docker compose exec web python manage.py
enviar_paquetes_pendientes" cada 15-30 minutos. Si no hay nada
pendiente, no hace nada. Si el SIN sigue inalcanzable, no rompe nada
-- deja todo como estaba y reintenta en el proximo ciclo.

Uso:
    python manage.py enviar_paquetes_pendientes
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from fac.models import EventoSignificativo, FacturaEnc, PaqueteFacturas
from fe.services import (
    cerrar_evento_y_enviar_paquete, validar_paquete_sin,
    EmisionSinError, SinConexionError,
)

HORAS_LIMITE_ENVIO_EVENTO = 48
HORAS_AVISO_PROXIMO_AL_LIMITE = 4


class Command(BaseCommand):
    help = (
        "Cierra eventos significativos abiertos (envia el paquete de facturas "
        "offline pendientes) y valida paquetes ya enviados -- Fase C de la "
        "contingencia SIN. Pensado para correr en un scheduler cada 15-30 minutos."
    )

    def handle(self, *args, **options):
        self._cerrar_eventos_pendientes()
        self._validar_paquetes_enviados()

    def _cerrar_eventos_pendientes(self):
        eventos = EventoSignificativo.objects.filter(
            estado_evento=EventoSignificativo.ABIERTO,
            facturas__paquete__isnull=True,
            facturas__estado_sin=FacturaEnc.SIN_PENDIENTE,
        ).distinct()

        if not eventos.exists():
            self.stdout.write("Sin eventos abiertos con facturas pendientes de empaquetar.")
            return

        for evento in eventos:
            limite = evento.fecha_hora_inicio + timedelta(hours=HORAS_LIMITE_ENVIO_EVENTO)
            restante = limite - timezone.now()

            self.stdout.write(
                f"Evento #{evento.id} ({evento.sucursal}, PV {evento.codigo_punto_venta}): "
                f"intentando cerrar y enviar paquete..."
            )
            try:
                paquete = cerrar_evento_y_enviar_paquete(evento)
                self.stdout.write(self.style.SUCCESS(
                    f"  OK -- paquete #{paquete.id} enviado ({paquete.cantidad_facturas} "
                    f"factura(s)), codigoRecepcion={paquete.codigo_recepcion}"
                ))
            except SinConexionError as e:
                if restante <= timedelta(0):
                    self.stdout.write(self.style.ERROR(
                        f"  SIGUE SIN CONEXION y ya se pasó el plazo de {HORAS_LIMITE_ENVIO_EVENTO}h "
                        f"para enviar el paquete (evento abierto desde {evento.fecha_hora_inicio}). "
                        "Requiere atención manual."
                    ))
                elif restante <= timedelta(hours=HORAS_AVISO_PROXIMO_AL_LIMITE):
                    self.stdout.write(self.style.WARNING(
                        f"  Sigue sin conexión -- quedan menos de {HORAS_AVISO_PROXIMO_AL_LIMITE}h "
                        f"para el plazo de {HORAS_LIMITE_ENVIO_EVENTO}h. ({e})"
                    ))
                else:
                    self.stdout.write(self.style.WARNING(
                        f"  Sigue sin conexión al SIN -- se reintenta en el próximo ciclo. ({e})"
                    ))
            except EmisionSinError as e:
                self.stdout.write(self.style.ERROR(
                    f"  El SIN rechazó el evento/paquete del evento #{evento.id} -- "
                    f"requiere revisión manual. ({e})"
                ))

    def _validar_paquetes_enviados(self):
        paquetes = PaqueteFacturas.objects.filter(estado_paquete=PaqueteFacturas.ENVIADO)

        if not paquetes.exists():
            self.stdout.write("Sin paquetes enviados pendientes de validar.")
            return

        for paquete in paquetes:
            self.stdout.write(f"Paquete #{paquete.id} (evento #{paquete.evento_id}): validando recepción...")
            try:
                resultado = validar_paquete_sin(paquete)
                if resultado.estado_paquete == PaqueteFacturas.VALIDADO:
                    self.stdout.write(self.style.SUCCESS(
                        f"  Validado por el SIN -- {resultado.cantidad_facturas} factura(s) "
                        "ahora en estado Validada."
                    ))
                else:
                    self.stdout.write(self.style.ERROR(
                        f"  Rechazado por el SIN -- {resultado.mensaje_sin}"
                    ))
            except SinConexionError as e:
                self.stdout.write(self.style.WARNING(
                    f"  Sigue sin conexión al SIN -- se reintenta en el próximo ciclo. ({e})"
                ))
            except EmisionSinError as e:
                self.stdout.write(self.style.ERROR(
                    f"  Error al validar el paquete #{paquete.id} -- requiere revisión manual. ({e})"
                ))
