"""
prototipo/sin/probar_autenticacion.py — v4
Endpoint confirmado: siatrest.impuestos.gob.bo
Body confirmado en orden correcto (XSD exige orden alfabético de campos).
Ahora ajustando SOAPAction.
"""

import requests
from lxml import etree

URL = "https://siatrest.impuestos.gob.bo/v1/ServicioAutenticacionSoap"

NIT = "3852849010"
LOGIN = "millenniumlibreria@hotmail.com"
PASSWORD = "Libreri@2025+"

# Orden alfabético confirmado por el error del SIN:
# client, ip, login, nit, password, tipoClienteId, tipoUsuarioId
ENVELOPE = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:siat="https://siat.impuestos.gob.bo/">
   <soapenv:Header/>
   <soapenv:Body>
      <siat:token>
         <DatosUsuarioRequest>
            <client>0</client>
            <ip></ip>
            <login>{LOGIN}</login>
            <nit>{NIT}</nit>
            <password>{PASSWORD}</password>
            <tipoClienteId>0</tipoClienteId>
            <tipoUsuarioId>0</tipoUsuarioId>
         </DatosUsuarioRequest>
      </siat:token>
   </soapenv:Body>
</soapenv:Envelope>"""

BASE_HEADERS = {
    "Content-Type": "text/xml;charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/xml",
}

# Candidatos de SOAPAction a probar en orden
CANDIDATOS_SOAPACTION = [
    "",                                                       # vacío (a veces basta)
    "token",
    "\"\"",                                                    # literal vacío entre comillas
    "https://siat.impuestos.gob.bo/ServicioAutenticacionSoap/token",
    "https://siat.impuestos.gob.bo/ServicioAutenticacionSoap",
    "http://siat.impuestos.gob.bo/token",
]


def probar(soapaction, sin_header=False):
    headers = dict(BASE_HEADERS)
    etiqueta = "SIN header SOAPAction" if sin_header else f"SOAPAction='{soapaction}'"
    if not sin_header:
        headers["SOAPAction"] = soapaction

    print(f"\n=== Probando: {etiqueta} ===")
    resp = requests.post(URL, data=ENVELOPE.encode("utf-8"), headers=headers, timeout=30)
    print(f"Status: {resp.status_code}")
    print(f"Cuerpo: {resp.text[:800]}")

    # Si ya no es el error de SOAPAction, paramos: encontramos el valor correcto
    # (o llegamos a un error distinto que ya es progreso real)
    if "does not match an operation" not in resp.text:
        print("\n>>> Este SOAPAction pasó la validación de rutina. Revisar respuesta completa arriba. <<<")
        return True
    return False


if __name__ == "__main__":
    # Primero probamos sin la cabecera SOAPAction directamente
    if probar(None, sin_header=True):
        exit()

    for candidato in CANDIDATOS_SOAPACTION:
        if probar(candidato):
            break
    else:
        print("\nNinguno de los candidatos funcionó. Habría que inspeccionar el WSDL real si aparece,"
              " o revisar si el servicio espera SOAP 1.2 en vez de 1.1 (Content-Type distinto).")