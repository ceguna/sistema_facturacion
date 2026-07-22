"""
Genera un certificado autofirmado de PRUEBA (no valido ante el SIN) para poder
probar el mecanismo de firma digital sin depender todavia del certificado real
de ADSIB/firmadigital.bo.

Cuando llegue el certificado real (.pem + llave privada .pem generados con
XCA o Jacobitus), este script deja de usarse: simplemente se apunta
directamente a esos archivos en cuf_firma_prototipo/main.py.

Usa la misma estructura de OIDs que documentamos para el CSR boliviano
(ver Integracion_SIN_Referencia.docx, seccion 8), a modo de ensayo.
"""
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ObjectIdentifier
import datetime


def generar_certificado_prueba(
    ruta_llave_privada="certificado_prueba_key.pem",
    ruta_certificado="certificado_prueba_cert.pem",
    nombre_titular="CARLA CECILIA AGUILERA TELLEZ",
    razon_social="CARLA CECILIA AGUILERA TELLEZ",
    nit="3852849010",
):
    # OIDs bolivianos personalizados que vimos en "Generacion CSR para Software"
    OID_DN_QUALIFIER = ObjectIdentifier("2.5.4.46")
    OID_UID_NUMBER = ObjectIdentifier("1.3.6.1.1.1.1.0")
    OID_USER_ID = ObjectIdentifier("0.9.2342.19200300.100.1.1")

    llave_privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    sujeto = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, nombre_titular),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, razon_social),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Facturacion Electronica"),
        x509.NameAttribute(NameOID.TITLE, "Titular"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "BO"),
        x509.NameAttribute(OID_DN_QUALIFIER, "CI"),
        x509.NameAttribute(OID_UID_NUMBER, "3852849"),
        x509.NameAttribute(OID_USER_ID, "0"),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, nit),
        x509.NameAttribute(NameOID.EMAIL_ADDRESS, "ccaguilerat@gmail.com"),
    ])

    certificado = (
        x509.CertificateBuilder()
        .subject_name(sujeto)
        .issuer_name(sujeto)  # autofirmado: emisor = sujeto
        .public_key(llave_privada.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .sign(llave_privada, hashes.SHA256())
    )

    with open(ruta_llave_privada, "wb") as f:
        f.write(llave_privada.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    with open(ruta_certificado, "wb") as f:
        f.write(certificado.public_bytes(serialization.Encoding.PEM))

    print(f"Certificado de PRUEBA generado: {ruta_certificado}")
    print(f"Llave privada de PRUEBA generada: {ruta_llave_privada}")
    print("Recordatorio: este certificado NO es valido ante el SIN, es solo para "
          "probar el mecanismo de firma. Reemplazar por el real cuando este listo.")


if __name__ == "__main__":
    generar_certificado_prueba()
