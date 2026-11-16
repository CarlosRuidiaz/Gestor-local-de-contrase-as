# Registro de desviaciones respecto al Entregable 1

El enunciado permite que el informe final corrija el diseño inicial siempre que explique las desviaciones. Cada cambio respecto a `entregable1/Entregable1_Proyecto_final.pdf` se registra aquí al momento de hacerlo.

| Fecha | Sección del Entregable 1 | Qué cambió | Por qué | Impacto en seguridad o pruebas |
|---|---|---|---|---|
| | | | | |

## Verificación de supuestos sobre las bibliotecas

Resultado de `scripts/check_env.py` dentro de la imagen de referencia el 2026-11-15. Ningún supuesto del diseño falló, así que no hay desviaciones que registrar por este motivo.

| Supuesto | Resultado |
|---|---|
| Versiones | Python 3.12.16, `cryptography` 50.0.2, OpenSSL 4.0.3 (se exigía 3.2 o superior) |
| `Argon2id` con memoria, iteraciones, `lanes`, `secret` y `ad` | Disponible. El vector de RFC 9106 §5.3 coincide, lo que confirma Argon2 v1.3 |
| `derive_into` | Existe y escribe los 32 bytes en un `bytearray` preasignado. La KEK puede derivarse directamente en el búfer que luego se sobrescribe con ceros |
| Tipos de clave de `ChaCha20Poly1305` | Acepta `bytes`, `bytearray` y `memoryview` |
| Vector de RFC 8439 §2.8.2 | Coincide |
| Carriles de Argon2id en varios hilos | Indicio a favor sin confirmar. Con 64 MiB y 3 pasadas el tiempo de pared baja de 0,173 s (1 carril) a 0,070 s (4 carriles), pero el tiempo de CPU medido no creció como se esperaría. E1 debe medirlo con una herramienta fiable |
