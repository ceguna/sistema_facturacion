"""
Calculo del CUF (Codigo Unico de Factura).
Confirmado y verificado contra el ejemplo oficial del SIN — ver
prototipo/sin/cuf.py para el historial completo de validacion.
"""
import datetime

LONGITUDES = {
    "nit": 13, "fecha_hora": 17, "sucursal": 4, "modalidad": 1,
    "tipo_emision": 1, "tipo_factura": 1, "tipo_documento_sector": 2,
    "numero_factura": 10, "punto_venta": 4,
}


def _modulo_11(cadena, num_dig=1, lim_mult=9, x10=False):
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
    )
    digito_verificador = _modulo_11(campos)
    cadena_final = campos + digito_verificador
    cuf_local_hex = format(int(cadena_final), "X")
    return cuf_local_hex + str(codigo_control)