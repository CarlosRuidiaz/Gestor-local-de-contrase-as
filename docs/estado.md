# Estado del proyecto

Este archivo se actualiza **en cada push**. Quien retoma el trabajo hace `git pull`, lee esto y ya sabe dónde está el proyecto y qué sigue. Las reglas y el flujo están en [`guia_desarrollo.md`](guia_desarrollo.md).

**Antes de hacer cualquier commit** hay que leer la sección "Reglas de autoría y de lo que se sube" de la guía. Indica quién firma cada fase, qué no puede subirse nunca y cómo se sube.

Última actualización: 2026-11-16, Juan Bolivar (Fase 4, CLI).

## Resumen

Entregable 2 (60 % de la nota), semana académica 16. Las capas `crypto/`, `storage/` y `vault/` están terminadas y probadas, y el CLI mínimo (`pvlt/cli.py`) ya permite usar la bóveda desde la terminal. Falta la interfaz web, los experimentos y el cierre (README, guion de demostración e informe).

La suite tiene 468 pruebas en verde dentro del contenedor, con `mypy` estricto y `ruff` sin avisos. Cubre T1 a T8, T10 y T11. Faltan T9, T12 y T13, que dependen de la interfaz web.

## Fases

| Fase | Contenido | Estado | Responsable | Rama |
|---|---|---|---|---|
| 0 | Andamiaje, Docker, dependencias, verificación del entorno | Terminada | Carlos Ruidiaz | fusionada |
| 1 | `crypto/`: KEK con Argon2id, AEAD, aleatoriedad, borrado. T10 | Terminada | Carlos Ruidiaz | fusionada |
| 2 | `storage/`: formato v1, comprobaciones 1 y 2, guardado atómico, lock. T4 (formato), T5 (sin claves), T7 | Terminada | Claudia Elias | fusionada |
| 3 | `vault/`: entradas, operaciones, sesión, generador. T1, T2, T3, T6, T8, T11 y el resto de T4 y T5 | Terminada | Carlos Ruidiaz | fusionada |
| 4 | CLI mínimo con `getpass` | Terminada | Juan Bolivar | `feat/cli` |
| 5 | `web/`: FastAPI, seguridad HTTP, frontend. T9, T12, T13 | **Siguiente** | sin asignar | |
| 6 | Experimentos E1, E2, E3 y gráficas | **Siguiente** | sin asignar | |
| 7 | README, guion de demostración, informe final | Pendiente | sin asignar | |

Las fases 5 a 7 están sin asignar. Quien tome una anota su nombre en la tabla en el primer commit de su rama, y todos los commits de esa fase van a su nombre.

El detalle de cada fase, con sus casillas, está en [`plan_implementacion.md`](plan_implementacion.md). Las fases 5 y 6 pueden avanzar en paralelo una vez exista la 4.

## Siguiente paso

Con el CLI terminado, la **Fase 5** (`web/`, rama `feat/web`) y la **Fase 6** (experimentos, rama `feat/bench`) pueden avanzar en paralelo. Las dos usan exactamente la API de `pvlt.vault` descrita abajo. La Fase 6 puede medir con el CLI o directamente contra `Vault`, y para E1 contra `derive_kek`.

### Cómo se usa el CLI

```
docker compose run --rm app python -m pvlt.cli create --config A
docker compose run --rm app python -m pvlt.cli add --generate
docker compose run --rm app python -m pvlt.cli unlock
docker compose run --rm app python -m pvlt.cli --help
```

- Órdenes: `create [--config A|B|C]`, `unlock`, `list [--search]`, `get ID [--show]`, `add [--generate --length N --no-symbols ...]`, `change-password`, `export DESTINO [--overwrite]`, `import ORIGEN [--on-conflict ask|skip|replace|keep-both]` y `generate`.
- La ruta es `--vault RUTA`. Sin ella se usa `$PVLT_VAULT_DIR/boveda.pvlt` (en el contenedor, `/data`) y, si la variable no existe, `./boveda.pvlt`.
- Contraseñas con `getpass`. Sitio, usuario, notas y texto de búsqueda se piden por teclado con `input`, nunca como argumento.
- Al arrancar informa de los temporales eliminados y del posible retroceso, y ofrece restaurar el respaldo si la bóveda no se puede leer y el `.bak` sí. Solo restaura con una respuesta afirmativa explícita.
- Para la demo del respaldo basta con dañar un byte de `boveda.pvlt` y ejecutar `unlock`.
- Códigos de salida, definidos en `pvlt/cli.py`: 0 correcto, 2 uso incorrecto, 3 formato no reconocido, 4 archivo dañado, 5 contraseña incorrecta, 6 contenido manipulado, 7 sesión bloqueada, 8 dato inválido, 9 entrada inexistente, 10 el archivo ya existe, 11 bóveda abierta en otro proceso, 12 no hay bóveda o archivo a importar, 13 las contraseñas no coinciden, 14 error de lectura o escritura, 130 cancelado, 1 error inesperado (solo se muestra la clase).

