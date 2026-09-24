"""
Suite de pruebas de las piezas PURAS de la integracion SIN (fe) --
calculo de CUF y armado de XML. Deliberadamente NO cubre
emitir_factura_sin/anular_factura_sin/etc: esas funciones hablan con
el SOAP real del SIN Piloto y dependen de un certificado real
(prototipo/sin/certificado_real/, gitignored) -- no se pueden probar
con datos de prueba sin tocar la red real, y este proyecto ya usa la
libreria/base de desarrollo contra el Piloto real para eso (ver
CLAUDE.md, seccion "Environment"). Lo que SI se puede aislar sin red
son las funciones de calculo puro, y son las que mas conviene blindar
con pruebas automaticas (un error de un solo digito en el CUF o el XML
significa una factura rechazada por el SIN en produccion real).

Como correrla:
    python manage.py test fe
"""
import datetime

from django.test import TestCase

from fe.cuf import calcular_cuf
from fe.factura_xml import construir_factura_xml


class CalcularCufTests(TestCase):

    def test_coincide_con_el_ejemplo_oficial_del_sin(self):
        """
        CONFIRMADO contra el ejemplo oficial del SIN (ver
        prototipo/sin/cuf.py, bloque __main__) -- estos valores y el
        CUF esperado salen de ahi tal cual, es la misma verificacion
        que ya se habia hecho a mano, ahora automatizada para que
        cualquier cambio futuro en calcular_cuf() que rompa el
        algoritmo se note de inmediato (y no recien al facturar contra
        el SIN real).
        """
        cuf = calcular_cuf(
            nit=123456789,
            fecha_hora=datetime.datetime(2019, 1, 13, 16, 37, 21, 231000),
            codigo_sucursal=0,
            codigo_modalidad=1,          # Electronica en Linea
            codigo_tipo_emision=1,       # Online
            codigo_tipo_factura=1,       # Con derecho a credito fiscal
            codigo_documento_sector=1,   # Compra y Venta
            numero_factura=1,
            codigo_punto_venta=0,
            codigo_control="A19E23EF34124CD",
        )
        esperado = "8727F63A15F8976591FDDE5B387C5D015A29E06A1A19E23EF34124CD"
        self.assertEqual(cuf, esperado)

    def test_es_deterministico(self):
        kwargs = dict(
            nit=987654321, fecha_hora=datetime.datetime(2026, 9, 23, 10, 0, 0),
            codigo_sucursal=1, codigo_modalidad=1, codigo_tipo_emision=1,
            codigo_tipo_factura=1, codigo_documento_sector=1, numero_factura=42,
            codigo_punto_venta=0, codigo_control="ABCDEF0123456",
        )
        self.assertEqual(calcular_cuf(**kwargs), calcular_cuf(**kwargs))

    def test_cambiar_numero_factura_cambia_el_cuf(self):
        kwargs = dict(
            nit=987654321, fecha_hora=datetime.datetime(2026, 9, 23, 10, 0, 0),
            codigo_sucursal=1, codigo_modalidad=1, codigo_tipo_emision=1,
            codigo_tipo_factura=1, codigo_documento_sector=1,
            codigo_punto_venta=0, codigo_control="ABCDEF0123456",
        )
        cuf_1 = calcular_cuf(numero_factura=1, **kwargs)
        cuf_2 = calcular_cuf(numero_factura=2, **kwargs)
        self.assertNotEqual(cuf_1, cuf_2)

    def test_termina_con_el_codigo_de_control_literal(self):
        cuf = calcular_cuf(
            nit=123456789, fecha_hora=datetime.datetime(2026, 9, 23, 10, 0, 0),
            codigo_sucursal=0, codigo_modalidad=1, codigo_tipo_emision=1,
            codigo_tipo_factura=1, codigo_documento_sector=1, numero_factura=5,
            codigo_punto_venta=0, codigo_control="XYZ999",
        )
        self.assertTrue(cuf.endswith("XYZ999"))


