# Estado del proyecto

Este archivo se actualiza **en cada push**. Quien retoma el trabajo hace `git pull`, lee esto y ya sabe dónde está el proyecto y qué sigue. Las reglas y el flujo están en [`guia_desarrollo.md`](guia_desarrollo.md).

Última actualización: 2026-11-16, Carlos Ruidiaz.

## Resumen

Entregable 2 (60 % de la nota), semana académica 16. Las capas `crypto/` y `storage/` están terminadas y probadas. Falta `vault/`, el CLI, la interfaz web, los experimentos y el cierre (README, guion de demostración e informe).

La suite tiene 194 pruebas en verde dentro del contenedor, con `mypy` estricto y `ruff` sin avisos.

## Fases

| Fase | Contenido | Estado | Responsable | Rama |
|---|---|---|---|---|
| 0 | Andamiaje, Docker, dependencias, verificación del entorno | Terminada | Carlos Ruidiaz | fusionada |
| 1 | `crypto/`: KEK con Argon2id, AEAD, aleatoriedad, borrado. T10 | Terminada | Carlos Ruidiaz | fusionada |
| 2 | `storage/`: formato v1, comprobaciones 1 y 2, guardado atómico, lock. T4 (formato), T5 (sin claves), T7 | Terminada | Claudia Elias | fusionada |
| 3 | `vault/`: entradas, operaciones, sesión, generador. T1, T2, T3, T6, T8, T11 y el resto de T4 y T5 | **Siguiente** | Carlos Ruidiaz | sin empezar |
| 4 | CLI mínimo con `getpass` | Pendiente | sin asignar | |
| 5 | `web/`: FastAPI, seguridad HTTP, frontend. T9, T12, T13 | Pendiente | sin asignar | |
| 6 | Experimentos E1, E2, E3 y gráficas | Pendiente | sin asignar | |
| 7 | README, guion de demostración, informe final | Pendiente | sin asignar | |

El detalle de cada fase, con sus casillas, está en [`plan_implementacion.md`](plan_implementacion.md). Las fases 5 y 6 pueden avanzar en paralelo una vez exista la 4.

## Siguiente paso

**Fase 3, `pvlt/vault/`**, en una rama `feat/vault`. Tareas, en el orden sugerido:

1. Excepciones de la capa: `WrongPasswordError` ("Contraseña incorrecta") y `TamperedContentError` ("Contenido manipulado"). Las otras dos categorías ya existen en `storage/` (`FormatError`, `CorruptedFileError`).
2. Modelo de entrada y contenido: JSON canónico, validación de esquema, relleno a 4096 con `0x80` y su retiro estricto (`diseno.md` §5.1).
3. Sellado y apertura del archivo completo (`diseno.md` §4.1 y §4.4): construir `Hdr`, cifrar la DEK como `W` y el contenido como `C` con los datos asociados exactos, y las comprobaciones 3 y 4.
4. Operaciones: `create`, `unlock`, `save`, `lock`, `change_password`, `export`, `import_preview`, `import_apply` (`diseno.md` §4.2 a §4.6).
5. Sesión con temporizador de inactividad y reloj inyectable para las pruebas.
6. Generador con muestreo por rechazo y cálculo de entropía (`diseno.md` §4.8).
7. Pruebas T1, T2, T3, T6, T8, T11, y lo que falta de T4 y T5: contraseña incorrecta, alteración de cada campo **con el resumen recalculado**, e intercambio de `C` entre bóvedas.

### Qué ofrece ya el código para la Fase 3

`from pvlt import params`:

- `KEY_LEN`, `NONCE_LEN`, `TAG_LEN`, `SALT_LEN`, `PAD_BLOCK`.
- `WRAP_LABEL` y `DATA_LABEL`, las etiquetas de dominio exactas.
- `CONFIG_A`, `CONFIG_B`, `CONFIG_C` (`Argon2Params` con `m_cost`, `t_cost`, `parallelism`) y `M_COST_CREATE_MIN_KIB`.

`from pvlt.crypto import ...`:

- `derive_kek(password, salt, m_cost, t_cost, parallelism) -> bytearray`. Valida los límites antes de derivar. Lanza `KdfParameterError`.
- `seal(key, nonce, plaintext, aad) -> bytes` y `open_(key, nonce, ciphertext, aad) -> bytes`. `open_` lanza `AuthenticationError` sin datos. La capa `vault/` la traduce: al abrir `W` es `WrongPasswordError`, al abrir `C` es `TamperedContentError`.
- `random_bytes(n)` y `zeroize(buf)`.

`from pvlt.storage import ...`:

- `Header(purpose, m_cost, t_cost, parallelism, salt, vault_id, generation)` con `pack()`, que devuelve los 59 bytes de `Hdr`.
- `VaultFile(header, nonce_w, wrapped_key, nonce_d, ciphertext)` con `pack()`, que devuelve el archivo completo con su resumen.
- `Purpose.VAULT` y `Purpose.EXPORT`.
- `load(path, purpose) -> VaultFile` (comprobaciones 1 y 2, nunca escribe) y `unpack(data, purpose)`.
- `atomic_save(path, data, purpose=..., make_backup=..., fault_hook=...)`. Para exportar se usa `make_backup=False`.
- `write_backup(path, data)`, que hace falta tras cambiar la contraseña maestra para regenerar el `.bak`.
- `recover(path) -> RecoveryReport` (limpia temporales, informa `can_restore_backup` y `possible_rollback`) y `restore_backup(path)`.
- `VaultLock(path)`, utilizable con `with`. Lanza `VaultLockedError`.

