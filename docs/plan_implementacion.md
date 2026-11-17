# Plan de implementación

El estado actual, el siguiente paso y la bitácora están en [`estado.md`](estado.md). Las reglas y el flujo de trabajo están en [`guia_desarrollo.md`](guia_desarrollo.md).

Orden pensado para que la criptografía sea demostrable lo antes posible. Si la interfaz web se retrasa, todo lo de las fases 0 a 4 sigue siendo evaluable con el CLI. Marcar cada casilla al terminar y anotar en `desviaciones.md` lo que cambie respecto al diseño.

Las fases 1 y 2 pueden avanzar en paralelo (dos personas), igual que la 5 respecto a la 6.

## Fase 0 · Andamiaje y verificaciones

- [x] Inicializar git, `.gitignore` (excluir `*.pvlt`, `*.bak`, `*.tmp`, `bench/results/raw/`, entornos virtuales).
- [x] `pyproject.toml` con el paquete `pvlt`, `requirements.in` y `requirements.txt` con hashes (`pip-compile --generate-hashes`).
- [x] `Dockerfile` (python:3.12-slim) y `docker-compose.yml` publicando `127.0.0.1:8765:8765`.
- [x] Configurar `pytest`, `mypy` estricto en `crypto/`, `storage/`, `vault/`, y `ruff`.
- [x] Script `scripts/check_env.py` que imprima versión de `cryptography`, versión de OpenSSL, disponibilidad de `Argon2id`, de `derive_into`, y el tipo de clave aceptado por `ChaCha20Poly1305`. Registrar resultados en `desviaciones.md` si algo difiere del diseño.

Estado al 2026-11-15: andamiaje completo y verificado en el contenedor (`pytest`, `mypy`, `ruff` y `scripts/check_env.py` en verde). Falta el primer commit.

## Fase 1 · `crypto/`

- [x] `derive_kek(password: bytes, salt, m_cost, t_cost, parallelism) -> bytearray`.
- [x] `seal(key, nonce, plaintext, aad) -> bytes` y `open_(key, nonce, ciphertext, aad) -> bytes` sobre ChaCha20-Poly1305.
- [x] `random_bytes(n)` con `secrets`.
- [x] `zeroize(buf: bytearray)`.
- [x] T10: vector AEAD de RFC 8439 §2.8.2 y vector Argon2id de RFC 9106 §5.3.

Estado al 2026-11-15: capa completa, 67 pruebas en verde dentro del contenedor y `mypy` estricto sin errores.

- La KEK se deriva con `derive_into` directamente sobre el `bytearray` que luego borra `zeroize`.
- `open_` lanza `AuthenticationError` sin datos ni excepción encadenada. La capa `vault/` decide si significa contraseña incorrecta (al abrir W) o contenido manipulado (al abrir C).
- Los límites de Argon2id se validan en `validate_kdf_params` antes de construir la primitiva. Las constantes públicas del protocolo (tamaños, etiquetas de dominio, límites y configuraciones A, B y C) viven en `pvlt/params.py`, un módulo sin dependencias que `crypto/` y `storage/` comparten sin importarse entre sí.
- El vector de RFC 9106 §5.3 usa secreto y dato asociado, que `derive_kek` no expone. Por eso T10 lo comprueba sobre la primitiva de la biblioteca y además verifica que `derive_kek` produce exactamente la salida de esa primitiva con nuestros parámetros.

## Fase 2 · `storage/`

- [x] Dataclass `Header` y `VaultFile` con `pack()` y `unpack()` según la tabla de `diseno.md` §5. Los desplazamientos se definen en una sola tabla reutilizada por las pruebas.
- [x] Validación de la comprobación 1 (formato, versión, ids, límites, longitudes) y 2 (digest con `hmac.compare_digest`).
- [x] Guardado atómico con puntos de inyección de fallo, respaldo, lock y fsync del directorio.
- [x] Recuperación al iniciar: limpiar temporales, ofrecer `.bak`, advertir retroceso.
- [x] T4 (parte de formato), T5, T7.

Estado al 2026-11-15: capa completa, 194 pruebas en verde dentro del contenedor (127 de `storage/`) y `mypy` estricto sin errores.