### Qué ofrece ya el código

`from pvlt.vault import ...` es lo único que deben importar el CLI y la capa web:

- `Workspace(path)`: se abre una vez al arrancar el programa, utilizable con `with`. Toma el lock (`VaultLockedError` si otro proceso lo tiene) y deja en `.report` un `RecoveryReport` con `vault`, `backup`, `can_restore_backup` y `possible_rollback`. `restore_backup()` restaura el `.bak` a petición del usuario.
- `Vault.create(path, password, params=CONFIG_B)` y `Vault.unlock(path, password)`. Ambos devuelven una bóveda desbloqueada. Aceptan `clock` y `now` inyectables para las pruebas.
- Sesión: `lock()`, `is_locked`, `seconds_until_autolock()`. Toda operación sobre una bóveda bloqueada lanza `SessionLockedError`.
- Lectura: `len(vault)`, `list_entries(query="")` (devuelve `EntrySummary` sin contraseña ni notas), `get(id)` (devuelve `Entry` completa), `settings`, `generation`.
- Cambios: `add(site=, username=, password=, notes=)`, `update(id, ...)`, `delete(id)`, `update_settings(autolock_seconds=, generator=)`. Cada uno guarda en disco.
- `generate_password(settings=None)`, y fuera de la bóveda `generate(GeneratorSettings(...))` y `entropy_bits(...)`.
- `change_password(current, new)`.
- `export(destination, password, overwrite=False)`, `import_preview(source, password)` e `import_apply(preview, decisions)` con `ImportDecision.SKIP`, `REPLACE` o `KEEP_BOTH` por id de entrada importada.

Excepciones que la interfaz debe traducir. El texto de cada una ya es el mensaje en español para el usuario:

| Excepción | Origen | Mensaje |
|---|---|---|
| `FormatError` | `pvlt.storage` | Formato no reconocido |
| `CorruptedFileError` | `pvlt.storage` | Archivo dañado (ofrecer el respaldo) |
| `WrongPasswordError` | `pvlt.vault` | Contraseña incorrecta |
| `TamperedContentError` | `pvlt.vault` | Contenido manipulado |
| `SessionLockedError` | `pvlt.vault` | La bóveda está bloqueada |
| `ValidationError` | `pvlt.vault` | Dato inválido (el atributo `field` dice cuál) |
| `EntryNotFoundError` | `pvlt.vault` | La entrada no existe |
| `VaultExistsError` | `pvlt.vault` | Ya existe un archivo en esa ruta |
| `VaultLockedError` | `pvlt.storage` | La bóveda ya está abierta en otro proceso |
| `FileNotFoundError` | Python | No hay bóveda en esa ruta (ofrecer crearla) |

Las capas inferiores (`pvlt.crypto`, `pvlt.storage`) siguen disponibles para los experimentos de la Fase 6, por ejemplo `derive_kek` para E1 y `seal_file` y `open_file` de `pvlt.vault.envelope` para E2.

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
| 2026-11-16 | Cada fase la firma su responsable, sin firmas de herramientas, y no se reescribe el historial de `main` | Acuerdo del equipo. El detalle está en la guía |
| 2026-11-16 | `Workspace` sostiene el lock durante todo el proceso y `Vault` no toma ningún lock | El diseño pide adquirirlo al iniciar. Así la sesión puede bloquearse y desbloquearse sin soltarlo |
| 2026-11-16 | Todo cambio se guarda en disco antes de aplicarse en memoria | Un guardado fallido no deja la sesión distinta del archivo |
| 2026-11-16 | Al abrir solo se acepta el JSON canónico exacto | Serialización inequívoca, como pide el enunciado |
| 2026-11-16 | Contraseña maestra de 8 a 1024 caracteres, sin normalización Unicode | El diseño dejaba el mínimo abierto. NFC y NFD son contraseñas distintas, hay una prueba que lo fija |
| 2026-11-16 | En la importación, un conflicto sin decisión se omite | Es la única opción que no destruye ni duplica nada |
| 2026-11-16 | T11 comprueba la uniformidad dentro de cada clase, y sobre todo el alfabeto solo con longitud 128 | El muestreo por rechazo desplaza algo de peso entre clases en contraseñas cortas. Dentro de una clase la uniformidad es exacta |
| 2026-11-16 | T6 hace los 10 000 guardados en memoria y otros 200 por disco | La propiedad está en el sellado. Hacer 10 000 guardados con `fsync` tardaría minutos |
| 2026-11-16 | El CLI pide sitio, usuario, notas y búsqueda por teclado, no como argumentos | La regla 2 prohíbe esos datos en los argumentos del proceso, no solo las contraseñas |
| 2026-11-16 | El CLI comprueba el estado de la bóveda antes de pedir la contraseña | Si falta o falla las comprobaciones 1 o 2, falla sin ejecutar Argon2id |
| 2026-11-16 | `create` y `export` se niegan a sobrescribir antes de pedir la contraseña, y las contraseñas nuevas se piden dos veces con la longitud validada antes de derivar | No se gasta un Argon2id en una operación que va a fallar |
| 2026-11-16 | El CLI importa de `pvlt.storage` solo `FormatError`, `CorruptedFileError`, `VaultLockedError` y `FileStatus` | Las tres excepciones nacen en esa capa y la interfaz debe traducirlas. No hace falta reexportarlas desde `vault/` |
| 2026-11-16 | `pvlt.cli` también pasa `mypy` en modo estricto | Es una interfaz que maneja contraseñas |
| 2026-11-16 | Dos pruebas llevan la marca `slow` (T1 con 500 entradas y T6 por disco) | Suman unos 40 s. Se ejecutan por defecto y se pueden excluir con `-m "not slow"` |

