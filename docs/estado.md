# Estado del proyecto

Este archivo se actualiza **en cada push**. Quien retoma el trabajo hace `git pull`, lee esto y ya sabe dónde está el proyecto y qué sigue. Las reglas y el flujo están en [`guia_desarrollo.md`](guia_desarrollo.md).

**Antes de hacer cualquier commit** hay que leer la sección "Reglas de autoría y de lo que se sube" de la guía. Indica quién firma cada fase, qué no puede subirse nunca y cómo se sube.

Última actualización: 2026-11-21, Carlos Ruidiaz (Fase 7, cierre, en revisión).

## Resumen

Entregable 2 (60 % de la nota), semana académica 16. Las capas `crypto/`, `storage/`, `vault/` y `web/` están terminadas y probadas. La bóveda se usa desde la interfaz web local (`python -m pvlt.web` o el comando `pvlt`) o desde el CLI mínimo (`python -m pvlt.cli` o `pvlt-cli`). Los experimentos E1, E2 y E3 están medidos, con sus CSV y gráficas en `bench/results/`. El cierre (README, guion de demostración e informe en LaTeX) está escrito en la rama `docs/cierre` y espera la revisión del equipo.

La suite tiene 667 pruebas en verde dentro del contenedor, con `mypy` estricto y `ruff` sin avisos. Cubre todas las pruebas del diseño, de T1 a T13, y los scripts de los experimentos.

## Fases

| Fase | Contenido | Estado | Responsable | Rama |
|---|---|---|---|---|
| 0 | Andamiaje, Docker, dependencias, verificación del entorno | Terminada | Carlos Ruidiaz | fusionada |
| 1 | `crypto/`: KEK con Argon2id, AEAD, aleatoriedad, borrado. T10 | Terminada | Carlos Ruidiaz | fusionada |
| 2 | `storage/`: formato v1, comprobaciones 1 y 2, guardado atómico, lock. T4 (formato), T5 (sin claves), T7 | Terminada | Claudia Elias | fusionada |
| 3 | `vault/`: entradas, operaciones, sesión, generador. T1, T2, T3, T6, T8, T11 y el resto de T4 y T5 | Terminada | Carlos Ruidiaz | fusionada |
| 4 | CLI mínimo con `getpass` | Terminada | Juan Bolivar | `feat/cli` |
| 5 | `web/`: FastAPI, seguridad HTTP, frontend. T9, T12, T13 | Terminada | Claudia Elias | `feat/web` |
| 6 | Experimentos E1, E2, E3 y gráficas | Terminada | Juan Rojas | `feat/bench` |
| 7 | README, guion de demostración, informe final | **En revisión** | Carlos Ruidiaz | `docs/cierre` |

La fase 7 está en la rama `docs/cierre`, sin fusionar, para que el resto del equipo la revise antes de entregarla.

El detalle de cada fase, con sus casillas, está en [`plan_implementacion.md`](plan_implementacion.md). Las fases 5 y 6 pueden avanzar en paralelo una vez exista la 4.

## Siguiente paso

**Revisar la Fase 7 y entregar.** Todo el producto está terminado. Lo que falta es que cada integrante revise la rama `docs/cierre` y, con el visto bueno de todos, fusionarla en `main`:

```
git fetch origin
git switch docs/cierre
```

- `README.md`: seguir la instalación desde cero en un clon limpio y comprobar que cada comando funciona tal como está escrito.
- `python -m scripts.demo` dentro del contenedor (ver "Cómo se ejecuta la demostración"). Debe terminar con «Todas las comprobaciones pasaron».
- El guion manual de la interfaz web del README, de principio a fin, incluida la restauración del respaldo.
- `docs/informe/informe.pdf`: leerlo completo. Comprobar números, redacción, que no tenga punto y coma y que no pase de 12 páginas. Las correcciones van en `informe.tex` y luego se recompila.
- Decidir si se agrega algo del Entregable 1 que falte en el informe o si alguna sección debe recortarse.

Quien haga correcciones las sube en la misma rama con commits a su nombre y lo anota en la bitácora. El merge en `main` lo hace Carlos Ruidiaz cuando el equipo esté de acuerdo.

### Cómo se ejecuta la demostración

```
docker compose build
docker compose run --rm app python -m scripts.demo
docker compose run --rm app python -m scripts.demo --config B --keep
```

