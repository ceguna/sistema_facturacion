import zeep

BASE = "https://pilotosiatservicios.impuestos.gob.bo"

CONFIRMADOS = {
    "Codigos (CUIS/CUFD)": f"{BASE}/v2/FacturacionCodigos?wsdl",
    "Sincronizacion Catalogos": f"{BASE}/v2/FacturacionSincronizacion?wsdl",
    "Operaciones": f"{BASE}/v2/FacturacionOperaciones?wsdl",
    "Factura Compra-Venta": f"{BASE}/v2/ServicioFacturacionCompraVenta?wsdl",
    "Nota Credito-Debito": f"{BASE}/v2/ServicioFacturacionDocumentoAjuste?wsdl",
}
# Nota: estas 5 rutas vienen confirmadas directamente por el PDF oficial
# "Solicitud de Autorizacion de Sistemas" (Nro. 9454, Codigo de Sistema
# 373A0EA0FBA931B62586), no por prueba y error contra el WSDL. El
# servicio "ServicioFacturacionElectronica" usado antes (que tambien
# respondia) NO es el correcto para Factura Compra-Venta: la ruta
# real y oficial es ServicioFacturacionCompraVenta.

with open("wsdl_operaciones.txt", "w", encoding="utf-8") as out:
    for nombre, url in CONFIRMADOS.items():
        out.write(f"\n{'='*70}\n{nombre}\n{url}\n{'='*70}\n")
        try:
            client = zeep.Client(url)
            for service in client.wsdl.services.values():
                for port in service.ports.values():
                    for op in port.binding._operations.values():
                        out.write(f" - {op.name}\n")
        except Exception as e:
            out.write(f"  ERROR: {e}\n")

# --- Buscando el servicio de Autenticacion (Generacion de Token) ---
    # Este NO esta confirmado todavia -- probamos varios nombres posibles
    # siguiendo el mismo patron que los demas servicios.
    out.write(f"\n\n{'#'*70}\n# CANDIDATOS - Servicio de Autenticacion (sin confirmar)\n{'#'*70}\n")
    candidatos_auth = [
        f"{BASE}/v2/ServicioAutenticacionSoap?wsdl",
        f"{BASE}/v2/AutenticacionSoap?wsdl",
        f"{BASE}/v2/FacturacionAutenticacionSoap?wsdl",
        f"{BASE}/v1/ServicioAutenticacionSoap?wsdl",
        f"{BASE}/v2/FacturacionAutenticacion?wsdl",
        f"{BASE}/v2/Autenticacion?wsdl",
        f"{BASE}/v2/ServicioAutenticacion?wsdl",
        f"{BASE}/v2/GeneracionToken?wsdl",
        f"{BASE}/v2/ServicioGeneracionToken?wsdl",
        f"{BASE}/v1/FacturacionAutenticacion?wsdl",
        f"{BASE}/v1/Autenticacion?wsdl",
    ]
    for url in candidatos_auth:
        out.write(f"\nProbando: {url}\n")
        try:
            client = zeep.Client(url)
            out.write("  >>> CONECTO. Operaciones:\n")
            for service in client.wsdl.services.values():
                for port in service.ports.values():
                    for op in port.binding._operations.values():
                        out.write(f"     - {op.name}\n")
        except Exception as e:
            out.write(f"  no responde ({type(e).__name__})\n")

print("Listo. Revisa el archivo wsdl_operaciones.txt")