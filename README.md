# pvlt · Gestor local de contraseñas con Argon2id y AEAD

Proyecto final de Criptografía Aplicada (Universidad del Norte), Proyecto 2 del banco de proyectos. Docente: Ricardo Luis Villanueva-Polanco.

Equipo: Carlos Ruidiaz, Juan Bolivar, Juan Rojas y Claudia Elias.

`pvlt` es un gestor de contraseñas de un solo usuario que funciona por completo en el equipo, sin red ni sincronización. La bóveda guarda entre 1 y 500 credenciales (sitio, usuario, contraseña y notas) cifradas bajo una contraseña maestra. Se usa desde una interfaz web local o desde un CLI mínimo.

## Contenido

1. [Qué hace](#qué-hace)
2. [Antes de empezar](#antes-de-empezar)
3. [Instalación paso a paso](#instalación-paso-a-paso)
4. [Primer uso de la interfaz web](#primer-uso-de-la-interfaz-web)
5. [Guion de demostración](#guion-de-demostración)
6. [Pruebas automatizadas](#pruebas-automatizadas)
7. [Experimentos](#experimentos)
8. [Uso del CLI](#uso-del-cli)
9. [Instalación local sin Docker](#instalación-local-sin-docker)
10. [Problemas frecuentes](#problemas-frecuentes)
11. [Cómo funciona por dentro](#cómo-funciona-por-dentro)
12. [Documentación e informe](#documentación-e-informe)

## Qué hace

- Crear, desbloquear y bloquear la bóveda. El bloqueo ocurre con un botón, al cerrar el programa o tras 5 minutos de inactividad (configurable entre 30 s y 1 h).
- Agregar, buscar, consultar, copiar, modificar y eliminar credenciales. La lista se ordena alfabéticamente por sitio.
- Generador de contraseñas configurable (longitud de 8 a 128 y cuatro clases de caracteres) que muestra la entropía.
- Cambiar la contraseña maestra sin perder registros.
- Exportar e importar solo en formato cifrado, con contraseña propia y vista previa de conflictos.
- Guardado atómico con respaldo y recuperación tras un fallo o un archivo dañado.

## Antes de empezar

Hace falta:

| Qué | Para qué | Cómo comprobarlo |
|---|---|---|
| **Git** | Descargar el repositorio | `git --version` |
| **Docker** con Docker Compose (Docker Desktop en Windows o macOS) | Ejecutar `pvlt` en la plataforma de referencia: Linux con Python 3.12 dentro de un contenedor | `docker compose version` |
| Unos 2 GB libres en disco | La imagen, que incluye Chromium sin interfaz para las pruebas de navegador | |
| Algo más de 2 GiB de memoria libre para Docker | Solo para medir la configuración C de Argon2id (2 GiB). El uso normal no lo requiere | |

En Windows, Docker Desktop tiene que estar **abierto** antes de ejecutar cualquier comando `docker`. Si no lo está, los comandos fallan con un error del tipo `cannot connect to the Docker daemon`.

Los comandos de este README están pensados para **PowerShell** en Windows o para la terminal de Linux y macOS. En Git Bash, los comandos que llevan una ruta `/data/...` necesitan `MSYS_NO_PATHCONV=1` delante, como se explica en [Problemas frecuentes](#problemas-frecuentes).

## Instalación paso a paso

**1. Descargar el repositorio** y entrar en su carpeta. Todos los comandos siguientes se ejecutan desde ahí.

```
git clone https://github.com/CarlosRuidiaz/Gestor-local-de-contrase-as.git
cd Gestor-local-de-contrase-as
```

**2. Construir la imagen.** La primera vez tarda varios minutos, porque descarga Python, las dependencias y Chromium. Las siguientes veces reutiliza lo ya descargado.

```
docker compose build
```

Termina sin errores y la imagen queda con el nombre `pvlt:dev`. Las dependencias se instalan desde `requirements.txt` con `pip install --require-hashes`, así que si el hash de algún paquete no coincide la construcción se detiene. Las versiones están fijadas con `pip-tools` a partir de `requirements.in`.

**3. Comprobar que todo funciona** (opcional, unos 4 minutos):

```
docker compose run --rm app pytest
```

Debe terminar con una línea como `673 passed`. Más detalles en [Pruebas automatizadas](#pruebas-automatizadas).

> Si se modifica el código, hay que repetir `docker compose build`. El código se copia dentro de la imagen y no se lee desde la carpeta.

## Primer uso de la interfaz web

**1. Arrancar `pvlt`:**

```
docker compose up
```

La terminal muestra algo como esto:

```
pvlt escucha en http://127.0.0.1:8765/ (bóveda: /data/boveda.pvlt)
Abre esta URL en el navegador: http://127.0.0.1:8765/#t=...
El enlace sirve una sola vez. Ctrl+C cierra pvlt y bloquea la bóveda.
```

**2. Abrir el enlace.** Hay que copiar la URL completa, **incluida la parte `#t=...`**, y pegarla en el navegador. Esa parte es un token de un solo uso: al cargar la página se canjea por una cookie de sesión y desaparece de la barra de direcciones.

- Recargar la página (F5) conserva la sesión.
- Abrir otra pestaña u otro navegador muestra «Sesión no disponible», porque el enlace ya se usó. Para entrar desde otra pestaña hay que reiniciar `pvlt` (paso 5) y abrir el enlace nuevo. Se puede pegar en la misma pestaña.

**3. Crear la bóveda.** La primera vez aparece la pantalla «Crear bóveda»:

- Escribir la contraseña maestra (de 8 a 1024 caracteres) y repetirla.
- Dejar la configuración de Argon2id en **B (recomendada)**. La A es más rápida y más débil, y la C necesita 2 GiB de memoria. La sección [Elegir la configuración en otro equipo](#elegir-la-configuración-en-otro-equipo) explica cómo decidir.
- Pulsar **Crear**. Si el navegador ofrece guardar la contraseña, conviene rechazarlo.

Aparece la pantalla principal con la lista vacía y los botones **Nueva entrada**, **Generador**, **Contraseña maestra**, **Exportar**, **Importar** y **Ajustes**. Arriba están el botón **Bloquear** y la cuenta atrás «Bloqueo automático en N s».

**4. Usarla.** [La demostración en la interfaz web](#demostración-en-la-interfaz-web) recorre cada operación paso a paso.

**5. Cerrar.** Pulsar **Ctrl+C** en la terminal donde corre `docker compose up`. La terminal muestra «pvlt cerrado. La bóveda quedó bloqueada.» Para volver a entrar se repite desde el paso 1. Cada arranque imprime un enlace nuevo, y la bóveda creada sigue ahí.

**Dónde se guarda la bóveda.** En el volumen de Docker `pvlt-data`, en `/data/boveda.pvlt`. Junto a ella están su respaldo `boveda.pvlt.bak` y, si se exporta, los archivos de exportación. El volumen sobrevive al cerrar `pvlt` y al reiniciar el equipo. El puerto solo se publica en la interfaz local (`127.0.0.1:8765`), así que ningún otro equipo puede conectarse.

**Otras tareas con la bóveda:**

| Para | Comando |
|---|---|
| Ver los archivos del volumen | `docker compose run --rm app ls -l /data` |
| Usar otra bóveda en el mismo volumen | `docker compose run --rm --service-ports app python -m pvlt.web --vault /data/otra.pvlt` |
| Copiar una exportación al equipo (con `pvlt` en marcha) | `docker compose cp app:/data/exportacion.pvlt .` |
| **Borrar todo** y empezar de cero | `docker compose down -v` |

`docker compose down -v` elimina el volumen con la bóveda, su respaldo y las exportaciones, y no se puede deshacer. Solo debe usarse con bóvedas de prueba.

## Guion de demostración

La demostración tiene dos partes. La automática recorre en un minuto todos los escenarios que pide el enunciado y comprueba cada resultado. La manual, en la interfaz web, muestra lo mismo como lo vería un usuario. Todos los datos son sintéticos: **no se debe usar ninguna contraseña real**.

### Preparar una demostración desde cero

Para empezar con una bóveda nueva, sin restos de pruebas anteriores:

```
docker compose down -v
docker compose build
```

El primer comando borra el volumen de datos (ver la advertencia de la sección anterior).

### Demostración automática

```
docker compose run --rm app python -m scripts.demo
```

Trabaja en una carpeta temporal dentro del contenedor, así que no toca la bóveda del volumen. No muestra ninguna contraseña. Cada comprobación imprime `[OK]` o `[FALLO]`, y al final aparece «Todas las comprobaciones pasaron.» Tarda alrededor de un minuto, casi todo en los 500 guardados del primer escenario.

| Escenario | Qué comprueba |
|---|---|
| 1 | Crear, cerrar y reabrir bóvedas con 1, 100 y 500 entradas, y que ningún dato aparece en claro en el archivo |
| 2 | Agregar con el generador, buscar, consultar, modificar y eliminar, y el bloqueo por inactividad con un reloj simulado |
| 3 | Cambiar la contraseña maestra: la nueva abre la bóveda y el respaldo, la anterior ya no |
| 4 | Una contraseña incorrecta se rechaza sin tocar ningún archivo ni crear una bóveda vacía. También un archivo truncado, una versión desconocida y una memoria de Argon2id fuera de límite |
| 5 | Un bit alterado en la sal, el identificador, la generación, los nonces, W, C y sus etiquetas se detecta aunque el atacante recalcule el resumen. También un byte dañado sin recalcular el resumen y el contenido de otra bóveda |
| 6 | Una caída simulada tras cada paso del guardado atómico deja siempre una versión íntegra. Después se daña la bóveda y se restaura el respaldo |
| 7 | La exportación no tiene texto claro, la importación con la contraseña equivocada se rechaza y una importación con conflicto se aplica |

Opciones: `--config B` usa la configuración final de Argon2id en lugar de la A, y `--keep` conserva los archivos generados para inspeccionarlos.

### Demostración en la interfaz web

Antes de empezar, arrancar `pvlt` con `docker compose up` y abrir el enlace como se explica en [Primer uso](#primer-uso-de-la-interfaz-web). Cada paso dice qué hacer y qué debe verse.

**1. Crear la bóveda**
- Hacer: escribir `demo-maestra-1` como contraseña maestra, repetirla, dejar la configuración B y pulsar **Crear**.
- Debe verse: la pantalla principal con la lista vacía.
- Variante: si las dos contraseñas no coinciden, aparece «Las contraseñas no coinciden» y no se crea nada.

**2. Agregar entradas con el generador**
- Hacer: pulsar **Nueva entrada** y escribir un sitio (por ejemplo `correo.ejemplo`) y un usuario. Junto al campo de contraseña pulsar **Generar**.
- Debe verse: la contraseña generada en el campo y su entropía en el aviso. Al pulsar **Guardar** aparece «Entrada guardada.» y la entrada en la lista. Repetir con dos o tres sitios más.
- Generador aparte: el botón **Generador** de la barra permite elegir la longitud (8 a 128) y las clases de caracteres, y muestra la entropía en bits. **Guardar como predeterminado** fija esas opciones para el botón **Generar** de las entradas.

**3. Buscar**
- Hacer: escribir parte de un sitio o usuario en el cuadro de búsqueda.
- Debe verse: la lista se filtra mientras se escribe, sin pedir nada al servidor.

**4. Consultar y copiar**
- Hacer: pulsar **Ver** en una fila. En el detalle, pulsar **Ver** para mostrar la contraseña y **Copiar** para copiarla. Pegarla en un editor de texto antes de 20 s.
- Debe verse: el aviso «se vaciará en 20 s». Pasados 20 s aparece «Portapapeles vaciado.» y al pegar de nuevo no sale nada.
- Variante: copiar, cambiar a otra ventana y esperar más de 20 s. El navegador no permite vaciar el portapapeles sin foco, así que al volver a la pestaña aparece un aviso de que el portapapeles todavía tiene la contraseña y el vaciado se completa en ese momento.

**5. Modificar y eliminar**
- Hacer: en el detalle, pulsar **Editar**, cambiar el usuario o las notas y **Guardar**. Después, en otra entrada, pulsar **Eliminar** y confirmar.
- Debe verse: el cambio en la lista, y la entrada eliminada desaparece tras la pregunta «¿Eliminar esta entrada? No se puede deshacer.»
- Variante: un sitio vacío o de solo espacios se rechaza al guardar.

**6. HTML en las notas se muestra como texto**
- Hacer: editar una entrada y escribir en las notas `<img src=x onerror=alert(1)>`. Guardar.
- Debe verse: el texto tal cual en el detalle, sin imagen ni ventana de alerta.

**7. Bloquear y contraseña incorrecta**
- Hacer: pulsar **Bloquear**. Escribir una contraseña equivocada y pulsar **Desbloquear**.
- Debe verse: «Contraseña incorrecta». La bóveda no cambia y no se crea ninguna vacía. Después, con `demo-maestra-1`, se abre con todas las entradas.

**8. Bloqueo por inactividad**
- Hacer: pulsar **Ajustes**, escribir `30` en «Bloqueo por inactividad, en segundos» y **Guardar**. No tocar la página durante 30 s.
- Debe verse: la cuenta atrás de arriba pasa a 30 s al guardar, y al llegar a cero la página vuelve a pedir la contraseña con el aviso «La bóveda se bloqueó por inactividad.», que se ve durante unos segundos.
- Al terminar conviene volver a poner `300`, para que no se bloquee durante el resto de la demostración.

**9. Cambiar la contraseña maestra**
- Hacer: pulsar **Contraseña maestra**, escribir la actual (`demo-maestra-1`) y una nueva (`demo-maestra-2`) dos veces, y pulsar **Cambiar**. Después **Bloquear**.
- Debe verse: la antigua ya no abre la bóveda («Contraseña incorrecta») y la nueva sí, con todas las entradas.

**10. Exportar e importar**
- Hacer: pulsar **Exportar**, dejar el nombre `exportacion.pvlt`, escribir una contraseña de exportación (por ejemplo `demo-exportar-1`) dos veces y pulsar **Exportar**.
- Debe verse: «Exportadas N entradas a exportacion.pvlt.»
- Después pulsar **Importar**, elegir `exportacion.pvlt` en la lista de archivos, escribir la contraseña de exportación y pulsar **Vista previa**.
- Debe verse: «El archivo tiene N entradas, N en conflicto.», porque todas ya están en la bóveda. Para cada una se elige **Omitir**, **Sustituir** o **Conservar ambas** en la columna «Decisión», y **Aplicar** lo ejecuta en un solo guardado. El aviso resume cuántas se añadieron, sustituyeron, duplicaron u omitieron, y con «Conservar ambas» la entrada aparece dos veces en la lista.
- Variante: con una contraseña de exportación equivocada aparece «Contraseña incorrecta» y no se muestra la vista previa.

**11. Recuperación tras un archivo dañado**
- Hacer: detener `pvlt` con **Ctrl+C**. Dañar un bit de la bóveda y volver a arrancar:

    ```
    docker compose run --rm app python -m scripts.damage /data/boveda.pvlt
    docker compose up
    ```

    El primer comando responde «Se invirtió un bit del byte 200 de /data/boveda.pvlt.»
- Abrir el enlace nuevo que imprime la terminal.
- Debe verse: «La bóveda está dañada, pero el respaldo está bien» y el botón **Restaurar el respaldo**. Al pulsarlo y confirmar, aparece «Respaldo restaurado», el archivo dañado se conserva aparte como `boveda.pvlt.damaged-<fecha>` y la bóveda se abre con la contraseña `demo-maestra-2` en su versión anterior. El respaldo es la versión previa al último guardado, así que la última operación (en este guion, la importación) no aparece.

**12. Comprobar que no queda texto claro en disco**
- Hacer: detener `pvlt` con **Ctrl+C** y buscar en todos los archivos del volumen el nombre de un sitio guardado, por ejemplo `correo.ejemplo`:

    ```
    docker compose run --rm app sh -c "grep -rl 'correo.ejemplo' /data || echo 'Sin coincidencias'"
    ```

- Debe verse: «Sin coincidencias». Si el sitio apareciera en claro en algún archivo, se imprimiría el nombre de ese archivo.

## Pruebas automatizadas

```
docker compose run --rm app pytest
docker compose run --rm app mypy
docker compose run --rm app ruff check .
docker compose run --rm app ruff format --check .
```

| Comando | Qué hace | Resultado esperado |
|---|---|---|
| `pytest` | La suite completa, de tres a diez minutos según el equipo | `673 passed` |
| `mypy` | Revisión de tipos en modo estricto | `Success: no issues found` |
| `ruff check .` | Estilo y reglas de seguridad de bandit | `All checks passed!` |
| `ruff format --check .` | Formato del código | `... files already formatted` |

Las pruebas funcionales usan la configuración A de Argon2id (64 MiB) para ir más rápido. Para iterar, `pytest -m "not slow"` excluye las pruebas largas y `pytest -m "not browser"` las de navegador.

La suite cubre las pruebas T1 a T13 del diseño, además de los experimentos y el guion de demostración:

| Prueba | Qué comprueba | Dónde |
|---|---|---|
| T1 | Crear, cerrar y reabrir con 1, 100 y 500 entradas, todas las operaciones y el bloqueo por inactividad | `tests/vault/test_vault.py` |
| T2 | Cambio de contraseña maestra: la nueva abre bóveda y respaldo, la antigua no | `tests/vault/test_vault.py` |
| T3 | Ningún dato sintético aparece en claro en el archivo | `tests/vault/test_vault.py` |
| T4 | Contraseña incorrecta, archivo truncado, versión desconocida, parámetros fuera de límite | `tests/storage/test_format.py`, `tests/vault/test_tamper.py` |
| T5 | Un bit alterado en cada campo, nonce, etiqueta, W y C, e intercambio de C | `tests/vault/test_tamper.py` |
| T6 | 10 000 guardados sin repetir DEK ni nonce | `tests/vault/test_tamper.py` |
| T7 | Interrupción tras cada paso del guardado y bytes dañados | `tests/storage/test_store.py`, `tests/vault/test_workspace.py` |
| T8 | Exportar e importar con y sin la contraseña de exportación | `tests/vault/test_export_import.py` |
| T9 | La contraseña sintética no aparece en logs, temporales, argumentos ni URL | `tests/web/`, `tests/test_cli.py` |
| T10 | Vectores de RFC 8439 y RFC 9106 | `tests/crypto/` |
| T11 | Generador: longitud, clases y uniformidad (χ²) | `tests/vault/test_generator.py` |
| T12 | El portapapeles se vacía a los 20 s (Playwright) | `tests/web/` |
| T13 | Sin cookie, sin CSRF, Host u Origin ajenos, HTML en notas, carga en iframe | `tests/web/` |

## Experimentos

Los experimentos miden el costo de Argon2id y de abrir y guardar, y producen los CSV y las gráficas del informe.

| Experimento | Qué mide |
|---|---|
| **E1** | Tiempo de desbloqueo (mediana de 20) y pico de memoria para las configuraciones A, B y C de Argon2id, paralelismo de los carriles y costo de un ataque de diccionario |
| **E2** | Abrir y guardar sin Argon2id con 1, 100 y 500 entradas (mediana de 50) |
| **E3** | Tamaño del archivo frente al JSON sin cifrar |

**Prueba rápida** (unos segundos, solo para comprobar que los scripts funcionan). Sus números no son válidos y quedan dentro del contenedor, en `bench/results/quick/`, sin tocar los resultados de referencia:

```
docker compose run --rm app python -m bench.run_all --quick
```

**Medición completa** (unos 5 minutos). Mientras mide conviene no ejecutar nada pesado en el equipo. En PowerShell, Linux o macOS:

```
docker compose run --rm -e PVLT_BENCH_HOST="descripción del equipo" -v "${PWD}/bench/results:/app/bench/results" app python -m bench.run_all
```

La opción `-v` hace que los resultados se escriban en la carpeta `bench/results/` del repositorio, así que **sustituye los resultados de referencia** del informe por los del equipo actual. Si eso no se quiere, basta con omitir `-v` y los resultados se quedan en el contenedor, que se borra al terminar. `PVLT_BENCH_HOST` es solo una descripción del equipo que se guarda en `sistema.csv`.

Resultados en el equipo de referencia (Intel Core i5-10300H, Docker sobre WSL2):

| Configuración | Memoria | Pasadas | Desbloqueo (mediana) | Pico de memoria |
|---|---|---|---|---|
| A | 64 MiB | 3 | 0,109 s | 98 MiB |
| **B (final)** | 256 MiB | 3 | 0,422 s | 290 MiB |
| C | 2 GiB | 1 | 1,908 s | 2 082 MiB |

La configuración final es B, la de mayor memoria que desbloquea en 1 s o menos en el equipo de referencia. Los CSV y las gráficas están en [`bench/results/`](bench/results/).

### Elegir la configuración en otro equipo

La regla de 1 s depende del equipo. Para aplicarla en el que va a usar `pvlt`:

```
docker compose run --rm app python -m bench.calibrate
```

Mide A, B y C con 5 desbloqueos cada una (menos de medio minuto en el equipo de referencia), muestra el tiempo y la memoria de cada una y recomienda la de mayor memoria que desbloquea en 1 s o menos. No escribe ningún archivo. En equipos con poca memoria, `--skip-c` omite la configuración de 2 GiB.

La configuración se elige al crear la bóveda, en el campo «Configuración de Argon2id» de la interfaz web o con `python -m pvlt.cli create --config A|B|C`. Queda guardada en la cabecera del archivo, así que cada bóveda se abre con la suya.

## Uso del CLI

El CLI es un punto de entrada mínimo para pruebas y experimentos. Usa la misma bóveda del volumen que la interfaz web, así que no deben ejecutarse a la vez. Las contraseñas se piden con `getpass`, sin eco, y el resto de datos sensibles (sitio, usuario, notas, búsqueda) se piden por teclado, nunca como argumento.

Ejemplo de uso, con `pvlt` detenido:

```
docker compose run --rm app python -m pvlt.cli --help
docker compose run --rm app python -m pvlt.cli add --generate
docker compose run --rm app python -m pvlt.cli list --search
```

`add` pide la contraseña maestra, el sitio, el usuario y las notas, y genera la contraseña. `list --search` pide el texto a buscar y lista las coincidencias sin contraseñas. Si el volumen no tiene bóveda, se crea con `create`.

| Orden | Qué hace |
|---|---|
| `create [--config A\|B\|C]` | Crea una bóveda vacía (por defecto con la configuración B) |
| `unlock` | Abre la bóveda y la lista |
| `list [--search]` | Lista sin contraseñas, con filtro opcional |
| `get ID [--show]` | Muestra una entrada, y la contraseña solo con `--show` |
| `add [--generate ...]` | Agrega una entrada, con contraseña escrita o generada |
| `change-password` | Cambia la contraseña maestra |
| `export DESTINO [--overwrite]` | Exporta a un archivo cifrado con contraseña propia |
| `import ORIGEN [--on-conflict ask\|skip\|replace\|keep-both]` | Importa una exportación |
| `generate` | Genera una contraseña sin tocar la bóveda |

La ruta se elige con `--vault RUTA`. Sin ella se usa `$PVLT_VAULT_DIR/boveda.pvlt` (en el contenedor, `/data/boveda.pvlt`) o `./boveda.pvlt`. Los códigos de salida están documentados en `pvlt/cli.py`.

## Instalación local sin Docker

Con Python 3.12 o superior, desde la carpeta del repositorio:

```
python -m venv .venv
.venv\Scripts\activate
pip install --require-hashes -r requirements.txt
pip install --no-deps -e .
```

En Linux o macOS, la segunda línea es `source .venv/bin/activate`.

Quedan disponibles dos comandos:

- `pvlt` arranca la interfaz web en `127.0.0.1` con un puerto aleatorio y abre el navegador. Acepta `--vault RUTA`, `--port N` y `--no-browser`. Sin `--vault`, la bóveda es `boveda.pvlt` en la carpeta actual.
- `pvlt-cli` es el CLI descrito arriba.

Fuera de Docker no se garantiza la semántica POSIX de `fsync` y `os.replace` ni los permisos 0600. Windows y macOS son compatibles, pero las mediciones y las pruebas de fallo de referencia se hicieron en el contenedor.

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `cannot connect to the Docker daemon` o similar | Docker Desktop no está abierto. Abrirlo, esperar a que indique que está en marcha y repetir el comando |
| «Sesión no disponible. El enlace de inicio ya se usó o no es válido» | El enlace sirve una sola vez. Detener `pvlt` con Ctrl+C, arrancarlo de nuevo y abrir el enlace nuevo |
| «Sesión no disponible» sin más explicación al abrir la página | Se abrió la dirección sin la parte `#t=...`, o en una pestaña nueva. Copiar la URL completa de la terminal, o reiniciar `pvlt` si ese enlace ya se usó |
| `port is already allocated` al arrancar | Otro programa, o un `pvlt` anterior, usa el puerto 8765. Cerrar la otra terminal o ejecutar `docker compose down` |
| En Git Bash, un comando con `/data` responde `cannot access 'C:/Program Files/Git/data'` o no encuentra el archivo | Git Bash convierte `/data/...` en una ruta de Windows. Anteponer `MSYS_NO_PATHCONV=1` al comando (por ejemplo `MSYS_NO_PATHCONV=1 docker compose run --rm app ls -l /data`), o usar PowerShell |
| Los cambios en el código no se notan | Falta `docker compose build`. El código se copia dentro de la imagen |
| La configuración C falla o el sistema se queda sin memoria | Docker tiene menos de unos 2,5 GiB asignados. Aumentar la memoria en Docker Desktop o usar `--skip-c` al calibrar |
| La página vuelve a pedir la contraseña sola | Es el bloqueo por inactividad. Se ajusta en **Ajustes** |

## Cómo funciona por dentro

### Criptografía

La contraseña maestra deriva una clave de envoltura (KEK) con **Argon2id v1.3** (256 MiB, 3 pasadas, 4 carriles, sal de 128 bits). La KEK cifra con **ChaCha20-Poly1305** una clave de datos (DEK) aleatoria que se renueva en cada guardado y cifra el contenido. La cabecera completa va como dato asociado con etiquetas de dominio separadas. Todo pasa por la biblioteca `cryptography` (pyca), sin primitivas propias.

```
KEK = Argon2id(contraseña, sal, m, t, p)
W   = ChaCha20-Poly1305(KEK).cifrar(N_w, DEK,     "PVLT/v1/wrap" || Hdr)
C   = ChaCha20-Poly1305(DEK).cifrar(N_d, pad(P),  "PVLT/v1/data" || Hdr || W)
```

El formato binario, el protocolo y el modelo de adversario están en [`docs/diseno.md`](docs/diseno.md). El análisis completo está en el informe final ([`docs/informe/`](docs/informe/)).

### Estructura del repositorio

```
pvlt/
  crypto/     Argon2id, ChaCha20-Poly1305, aleatoriedad y borrado. Funciones puras, sin disco
  storage/    formato binario v1, límites, guardado atómico, respaldo y lock. Nunca recibe claves
  vault/      sesión, entradas, operaciones y generador. Única capa que sostiene la KEK
  web/        FastAPI, seguridad HTTP y frontend en HTML, CSS y JS propios
  cli.py      CLI mínimo
  params.py   constantes públicas del protocolo y configuraciones de Argon2id
tests/        pruebas por capa (crypto, storage, vault, web, bench, CLI y demostración)
bench/        experimentos E1, E2 y E3, calibración de Argon2id y resultados en bench/results/
scripts/      guion de demostración, daño controlado de un archivo y verificación del entorno
docs/         especificación técnica, Entregable 1 e informe final
```

Las dependencias van en un solo sentido: `web → vault → (crypto, storage)`. Una prueba de humo lo verifica.

### Límites de seguridad

`pvlt` protege la bóveda frente a quien copia o modifica el archivo cuando la bóveda está cerrada, frente a fallos al guardar y frente a otros usuarios locales y páginas web que intenten usar el servidor. No protege frente a malware, keyloggers, extensiones maliciosas ni volcados de memoria con la bóveda abierta, ni frente a una contraseña maestra débil. El retroceso a una copia antigua válida solo se advierte. Las limitaciones completas están en el informe.

## Documentación e informe

| Archivo | Contenido |
|---|---|
| [`docs/informe/informe.pdf`](docs/informe/informe.pdf) | Informe final (12 páginas), con su fuente LaTeX en la misma carpeta |
| [`docs/diseno.md`](docs/diseno.md) | Especificación técnica: formato, protocolo, seguridad web, pruebas y experimentos |
| [`docs/entregable1/`](docs/entregable1/) | Entregable 1 (diseño y estado del arte) |

Todos los datos de prueba y de demostración son sintéticos.

### Compilar el informe

`docs/informe/informe.pdf` ya está compilado. Para regenerarlo tras cambiar `informe.tex` hace falta una imagen con LaTeX, que se construye una vez:

```
docker build -t pvlt-informe docs/informe
```

Después, para generar el PDF y borrar los archivos auxiliares:

```
docker run --rm -v "${PWD}:/work" -w /work/docs/informe pvlt-informe latexmk -pdf informe.tex
docker run --rm -v "${PWD}:/work" -w /work/docs/informe pvlt-informe latexmk -c
```

Las gráficas se leen directamente de `bench/results/`.