- Recorre en una carpeta temporal los siete escenarios exigidos (T1 a T8 en vivo) con 50 comprobaciones `[OK]` o `[FALLO]`, sin mostrar ninguna contraseña. Tarda alrededor de un minuto.
- `scripts/damage.py` invierte un bit de un archivo, para la demostración manual de la restauración del respaldo en la interfaz web: `docker compose run --rm app python -m scripts.damage /data/boveda.pvlt` con el servidor detenido.

### Cómo se compila el informe

El informe está en `docs/informe/informe.tex`, y `informe.pdf` se versiona junto a él. Las gráficas se leen directamente de `bench/results/`. Para compilar hace falta una imagen con LaTeX, que se construye una vez:

```
docker build -t pvlt-informe docs/informe
docker run --rm -v "${PWD}:/work" -w /work/docs/informe pvlt-informe latexmk -pdf informe.tex
docker run --rm -v "${PWD}:/work" -w /work/docs/informe pvlt-informe latexmk -c
```

El segundo comando genera `informe.pdf` y el tercero borra los auxiliares, que además están en `.gitignore`. Desde Git Bash hay que anteponer `MSYS_NO_PATHCONV=1` y usar `$(pwd -W)` en lugar de `${PWD}`.

### Resultados de los experimentos

Equipo de referencia: Intel Core i5-10300H (8 hilos), Windows 10 Pro con Docker Desktop sobre WSL2, máquina virtual de 3,83 GiB, Python 3.12.16, `cryptography` 50.0.2 y OpenSSL 4.0.3. Todo está en `bench/results/sistema.csv`.

- **E1, desbloqueo** (mediana de 20, `e1_argon2.csv`): A 0,109 s y 98 MiB de pico, B 0,422 s y 290 MiB, C 1,908 s y 2 082 MiB. El pico menos la base del proceso coincide con la memoria de Argon2id con un margen de 1 MiB.
- **Configuración final: B.** Es la de mayor memoria que desbloquea en 1 s o menos. C casi duplica ese límite. B ya era el valor por defecto, así que no cambia ningún parámetro.
- **Carriles** (`e1_carriles.csv`): con 256 MiB y 3 pasadas el desbloqueo pasa de 0,840 s con 1 carril a 0,528 s con 2 y 0,414 s con 4. El tiempo de CPU se mantiene entre 0,83 y 0,99 s, y el cociente CPU sobre pared sube de 1,00 a 1,57 y 2,40. Los carriles sí corren en paralelo, aunque con 4 la ganancia no llega a ser de 4 veces.
- **Costo de diccionario** (`e1_diccionario.csv`): con B, recorrer RockYou (1,43·10^7 candidatos) cuesta unas 1 683 horas de pared en este equipo, y una contraseña de 40 bits unos 14 700 años. Es t × |D| en hardware como este. Un atacante con GPU o muchos núcleos lo reduce, y el informe debe decirlo.
- **E2** (mediana de 50, `e2_abrir_guardar.csv`): guardar cuesta entre 4 y 9 ms y abrir entre 0,4 y 12,8 ms para 1 a 500 entradas. El guardado lo domina la escritura atómica con `fsync`, y la apertura de 500 entradas la domina el análisis estricto del JSON, no el AEAD. Frente al Argon2id de B, abrir y guardar no pesan.
- **E3** (`e3_tamano.csv`): la parte fija ocupa 183 bytes (cabecera, sobre, etiqueta de C y resumen). Por debajo de unas 14 entradas el archivo mide 4 279 bytes por el relleno a 4 096. Desde 100 entradas, el archivo ocupa como mucho un 3 % más que el JSON.

### Cómo se repiten los experimentos

```
docker compose build
docker compose run --rm -e PVLT_BENCH_HOST="descripción del anfitrión" -v "${PWD}/bench/results:/app/bench/results" app python -m bench.run_all
```

- Tarda unos 5 minutos. `--quick` lo recorre con pocas repeticiones y sin C, solo para comprobar que funciona. Sus números no valen para el informe.
- Cada experimento también se ejecuta por separado: `python -m bench.e1_argon2`, `bench.e2_open_save`, `bench.e3_size` y `bench.plots`.
- Los CSV de resumen y las PNG se versionan. Las mediciones por repetición quedan en `bench/results/raw/`, que no se versiona.
- E1 necesita algo más de 2 GiB libres en Docker para C. Si el proceso muere por falta de memoria, mide la alternativa del diseño (1 GiB y 2 pasadas) y la anota como C'.
- Mientras se mide no conviene ejecutar nada pesado en el equipo, porque altera los tiempos.

