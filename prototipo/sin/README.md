# Prototipo aislado — Paso 3: generación de XML + cálculo de CUF + firma digital

Este prototipo vive **fuera** del proyecto Django principal, tal como lo
planeamos. No toca `fac/views.py` ni ningún modelo real todavía — es solo
para probar el mecanismo antes de integrarlo (eso es el Paso 5).

## Cómo correrlo

```powershell
python -m venv entorno_prueba_sin
entorno_prueba_sin\Scripts\activate
pip install lxml signxml cryptography
python main.py
```

Debería terminar con:
```
[5] Validando el documento completo contra facturaElectronicaCompraVenta.xsd...
    VALIDO contra el XSD oficial.

Listo. Factura de prueba guardada en: factura_firmada.xml
```

## Archivos

- `factura_xml.py` — arma el XML de la cabecera + detalle, respetando el
  orden exacto de campos del XSD oficial y el patrón `xsi:nil="true"` para
  los campos opcionales sin usar.
- `cuf.py` — calcula el CUF. **Verificado byte a byte contra el ejemplo
  oficial** de la página "Algoritmos Utilizados" del SIAT (Módulo 11,
  Generación CUF, Base 16). El único dato que falta para tener el CUF
  definitivo en producción es el `codigoControl` real, que viene de la
  respuesta del servicio `solicitudCufd` (aquí está simulado con el valor
  de ejemplo oficial).
- `firmar.py` / `main.py` — firman el XML con XML-DSig (RSA-SHA256, SHA-256,
  canonicalización C14N 1.0 con comentarios — confirmado exactamente contra
  el XML de ejemplo oficial del SIN).
- `generar_certificado_prueba.py` — genera un certificado autofirmado (no
  válido ante el SIN) solo para poder probar la firma sin depender todavía
  del certificado real de ADSIB.
- `facturaElectronicaCompraVenta.xsd` — el XSD oficial (el mismo que subiste).
- `SignatureSchema.xsd` — el schema estándar de W3C para XML-DSig (debe
  quedar en la carpeta **de arriba** de donde está el XSD, porque este último
  lo importa como `../SignatureSchema.xsd`).

## Qué falta antes de conectar esto al SIN real (Paso 4)

1. Cambiar `ARCHIVO_LLAVE`/`ARCHIVO_CERT` en `main.py` por el certificado
   real de ADSIB cuando esté listo (mismo formato `.pem`, no hay que cambiar
   nada más del código).
2. Conectar contra los servicios SOAP reales del ambiente Piloto (`cuis`,
   `solicitudCufd`, `RecepcionFactura`) usando `zeep`. El CUFD real trae el
   `codigoControl` que hoy está simulado en `cuf.py`.
