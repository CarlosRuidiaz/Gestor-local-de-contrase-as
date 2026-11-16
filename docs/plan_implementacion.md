# Plan de implementación

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

- [ ] `derive_kek(password: bytes, salt, m_cost, t_cost, parallelism) -> bytearray`.
- [ ] `seal(key, nonce, plaintext, aad) -> bytes` y `open_(key, nonce, ciphertext, aad) -> bytes` sobre ChaCha20-Poly1305.
- [ ] `random_bytes(n)` con `secrets`.
- [ ] `zeroize(buf: bytearray)`.
- [ ] T10: vector AEAD de RFC 8439 §2.8.2 y vector Argon2id de RFC 9106 §5.3.

## Fase 2 · `storage/`

- [ ] Dataclass `Header` y `VaultFile` con `pack()` y `unpack()` según la tabla de `diseno.md` §5. Los desplazamientos se definen en una sola tabla reutilizada por las pruebas.
- [ ] Validación de la comprobación 1 (formato, versión, ids, límites, longitudes) y 2 (digest con `hmac.compare_digest`).
- [ ] Guardado atómico con puntos de inyección de fallo, respaldo, lock y fsync del directorio.
- [ ] Recuperación al iniciar: limpiar temporales, ofrecer `.bak`, advertir retroceso.
- [ ] T4 (parte de formato), T5, T7.

## Fase 3 · `vault/`

- [ ] Modelo de entrada, JSON canónico, relleno y su retiro estricto.
- [ ] `create`, `unlock` (cuatro comprobaciones con excepciones propias), `save`, `lock`, `change_password`, `export`, `import_preview`, `import_apply`.
- [ ] Sesión con temporizador de inactividad inyectable (reloj falso en pruebas).
- [ ] Generador con muestreo por rechazo y cálculo de entropía.
- [ ] T1, T2, T3, T6, T8, T11.

## Fase 4 · CLI mínimo

- [ ] `python -m pvlt.cli create|unlock|add|list|change-password|export|import` usando `getpass`.
- [ ] Sirve para la demo de respaldo y para los experimentos. No necesita ser bonito.

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