class ConstruirFacturaXmlTests(TestCase):
    """Estructura del XML de Factura de Compra y Venta (Electronica en
    Linea) -- ver fe/factura_xml.py. No valida contra el XSD real (eso
    ya lo hace fe/services.py en el flujo de emision real, con el
    archivo de prototipo/sin/), pero si confirma que el orden de campos,
    los valores y el manejo de nillable/obligatorio son correctos --
    un solo campo en el orden equivocado o mal marcado nillable hace
    que el SIN rechace la factura completa.
    """

    def _cabecera_valida(self, **overrides):
        base = {
            "nitEmisor": "123456789", "razonSocialEmisor": "EMPRESA TEST",
            "municipio": "SANTA CRUZ DE LA SIERRA", "telefono": None,
            "numeroFactura": "1", "cuf": "CUF-TEST", "cufd": "CUFD-TEST",
            "codigoSucursal": "0", "direccion": "CALLE FALSA 123",
            "codigoPuntoVenta": None, "fechaEmision": "2026-09-23T10:00:00.000",
            "nombreRazonSocial": None, "codigoTipoDocumentoIdentidad": "1",
            "numeroDocumento": "7777777", "complemento": None,
            "codigoCliente": "0", "codigoMetodoPago": "1", "numeroTarjeta": None,
            "montoTotal": "100.00", "montoTotalSujetoIva": "100.00",
            "codigoMoneda": "1", "tipoCambio": "1.00", "montoTotalMoneda": "100.00",
            "montoGiftCard": None, "descuentoAdicional": "0.00",
            "codigoExcepcion": None, "cafc": None, "leyenda": "LEYENDA DE PRUEBA",
            "usuario": "usuario_test", "codigoDocumentoSector": "1",
        }
        base.update(overrides)
        return base

    def _detalle_valido(self, **overrides):
        base = {
            "actividadEconomica": "620000", "codigoProductoSin": "99999",
            "codigoProducto": "PROD-1", "descripcion": "Producto de prueba",
            "cantidad": "1", "unidadMedida": "58", "precioUnitario": "100.00",
            "montoDescuento": "0.00", "subTotal": "100.00",
            "numeroSerie": None, "numeroImei": None,
        }
        base.update(overrides)
        return base

    def test_arma_el_root_correcto_con_namespace_xsi(self):
        root = construir_factura_xml(self._cabecera_valida(), [self._detalle_valido()])
        self.assertEqual(root.tag, "facturaElectronicaCompraVenta")
        self.assertEqual(
            root.get("{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation"),
            "facturaElectronicaCompraVenta.xsd",
        )

    def test_cabecera_conserva_los_valores_en_el_orden_esperado(self):
        root = construir_factura_xml(self._cabecera_valida(), [self._detalle_valido()])
        cab = root.find("cabecera")
        self.assertEqual(cab.find("nitEmisor").text, "123456789")
        self.assertEqual(cab.find("montoTotal").text, "100.00")
        self.assertEqual(cab.find("leyenda").text, "LEYENDA DE PRUEBA")
        # Orden real de los hijos == ORDEN_CABECERA (el SIN es
        # posicional en algunos parsers XML, no solo por nombre).
        tags = [el.tag for el in cab]
        self.assertEqual(tags[0], "nitEmisor")
        self.assertEqual(tags[-1], "codigoDocumentoSector")

    def test_detalle_incluye_una_linea_por_producto(self):
        root = construir_factura_xml(
            self._cabecera_valida(),
            [self._detalle_valido(codigoProducto="A"), self._detalle_valido(codigoProducto="B")],
        )
        detalles = root.findall("detalle")
        self.assertEqual(len(detalles), 2)
        self.assertEqual(detalles[0].find("codigoProducto").text, "A")
        self.assertEqual(detalles[1].find("codigoProducto").text, "B")

    def test_campo_nillable_en_none_se_marca_xsi_nil(self):
        root = construir_factura_xml(self._cabecera_valida(telefono=None), [self._detalle_valido()])
        campo = root.find("cabecera").find("telefono")
        self.assertEqual(campo.get("{http://www.w3.org/2001/XMLSchema-instance}nil"), "true")
        self.assertIsNone(campo.text)

    def test_campo_obligatorio_en_none_lanza_error_claro(self):
        """
        Sin este chequeo, un campo obligatorio faltante generaria un
        XML invalido que el SIN recien rechazaria del otro lado -- se
        prefiere fallar rapido y local, con un mensaje que diga
        exactamente que campo falta.
        """
        with self.assertRaises(ValueError) as ctx:
            construir_factura_xml(self._cabecera_valida(nitEmisor=None), [self._detalle_valido()])
        self.assertIn("nitEmisor", str(ctx.exception))

    def test_montodescuento_por_defecto_es_cero_si_no_se_pasa(self):
        detalle_sin_descuento = self._detalle_valido()
        del detalle_sin_descuento["montoDescuento"]
        root = construir_factura_xml(self._cabecera_valida(), [detalle_sin_descuento])
        self.assertEqual(root.find("detalle").find("montoDescuento").text, "0")


