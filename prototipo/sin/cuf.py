"""
Calculo del CUF (Codigo Unico de Factura).

CONFIRMADO Y VERIFICADO contra el ejemplo oficial de
siatinfo.impuestos.gob.bo/index.php/facturacion-en-linea/algoritmos-utilizados
(paginas "Algoritmo Modulo 11", "Generacion CUF" y "Algoritmo Base 16").

El resultado de esta implementacion fue verificado byte a byte contra el
ejemplo oficial (NIT=123456789, fecha=2019-01-13T16:37:21.231, etc.) y
produce exactamente el mismo string hexadecimal que documenta el SIN:
    8727F63A15F8976591FDDE5B387C5D015A29E06A1

IMPORTANTE: el CUF final NO se calcula 100% localmente. Esta funcion produce
la parte "local" (54 digitos -> hexadecimal). El CUF completo que va en el
XML se arma concatenando ese resultado con el "codigoControl" que devuelve
el SIN en la respuesta del servicio solicitudCufd (ver ejemplo oficial,
paso 5). O sea: no se puede tener el CUF definitivo sin haber pedido antes
el CUFD del dia -- son cosas encadenadas.
"""
import datetime

# Longitud exacta de cada campo, segun la tabla oficial "Generacion CUF".
LONGITUDES = {
    "nit": 13,
    "fecha_hora": 17,
    "sucursal": 4,
    "modalidad": 1,
    "tipo_emision": 1,
    "tipo_factura": 1,
    "tipo_documento_sector": 2,
    "numero_factura": 10,
    "punto_venta": 4,
}


def _modulo_11(cadena, num_dig=1, lim_mult=9, x10=False):
    """
    Replica exacta del algoritmo "calculaDigitoMod11" de la pagina oficial
    (Java/C#): pesos ciclicos de 2 a lim_mult (9), de derecha a izquierda.
    dig==10 -> se agrega '1'; dig==11 -> se agrega '0' (solo con x10=True).
    """
    cadena_trabajo = cadena
    for _ in range(num_dig):
        suma = 0
        mult = 2
        for i in range(len(cadena_trabajo) - 1, -1, -1):
            suma += mult * int(cadena_trabajo[i])
            mult += 1
            if mult > lim_mult:
                mult = 2
        if x10:
            dig = ((suma * 10) % 11) % 10
        else:
            dig = suma % 11
        if dig == 10:
            cadena_trabajo += "1"
        elif dig == 11:
            cadena_trabajo += "0"
        else:
            cadena_trabajo += str(dig)
    return cadena_trabajo[-num_dig:] if num_dig else ""


def _completar_ceros(valor, longitud):
    return str(valor).zfill(longitud)


def calcular_cuf(nit, fecha_hora, codigo_sucursal, codigo_modalidad,
                  codigo_tipo_emision, codigo_tipo_factura,
                  codigo_documento_sector, numero_factura,
                  codigo_control, codigo_punto_venta=0):
    """
    nit: NIT del emisor (entero o string).
    fecha_hora: datetime.datetime de emision.
    codigo_sucursal / codigo_modalidad / codigo_tipo_emision /
    codigo_tipo_factura / codigo_documento_sector / numero_factura /
    codigo_punto_venta: enteros, segun las tablas parametricas del SIN.
    codigo_control: el valor devuelto por el SIN en la respuesta del
        servicio solicitudCufd (se concatena al final, es OBLIGATORIO
        para tener el CUF real, no se puede omitir ni inventar).

    Devuelve el CUF completo (hexadecimal local + codigoControl).
    """
    fecha_str = (
        fecha_hora.strftime("%Y%m%d%H%M%S")
        + f"{fecha_hora.microsecond // 1000:03d}"
    )

    campos = (
        _completar_ceros(nit, LONGITUDES["nit"])
        + _completar_ceros(fecha_str, LONGITUDES["fecha_hora"])
        + _completar_ceros(codigo_sucursal, LONGITUDES["sucursal"])
        + _completar_ceros(codigo_modalidad, LONGITUDES["modalidad"])
        + _completar_ceros(codigo_tipo_emision, LONGITUDES["tipo_emision"])
        + _completar_ceros(codigo_tipo_factura, LONGITUDES["tipo_factura"])
        + _completar_ceros(codigo_documento_sector, LONGITUDES["tipo_documento_sector"])
        + _completar_ceros(numero_factura, LONGITUDES["numero_factura"])
        + _completar_ceros(codigo_punto_venta, LONGITUDES["punto_venta"])
    )  # 53 digitos

    digito_verificador = _modulo_11(campos)  # -> 54 digitos con el check digit
    cadena_final = campos + digito_verificador

    cuf_local_hex = format(int(cadena_final), "X")

    return cuf_local_hex + str(codigo_control)


if __name__ == "__main__":
    # Reproduce EXACTO el ejemplo oficial, para dejar constancia de la
    # verificacion.
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
        codigo_control="A19E23EF34124CD",  # valor de ejemplo del SIN
    )
    esperado = "8727F63A15F8976591FDDE5B387C5D015A29E06A1A19E23EF34124CD"
    print("CUF calculado:", cuf)
    print("CUF esperado :", esperado)
    print("Coincide exacto con el ejemplo oficial:", cuf == esperado)
