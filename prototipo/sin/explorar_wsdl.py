import zeep

BASE = "https://pilotosiatservicios.impuestos.gob.bo"

# Confirmados en la corrida anterior
CONFIRMADOS = {
    "Codigos (CUIS/CUFD)": f"{BASE}/v2/FacturacionCodigos?wsdl",
    "Sincronizacion Catalogos": f"{BASE}/v2/FacturacionSincronizacion?wsdl",
    "Facturacion Electronica": f"{BASE}/v2/ServicioFacturacionElectronica?wsdl",
}

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

print("Listo. Revisa el archivo wsdl_operaciones.txt")