### Cómo se usa la interfaz web

```
docker compose build
docker compose run --rm --service-ports app            # o: docker compose up
docker compose run --rm --service-ports app python -m pvlt.web --vault /data/otra.pvlt
```

- `docker compose run` no publica el puerto si no se le pasa `--service-ports`. `docker compose up` sí lo publica, porque la imagen arranca `python -m pvlt.web` por defecto.
- Se abre la URL `http://127.0.0.1:8765/#t=...` que se imprime en la terminal. Sirve una sola vez. Recargar la página conserva la sesión, pero otra pestaña o navegador necesita reiniciar pvlt. Ctrl+C cierra el servidor y bloquea la bóveda.
- Fuera de Docker, `python -m pvlt.web [--vault RUTA] [--port N] [--no-browser]` escucha en `127.0.0.1` con un puerto aleatorio y abre el navegador.
- Exportar e importar trabajan con archivos `.pvlt` de la carpeta de la bóveda (en el contenedor, el volumen `/data`). Para sacarlos del volumen: `docker compose cp`, o montar una carpeta del anfitrión.
- La API vive en `pvlt/web/app.py`. Todas las rutas `/api/` salvo el canje del token exigen la cookie y la cabecera `X-CSRF-Token`. Los códigos HTTP son 401 sin sesión, 403 por Host, Origin o CSRF, 400 contraseña incorrecta, 404 sin bóveda o entrada inexistente, 409 el archivo ya existe, 422 dato inválido, formato no reconocido, archivo dañado o contenido manipulado (el campo `error` los distingue) y 423 sesión bloqueada.
- Para la demo del respaldo: dañar un byte de la bóveda con el servidor parado y arrancarlo. La página ofrece restaurar el `.bak` y pide confirmación.

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
| 2026-11-19 | `playwright` 1.65.2 entra en `requirements.txt` y Chromium sin interfaz (`--only-shell`) se instala en la imagen de referencia | T12 y T13 corren con los mismos comandos que el resto de la suite. La imagen pasa a ocupar unos 1,5 GB |
| 2026-11-19 | Exportar e importar desde la web usan un nombre de archivo en la carpeta de la bóveda, no subida ni descarga | Reutiliza `Vault.export` e `import_preview` sin tocar `vault/` ni añadir dependencias, y no crea temporales fuera del guardado atómico |
| 2026-11-19 | El CSRF se exige en todas las rutas `/api/` salvo el canje, incluidas las de lectura | Las lecturas devuelven sitios, usuarios y contraseñas. Es más simple y más estricto que distinguir por método |
| 2026-11-19 | El token CSRF vive en `sessionStorage` y no hay ruta que lo reentregue a partir de la cookie | Las cookies no distinguen puertos. Un servidor ajeno en otro puerto local podría recibir la cookie, pero no el token CSRF |
| 2026-11-19 | Un hilo borra la KEK al vencer la inactividad aunque no lleguen peticiones | La comprobación de `Vault` es perezosa. Sin el hilo, la KEK seguiría en memoria hasta la siguiente petición |
| 2026-11-19 | `pvlt.web` importa de `pvlt.storage` solo `FormatError`, `CorruptedFileError`, `VaultLockedError`, `FileStatus` y `RecoveryReport` | El mismo criterio que el CLI. Son excepciones y estados que nacen en esa capa y la interfaz debe traducirlos |
| 2026-11-19 | `pvlt.web` también pasa `mypy` en modo estricto | Igual que el CLI, es una interfaz que maneja contraseñas |
| 2026-11-19 | Las pruebas de navegador llevan la marca `browser` | Se ejecutan por defecto. Si `playwright` o Chromium no están instalados se omiten solas, y `-m "not browser"` las excluye |
| 2026-11-21 | La configuración final de Argon2id es B (256 MiB, 3 pasadas, 4 carriles) | E1: es la de mayor memoria con un desbloqueo de 1 s o menos (0,422 s). C tarda 1,908 s |
| 2026-11-21 | E1 mide `Vault.unlock` completo, cada configuración en un proceso hijo propio | Es lo que espera el usuario. El pico `ru_maxrss` de un proceso nuevo pertenece solo a esa configuración |
| 2026-11-21 | Los carriles se comprueban con el cociente entre tiempo de CPU y tiempo de pared, variando solo `parallelism` sobre B | `process_time` suma la CPU de todos los hilos. Un cociente mayor que 1 prueba que trabajan a la vez |
| 2026-11-21 | E2 usa una KEK aleatoria y mide por separado sellar, escritura atómica, lectura con comprobaciones 1 y 2, y comprobaciones 3 y 4 con el JSON | Excluye Argon2id, como pide el diseño, y muestra qué domina cada operación |
| 2026-11-21 | `matplotlib` entra en `requirements.txt` | Las gráficas se generan con los mismos comandos y en la misma imagen que el resto |
| 2026-11-21 | `bench/` pasa `mypy` en modo estricto y `ruff`, con S105 permitido por la contraseña sintética fija | Los scripts forman parte de lo que se evalúa (métricas reproducibles) |
| 2026-11-21 | El comando `pvlt` arranca la interfaz web y el CLI pasa a ser `pvlt-cli` | Es lo que describe el Entregable 1. Así no hay desviación que explicar |
| 2026-11-21 | La demostración es un script de Python (`scripts/demo.py`) sobre la API de `vault/`, no un guion de shell sobre el CLI | El CLI pide las contraseñas con `getpass` y no se puede automatizar sin pasarlas por argumentos. El script muestra cada escenario con su comprobación explícita |
| 2026-11-21 | El informe se escribe en LaTeX en `docs/informe/` y el PDF se versiona | Acuerdo del equipo. El PDF compilado queda disponible para revisar sin instalar LaTeX |