### Qué leer por fase

| Fase | Secciones de `diseno.md` |
|---|---|
| 3 | §4 completa, §5.1, §6, y las pruebas T1 a T8 y T11 de §9 |
| 4 | §4.2 a §4.6, §7 (arranque y recuperación) |
| 5 | §8 completa, §4.9, y T9, T12, T13 de §9 |
| 6 | §6 y §10 |
| 7 | `requisitos_entregable2.md` y `desviaciones.md` |

## Decisiones tomadas

Solo las que no se deducen leyendo el diseño. Las que afectan al formato o a la persistencia también están en `diseno.md` como concreciones.

| Fecha | Decisión | Motivo |
|---|---|---|
| 2026-11-15 | `cryptography` 50.0.2 sobre OpenSSL 4.0.3. Todos los supuestos del diseño sobre la biblioteca se cumplen (ver `desviaciones.md`) | Verificado con `scripts/check_env.py` |
| 2026-11-15 | La KEK se deriva con `derive_into` sobre un `bytearray` propio | Permite sobrescribirla con ceros al bloquear |
| 2026-11-15 | Las constantes públicas del protocolo viven en `pvlt/params.py`, fuera de las capas | `crypto/` y `storage/` las comparten sin importarse entre sí |
| 2026-11-15 | `crypto/` lanza una sola `AuthenticationError`. El significado lo pone `vault/` | El AEAD no puede distinguir contraseña incorrecta de manipulación |
| 2026-11-15 | El vector de RFC 9106 se prueba sobre la primitiva de la biblioteca | Usa secreto y dato asociado, que `derive_kek` no expone a propósito |
| 2026-11-15 | El lock es un bloqueo del núcleo sobre `boveda.pvlt.lock`, sin PID | Se libera solo al morir el proceso. En Docker el PID se repite entre ejecuciones y no serviría |
| 2026-11-15 | La versión vigente solo se copia a `.bak` si supera las comprobaciones 1 y 2 | Una bóveda dañada no debe destruir el último respaldo bueno |
| 2026-11-15 | `len_C` máximo de 16 MiB más la etiqueta, y `generation` mínima de 1 | Acotar la lectura de archivos hostiles |
| 2026-11-15 | El SHA-256 del resumen se calcula con `cryptography`, no con `hashlib` | Una sola biblioteca criptográfica en el producto. Las pruebas sí usan `hashlib` como implementación independiente |
| 2026-11-15 | `playwright` no está en `requirements.in` todavía | Se añade en la Fase 5 para no engordar la imagen antes de tiempo |
| 2026-11-15 | Los PDF del curso no se versionan | Son material del docente |

## Pendientes y advertencias

- **Carriles de Argon2id en varios hilos:** sin confirmar. Con 4 carriles el tiempo de pared baja, pero el tiempo de CPU medido no crece como se esperaría. E1 debe medirlo con una herramienta fiable y el informe debe decir qué se observó.
- **El resumen SHA-256 no protege contra manipulación.** Quien altera un campo y recalcula el resumen supera las comprobaciones 1 y 2. `tests/storage/test_format.py` lo deja explícito. La Fase 3 debe demostrar que las etiquetas AEAD rechazan esos archivos.
- **Configuración final de Argon2id:** se decide en la Fase 6 con los resultados de E1. Por ahora el valor por defecto propuesto es la configuración B.
- **Reconstruir la imagen tras cada cambio.** El código se copia a la imagen, no se monta. Sin `docker compose build` las pruebas corren contra la versión anterior.
- **Timeouts de PyPI** al regenerar `requirements.txt`. Usar `PIP_DEFAULT_TIMEOUT=120` como indica la guía.

## Bitácora

Una entrada por sesión de trabajo que termine en push, la más reciente arriba. Formato: fecha, quién, rama, qué se hizo, qué quedó pendiente o a medias, y avisos para quien sigue.

### 2026-11-16 · Carlos Ruidiaz · `docs/guia-desarrollo`

- Se añaden `guia_desarrollo.md` y este archivo para que cualquier integrante pueda retomar el trabajo solo con clonar.
- Sin cambios de código.
- Sigue: Fase 3.

### 2026-11-15 · Claudia Elias · `feat/storage`

- Fase 2 completa: `storage/format.py`, `store.py`, `lock.py`, `errors.py`. 127 pruebas nuevas.
- Se movieron los límites de Argon2id a `params.argon2_limit_violation` para que `crypto/` y `storage/` usen la misma función.
- Pendiente para la Fase 3: la parte de T4 y T5 que necesita claves.

### 2026-11-15 · Carlos Ruidiaz · `feat/crypto`

- Fase 1 completa: `crypto/kdf.py`, `aead.py`, `rand.py`, `memory.py` y `params.py`. T10 completo.

### 2026-11-15 · Carlos Ruidiaz · `main`

- Fase 0 completa: andamiaje, Dockerfile, dependencias con hashes, `scripts/check_env.py`, pruebas de humo.
- Verificados los supuestos del diseño sobre `cryptography` y OpenSSL. Ninguno falló.