class SolicitarCuisSucursalTests(TestCase):
    """Boton "Solicitar CUIS" por sucursal (24/09/2026). El SIN se
    simula (nunca se toca la red real): se reemplaza _cliente_soap por
    un cliente falso que devuelve la respuesta que se quiera."""

    def setUp(self):
        from fe.models import Empresa, Sucursal
        self.empresa = Empresa.objects.create(
            razon_social="EMPRESA CUIS", nit="123456789", codigo_sistema="SISTEMA-TEST")
        self.sucursal = Sucursal.objects.create(
            empresa=self.empresa, codigo_sucursal=1, nombre="Cochabamba")

    def _cliente_falso(self, respuesta):
        from unittest.mock import MagicMock
        cliente = MagicMock()
        cliente.service.cuis.return_value = respuesta
        return cliente

    def test_guarda_cuis_y_vigencia_cuando_el_sin_lo_entrega(self):
        from unittest.mock import patch
        from fe import services
        resp = {"transaccion": True, "codigo": "CUIS-NUEVO",
                "fechaVigencia": datetime.datetime(2027, 9, 24, 12, 0), "mensajesList": None}
        cliente = self._cliente_falso(resp)
        with patch.object(services, "_cliente_soap", return_value=cliente), \
             patch.object(services, "_obtener_token", return_value="TOKEN"):
            codigo = services.solicitar_cuis_sucursal_sin(self.sucursal)
        self.assertEqual(codigo, "CUIS-NUEVO")
        self.sucursal.refresh_from_db()
        self.assertEqual(self.sucursal.codigo_cuis, "CUIS-NUEVO")
        self.assertIsNotNone(self.sucursal.fecha_vigencia_cuis)
        solicitud = cliente.service.cuis.call_args.kwargs["SolicitudCuis"]
        self.assertEqual(solicitud["codigoSucursal"], 1)
        self.assertEqual(solicitud["codigoPuntoVenta"], 0)

    def test_rechazo_del_sin_muestra_su_mensaje_y_no_guarda_nada(self):
        from unittest.mock import patch
        from fe import services
        resp = {"transaccion": False, "codigo": None,
                "mensajesList": [{"codigo": 1, "descripcion": "SUCURSAL NO REGISTRADA"}]}
        with patch.object(services, "_cliente_soap", return_value=self._cliente_falso(resp)), \
             patch.object(services, "_obtener_token", return_value="TOKEN"):
            with self.assertRaises(services.EmisionSinError) as ctx:
                services.solicitar_cuis_sucursal_sin(self.sucursal)
        self.assertIn("SUCURSAL NO REGISTRADA", str(ctx.exception))
        self.sucursal.refresh_from_db()
        self.assertFalse(self.sucursal.codigo_cuis)

    def test_no_vuelve_a_pedir_si_el_cuis_sigue_vigente(self):
        from unittest.mock import patch
        from django.utils import timezone
        from fe import services
        self.sucursal.codigo_cuis = "CUIS-VIGENTE"
        self.sucursal.fecha_vigencia_cuis = timezone.now() + datetime.timedelta(days=100)
        self.sucursal.save()
        cliente = self._cliente_falso({})
        with patch.object(services, "_cliente_soap", return_value=cliente):
            with self.assertRaises(services.EmisionSinError):
                services.solicitar_cuis_sucursal_sin(self.sucursal)
        cliente.service.cuis.assert_not_called()

    def test_requiere_codigo_de_sistema_de_la_empresa(self):
        from fe import services
        self.empresa.codigo_sistema = None
        self.empresa.save()
        with self.assertRaises(services.EmisionSinError):
            services.solicitar_cuis_sucursal_sin(self.sucursal)