## Pendientes y advertencias

- **El resumen SHA-256 no protege contra manipulación.** Quien altera un campo y recalcula el resumen supera las comprobaciones 1 y 2. `tests/storage/test_format.py` lo deja explícito. La Fase 3 debe demostrar que las etiquetas AEAD rechazan esos archivos.
- **Los números de E1 dependen del equipo.** La regla de 1 s se aplicó en el equipo de referencia descrito arriba. En otro equipo B puede tardar más o menos, y el informe debe presentar la decisión ligada a ese equipo.
- **Reconstruir la imagen tras cada cambio.** El código se copia a la imagen, no se monta. Sin `docker compose build` las pruebas corren contra la versión anterior.
- **Docker Desktop no arranca y muestra "remove ...sock: El sistema no tiene acceso al archivo".** Pasa si se lanza dos veces o tras un cierre brusco. Se arregla finalizando todos los procesos de Docker desde el Administrador de tareas y abriéndolo una sola vez. No hace falta "Reset to factory defaults".
- **La suite completa tarda cerca de dos minutos** en el contenedor. Para iterar, `pytest -m "not slow"` o un solo archivo.
- **Las pruebas también pasan en Windows** con Python 3.14, salvo dos de permisos POSIX que se omiten solas. Sirve para iterar rápido, pero la referencia sigue siendo el contenedor.
- **Ventana en el cambio de contraseña:** entre el guardado y la reescritura del respaldo, el `.bak` todavía abre con la contraseña anterior. Está documentado en `diseno.md` §4.9. Conviene mencionarlo en el informe como limitación.
- **Timeouts de PyPI** al regenerar `requirements.txt`. Usar `PIP_DEFAULT_TIMEOUT=120` como indica la guía.
- **Rutas en Git Bash.** Al pasar rutas del contenedor (`/tmp/...`, `/app`) a `docker run` desde Git Bash, este las convierte en rutas de Windows. Hay que anteponer `MSYS_NO_PATHCONV=1` o usar PowerShell.
- **La gráfica de E3 dibuja escalones engañosos.** `bench/results/e3_tamano.png` une los puntos medidos con escalones planos, lo que sugiere que entre dos mediciones el archivo ocupa menos que el JSON, y no es así. El informe usa una tabla en su lugar. Si se corrige `bench/plots.py` (por ejemplo, trazando solo los puntos medidos), hay que regenerar la gráfica.
- **Token en los argumentos del navegador (limitación).** Fuera de Docker, mientras el sistema lanza el navegador, la URL con el token aparece en los argumentos de ese proceso. Se mitiga porque el token sirve una sola vez. Conviene mencionarlo en el informe junto a A4.
- **Aviso de Starlette en las pruebas.** `TestClient` emite `StarletteDeprecationWarning` porque recomienda `httpx2`. No afecta a nada y se deja hasta que haya que actualizar dependencias.