- `format.py` define los desplazamientos en dos tablas (`HEADER_FIELDS` y `ENVELOPE_FIELDS`). Una prueba las compara con la tabla de `diseno.md` §5 copiada a mano, y T5 recorre esas mismas tablas.
- `store.py` expone seis puntos de interrupción (`SaveStep`). T7 corta el guardado en cada uno y comprueba que siempre queda una versión íntegra.
- La versión vigente solo se copia a `.bak` si supera las comprobaciones 1 y 2. Así una bóveda dañada nunca destruye el último respaldo bueno.
- `lock.py` usa un bloqueo del núcleo sobre `boveda.pvlt.lock` (`flock` en POSIX, `msvcrt.locking` en Windows). El núcleo lo libera cuando el proceso termina, incluso si muere de forma abrupta.
- Límite de esta capa, cubierto por una prueba explícita: quien altera un campo y recalcula el SHA-256 supera las comprobaciones 1 y 2. El rechazo de ese archivo corresponde a las etiquetas AEAD de las comprobaciones 3 y 4, que se prueban en la Fase 3.
- Pendiente para la Fase 3: la parte de T4 y T5 que necesita claves (contraseña incorrecta, alteraciones con resumen recalculado, intercambio de C entre bóvedas).

## Fase 3 · `vault/`

- [x] Modelo de entrada, JSON canónico, relleno y su retiro estricto.
- [x] `create`, `unlock` (cuatro comprobaciones con excepciones propias), `save`, `lock`, `change_password`, `export`, `import_preview`, `import_apply`.
- [x] Sesión con temporizador de inactividad inyectable (reloj falso en pruebas).
- [x] Generador con muestreo por rechazo y cálculo de entropía.
- [x] T1, T2, T3, T6, T8, T11.

Estado al 2026-11-16: capa completa, 410 pruebas en verde dentro del contenedor (216 de `vault/`) y `mypy` estricto sin errores. Con esto quedan cubiertas T1 a T8, T10 y T11. El detalle de las decisiones está en `estado.md` y las concreciones en `diseno.md`.

## Fase 4 · CLI mínimo

- [x] `python -m pvlt.cli create|unlock|add|list|change-password|export|import` usando `getpass`. También `get` y `generate`.
- [x] Sirve para la demo de respaldo y para los experimentos. No necesita ser bonito.

Estado al 2026-11-16: CLI completo, 468 pruebas en verde dentro del contenedor (58 del CLI) y `mypy` estricto sin errores. Las órdenes, la ruta por defecto y los códigos de salida están en `estado.md`.

## Fase 5 · `web/`

- [ ] App FastAPI con arranque (token, puerto, abrir navegador o imprimir URL).
- [ ] Middleware de seguridad: Host, Origin, CSRF, cabeceras CSP y no-store.
- [ ] Endpoints: estado, crear, desbloquear, bloquear, listar (sin contraseñas), obtener contraseña de una entrada, crear, editar, eliminar, generar, cambiar contraseña, exportar, importar con vista previa.
- [ ] Frontend en HTML, CSS y JS propios, sin CDN. Solo `textContent` para datos de usuario.
- [ ] Portapapeles con borrado a los 20 s. Aviso sobre el guardado de contraseñas del navegador.
- [ ] T9 (logs y URL), T12, T13 con Playwright.

## Fase 6 · Experimentos

- [ ] `bench/e1_argon2.py`, `bench/e2_open_save.py`, `bench/e3_size.py`, resultados CSV en `bench/results/`.
- [ ] Gráficas para el informe y estimación del costo de diccionario.
- [ ] Decidir la configuración final de Argon2id y anotarlo.

## Fase 7 · Cierre

- [ ] README: instalación desde cero (Docker y local), comandos, guion de demostración paso a paso.
- [ ] `scripts/demo.sh` o guion equivalente que recorra los escenarios exigidos.
- [ ] Revisar `desviaciones.md` y redactar el informe final (8 a 12 páginas, sin punto y coma).
- [ ] Ejecutar la suite completa en un clon limpio dentro de Docker.