## Pendientes y advertencias

- **Carriles de Argon2id en varios hilos:** sin confirmar. Con 4 carriles el tiempo de pared baja, pero el tiempo de CPU medido no crece como se esperaría. E1 debe medirlo con una herramienta fiable y el informe debe decir qué se observó.
- **El resumen SHA-256 no protege contra manipulación.** Quien altera un campo y recalcula el resumen supera las comprobaciones 1 y 2. `tests/storage/test_format.py` lo deja explícito. La Fase 3 debe demostrar que las etiquetas AEAD rechazan esos archivos.
- **Configuración final de Argon2id:** se decide en la Fase 6 con los resultados de E1. Por ahora el valor por defecto propuesto es la configuración B.
- **Reconstruir la imagen tras cada cambio.** El código se copia a la imagen, no se monta. Sin `docker compose build` las pruebas corren contra la versión anterior.
- **Docker Desktop no arranca y muestra "remove ...sock: El sistema no tiene acceso al archivo".** Pasa si se lanza dos veces o tras un cierre brusco. Se arregla finalizando todos los procesos de Docker desde el Administrador de tareas y abriéndolo una sola vez. No hace falta "Reset to factory defaults".
- **La suite completa tarda cerca de dos minutos** en el contenedor. Para iterar, `pytest -m "not slow"` o un solo archivo.
- **Las pruebas también pasan en Windows** con Python 3.14, salvo dos de permisos POSIX que se omiten solas. Sirve para iterar rápido, pero la referencia sigue siendo el contenedor.
- **Ventana en el cambio de contraseña:** entre el guardado y la reescritura del respaldo, el `.bak` todavía abre con la contraseña anterior. Está documentado en `diseno.md` §4.9. Conviene mencionarlo en el informe como limitación.
- **Timeouts de PyPI** al regenerar `requirements.txt`. Usar `PIP_DEFAULT_TIMEOUT=120` como indica la guía.

## Bitácora

Una entrada por sesión de trabajo que termine en push, la más reciente arriba. Formato: fecha, quién, rama, qué se hizo, qué quedó pendiente o a medias, y avisos para quien sigue.

### 2026-11-16 · Juan Bolivar · `feat/cli`

- Fase 4 completa: `pvlt/cli.py` con las órdenes `create`, `unlock`, `list`, `get`, `add`, `change-password`, `export`, `import` y `generate`. Se ejecuta con `python -m pvlt.cli` o con el script `pvlt`.
- Arranque con `Workspace`: avisos de temporales y de posible retroceso, y restauración del respaldo solo con confirmación.
- Cada excepción se traduce a su mensaje en español y a un código de salida propio, sin trazas. Un error desconocido muestra solo el nombre de la clase.
- 58 pruebas nuevas en `tests/test_cli.py`, con `getpass` e `input` sustituidos. Comprueban que ningún secreto ni dato de entrada aparece en los argumentos ni en la salida, salvo la contraseña de `get --show`.
- Fuera del CLI solo cambia `pyproject.toml`, que añade `pvlt.cli` al modo estricto de `mypy`.
- Sigue: Fases 5 y 6, en paralelo.

### 2026-11-16 · Carlos Ruidiaz · `docs/reglas-autoria`

- Se añade a la guía la sección "Reglas de autoría y de lo que se sube": quién firma, qué no se sube nunca y cómo se sube.
- Sin cambios de código.
- Sigue: Fase 4 (CLI), sin asignar.

### 2026-11-16 · Carlos Ruidiaz · `feat/vault`

- Fase 3 completa: `vault/errors.py`, `model.py`, `envelope.py`, `vault.py`, `generator.py` y `workspace.py`. 216 pruebas nuevas.
- Quedan cubiertas T1, T2, T3, T6, T8 y T11, y la parte de T4 y T5 que necesitaba claves (alteración de cada campo con el resumen recalculado, intercambio de `C`, mezcla de generaciones).
- Cambio menor fuera de la capa: `crypto.seal` acepta también `bytearray` como texto a cifrar, para sellar la DEK sin copiarla a `bytes`.
- Se ajustaron dos pruebas de `storage/` para que también pasen en Windows (el archivo de lock no se puede leer mientras está tomado).
- Sigue: Fase 4 (CLI). Está descrita arriba con la API que debe usar.

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