## Bitácora

Una entrada por sesión de trabajo que termine en push, la más reciente arriba. Formato: fecha, quién, rama, qué se hizo, qué quedó pendiente o a medias, y avisos para quien sigue.

### 2026-11-21 · Carlos Ruidiaz · `docs/cierre`

- Fase 7 escrita y en revisión, sin fusionar en `main`.
- `README.md` con instalación desde cero (Docker y local), uso de la web y del CLI, pruebas, guion de demostración automático y manual, experimentos y límites de seguridad.
- `scripts/demo.py` recorre los escenarios exigidos con 50 comprobaciones, y `scripts/damage.py` sirve para la demostración manual del respaldo. Dos pruebas nuevas en `tests/test_demo.py`. Ambos scripts pasan `mypy` estricto.
- `docs/informe/`: informe final en LaTeX con su PDF y el `Dockerfile` para compilarlo.
- El comando `pvlt` apunta ahora a la web y el CLI a `pvlt-cli`. Cambian `pyproject.toml` y el `prog` de los dos analizadores de argumentos.
- Suite completa (667 pruebas), `mypy`, `ruff` y la demostración en verde dentro de Docker sobre un clon limpio de la rama. Instalado con `pip`, `pvlt` abre la web y `pvlt-cli` el CLI.
- Sigue: revisión del equipo (ver "Siguiente paso") y merge.

### 2026-11-21 · Juan Rojas · `feat/bench`

- Fase 6 completa: `bench/common.py`, `e1_argon2.py`, `e2_open_save.py`, `e3_size.py`, `plots.py` y `run_all.py`.
- Resultados medidos en el contenedor y versionados en `bench/results/`: seis CSV de resumen (incluido `sistema.csv`) y cinco gráficas. El resumen está arriba, en "Resultados de los experimentos".
- La configuración final de Argon2id es B, que ya era el valor por defecto. No cambian `pvlt/params.py` ni el formato.
- E1 confirma que los carriles corren en paralelo, lo que cierra el aviso abierto en la Fase 0.
- 11 pruebas nuevas en `tests/bench/`. Ejecutan los scripts con ajustes mínimos y comprueban que ningún CSV ni ninguna PNG contiene la contraseña sintética ni datos de entradas.
- Fuera de `bench/` cambian `requirements.in` y `requirements.txt` (`matplotlib`) y `pyproject.toml` (`mypy` estricto y `ruff` en `bench/`).
- Se corrige una carrera en `test_t12_a_second_copy_restarts_the_timer`, que fallaba siempre en este equipo (también en `main`). La prueba daba la copia por terminada al ver el aviso anterior y leía el portapapeles antes de que se vaciara. Solo cambia la prueba, no la interfaz.
- Sigue: Fase 7 (cierre).

### 2026-11-19 · Claudia Elias · `feat/web`

- Fase 5 completa: `pvlt/web/security.py`, `errors.py`, `schemas.py`, `app.py`, `server.py` y `__main__.py`, y el frontend en `pvlt/web/static/` (HTML, CSS y JS propios, sin nada en línea).
- Seguridad HTTP según `diseno.md` §8: token de arranque de un solo uso en el fragmento, cookie `HttpOnly` y `SameSite=Strict`, CSRF, Host y Origin, CSP con `frame-ancestors 'none'`, `no-store` y log de acceso desactivado. Las concreciones quedan anotadas en §8.
- La API cubre estado, crear, desbloquear, bloquear, restaurar el respaldo, entradas, contraseña de una entrada, generador, ajustes, cambio de contraseña, exportación e importación con vista previa.
- 186 pruebas nuevas en `tests/web/`. T13 por HTTP sobre cada ruta, T9 con el servidor real como subproceso y T12 y T13 en Chromium con Playwright.
- Fuera de `web/` cambian `requirements.in` y `requirements.txt` (`playwright`), el `Dockerfile` (Chromium sin interfaz) y `pyproject.toml` (estáticos como datos del paquete y `mypy` estricto en `pvlt.web`).
- Sigue: Fase 6 (experimentos) y después la Fase 7.

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
