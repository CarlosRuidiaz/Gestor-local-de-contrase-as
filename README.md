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

**4. Usarla.** [La parte 2 del guion de demostración](#parte-2-demostración-en-la-interfaz-web) recorre cada operación paso a paso.

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

La demostración tiene dos partes. La automática recorre en un minuto todos los escenarios que pide el enunciado y comprueba cada resultado. La manual, en la interfaz web, muestra lo mismo como lo vería un usuario y tarda unos 15 minutos. Todos los datos son sintéticos: **no se debe usar ninguna contraseña real**.

### Antes de la demostración

**Navegador.** Sirven Chrome, Edge, Firefox o Brave. En **Brave**, la primera vez que se copia una contraseña aparece el aviso «http://127.0.0.1:8765 quiere ver el texto y las imágenes copiados en el portapapeles». Hay que pulsar **Permitir**. `pvlt` nunca lee el portapapeles, pero Brave pide ese permiso para dejar que la página lo vacíe a los 20 s. Si se bloquea, el vaciado automático no puede completarse (ver el paso 4).

**Empezar con una bóveda nueva.** Si en el equipo ya hubo pruebas anteriores:

```
docker compose down -v
docker compose build
```

El primer comando borra el volumen de datos con la bóveda que hubiera (ver la advertencia de [Primer uso](#primer-uso-de-la-interfaz-web)). Para conservar una bóveda propia, en lugar de borrarla se puede añadir `-p pvlt-demo` después de `docker compose` en **todos** los comandos de la demostración, por ejemplo `docker compose -p pvlt-demo up`. Así usan un volumen aparte. En ese caso hay que detener antes cualquier otro `pvlt`, porque el puerto 8765 es el mismo.

**Datos que usa el guion.** Los pasos encadenan estos valores, así que conviene usarlos tal cual:

| Dato | Valor |
|---|---|
| Contraseña maestra | `demo-maestra-1`, y desde el paso 9 `demo-maestra-2` |
| Contraseña de exportación | `demo-exportar-1` |
| Entradas (sitio y usuario) | `correo.ejemplo` y `ana.demo`, `banco.ejemplo` y `luis.demo`, `foro.ejemplo` y `eva.demo` |

### Parte 1: demostración automática

```
docker compose run --rm app python -m scripts.demo
```

Trabaja en una carpeta temporal dentro del contenedor, así que no toca la bóveda del volumen. No muestra ninguna contraseña. Cada comprobación imprime `[OK]` o `[FALLO]`, son 49 en total, y al final aparece «Todas las comprobaciones pasaron.» Tarda alrededor de un minuto, casi todo en los 500 guardados del primer escenario.

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

### Parte 2: demostración en la interfaz web

Cada paso dice qué hacer, qué debe verse (con los textos exactos de la página) y, cuando aplica, una variante que muestra el rechazo de una acción incorrecta. Al final de algunos pasos se indica cómo debe quedar la lista, para comprobar que nada se perdió por el camino.

**0. Arrancar y abrir el enlace**
- Hacer: en una terminal, `docker compose up`. Copiar la URL completa que imprime, incluida la parte `#t=...`, y pegarla en el navegador.
- Debe verse: en la terminal, «pvlt escucha en http://127.0.0.1:8765/», la URL y «El enlace sirve una sola vez.». En el navegador, la pantalla «Crear bóveda», y la parte `#t=...` desaparece de la barra de direcciones.
- Variante: abrir `http://127.0.0.1:8765/` en otra pestaña. Aparece «Sesión no disponible», porque el enlace ya se usó. Recargar la primera pestaña (F5) sí conserva la sesión.

**1. Crear la bóveda**
- Hacer: escribir `demo-maestra-1` y, en la repetición, algo distinto. Pulsar **Crear**.
- Debe verse: «Las contraseñas no coinciden», y no se crea nada.
- Hacer: escribir `demo-maestra-1` en los dos campos, dejar la configuración **B (recomendada)** y pulsar **Crear**.
- Debe verse: «Bóveda creada.», la lista vacía y arriba «Bloqueo automático en 300 s».

**2. Agregar entradas con el generador**
- Hacer: pulsar **Nueva entrada**, escribir el sitio `correo.ejemplo` y el usuario `ana.demo`, y pulsar **Generar** junto al campo de contraseña. Pulsar **Guardar**.
- Debe verse: la contraseña generada en el campo y su entropía en el aviso. Al guardar, «Entrada guardada.» y la entrada en la lista.
- Hacer: repetir con `banco.ejemplo` y `luis.demo`, y con `foro.ejemplo` y `eva.demo`.
- Hacer: pulsar **Generador** en la barra, poner longitud `32`, desmarcar **Símbolos** y pulsar **Generar**.
- Debe verse: una contraseña de 32 letras y dígitos y «Entropía: 190,5 bits», que es 32 · log₂ 62. **Guardar como predeterminado** fija estas opciones para el botón **Generar** de las entradas.
- Estado: tres entradas, ordenadas por sitio (`banco`, `correo`, `foro`) y con «3 de 3 entradas».

**3. Buscar**
- Hacer: escribir `ban` en el cuadro de búsqueda, y después `eva`.
- Debe verse: «1 de 3 entradas», primero con `banco.ejemplo` y después con `foro.ejemplo`. Busca en sitio y usuario, y filtra mientras se escribe sin pedir nada al servidor. Borrar la búsqueda al terminar.

**4. Consultar y copiar**
- Hacer: pulsar **Ver** en la fila de `correo.ejemplo`. En el detalle, pulsar **Ver** para mostrar la contraseña, que es la misma que se generó en el paso 2. Pulsar **Copiar** y pegar en un editor de texto, por ejemplo el Bloc de notas.
- Debe verse: «Contraseña copiada. El portapapeles se vaciará en 20 s (no ocurre si cierras la pestaña antes).», y al pegar aparece la contraseña.
- Hacer: volver a la pestaña de `pvlt`, pulsar **Copiar** otra vez y **quedarse en esa pestaña** 20 s sin cambiar de ventana. Después, pegar de nuevo en el editor.
- Debe verse: «Portapapeles vaciado.» en la página, y al pegar no sale nada.
- En Brave: si aparece el aviso de permiso del portapapeles, pulsar **Permitir**. Mientras ese aviso esté abierto, el vaciado queda en espera, y se completa en cuanto se permite.
- Variante: copiar, cambiar a otra ventana y esperar más de 20 s. El navegador no deja vaciar el portapapeles si la pestaña no tiene el foco, así que la página muestra un aviso fijo: «El portapapeles todavía tiene la contraseña: el navegador no deja vaciarlo mientras esta pestaña no tiene el foco. Se vaciará al volver a ella.» Al volver a la pestaña y hacer clic en ella, el portapapeles se vacía.

**5. Modificar y eliminar**
- Hacer: en el detalle de `correo.ejemplo`, pulsar **Editar**, cambiar el usuario a `ana.editada` y pulsar **Guardar**.
- Debe verse: «Entrada guardada.», el usuario nuevo en la lista y la fecha de «Modificada» actualizada.
- Variante: pulsar **Editar**, borrar el sitio, escribir solo espacios y pulsar **Guardar**. Aparece «Dato inválido: sitio» y la lista no cambia. Pulsar **Cancelar**.
- Hacer: abrir el detalle de `foro.ejemplo` y pulsar **Eliminar**.
- Debe verse: la pregunta «¿Eliminar esta entrada? No se puede deshacer.». Al aceptar, «Entrada eliminada.».
- Estado: dos entradas, `banco.ejemplo` con `luis.demo` y `correo.ejemplo` con `ana.editada`.

**6. HTML en las notas se muestra como texto**
- Hacer: editar `correo.ejemplo` y escribir en las notas `<img src=x onerror=alert(1)>`. Guardar.
- Debe verse: el texto tal cual en el campo «Notas» del detalle, sin imagen rota ni ventana de alerta.

**7. Bloquear y contraseña incorrecta**
- Hacer: pulsar **Bloquear**.
- Debe verse: la pantalla «Desbloquear», sin ningún sitio, usuario ni contraseña a la vista.
- Hacer: escribir `demo-equivocada` y pulsar **Desbloquear**.
- Debe verse: «Contraseña incorrecta». La bóveda no se modifica ni se crea otra vacía.
- Comprobación en disco (opcional): en otra terminal, con `pvlt` en marcha, ejecutar este comando antes y después del intento fallido. Los resúmenes y la lista de archivos deben salir idénticos.

    ```
    docker compose exec app sh -c "sha256sum /data/* && ls /data"
    ```

- Hacer: escribir `demo-maestra-1` y pulsar **Desbloquear**.
- Debe verse: las dos entradas de antes.

**8. Bloqueo por inactividad**
- Hacer: pulsar **Ajustes**, escribir `30` en «Bloqueo por inactividad, en segundos (30 a 3600)» y pulsar **Guardar**. No tocar la página durante unos 35 s.
- Debe verse: «Ajustes guardados.» y la cuenta atrás de arriba pasa a «Bloqueo automático en 30 s». Al llegar a cero, la página vuelve a «Desbloquear» y muestra durante unos segundos «La bóveda se bloqueó por inactividad.».
- Hacer: desbloquear con `demo-maestra-1`, volver a **Ajustes**, poner `300` y **Guardar**, para que no se bloquee durante el resto de la demostración.

**9. Cambiar la contraseña maestra**
- Hacer: pulsar **Contraseña maestra**, escribir la actual (`demo-maestra-1`) y dos veces la nueva (`demo-maestra-2`), y pulsar **Cambiar**.
- Debe verse: «Contraseña maestra cambiada. El respaldo también usa la nueva.».
- Hacer: pulsar **Bloquear** e intentar desbloquear con `demo-maestra-1`.
- Debe verse: «Contraseña incorrecta». Con `demo-maestra-2` se abre con las dos entradas.

**10. Exportar e importar**
- Hacer: pulsar **Exportar**, dejar el nombre `exportacion.pvlt`, escribir dos veces `demo-exportar-1` y pulsar **Exportar**.
- Debe verse: «Exportadas 2 entradas a exportacion.pvlt.».
- Hacer: pulsar **Importar**, elegir `exportacion.pvlt` en la lista de archivos, escribir `demo-equivocada` y pulsar **Vista previa**.
- Debe verse: «Contraseña incorrecta», y no aparece ninguna vista previa.
- Hacer: escribir `demo-exportar-1` y pulsar **Vista previa**.
- Debe verse: «El archivo tiene 2 entradas, 2 en conflicto.» y una tabla con Sitio, Usuario, Conflicto («mismo identificador») y Decisión.
- Hacer: en la columna «Decisión», elegir **Conservar ambas** para `correo.ejemplo` y **Sustituir** para `banco.ejemplo`. Pulsar **Aplicar**.
- Debe verse: «Importación aplicada: 0 añadidas, 1 sustituidas, 1 duplicadas con identificador nuevo, 0 omitidas.».
- Estado: tres entradas, `banco.ejemplo` una vez y `correo.ejemplo` dos veces.

**11. Recuperación tras un archivo dañado**
- Hacer: detener `pvlt` con **Ctrl+C** en su terminal.
- Debe verse: «pvlt cerrado. La bóveda quedó bloqueada.».
- Hacer: dañar un bit de la bóveda y volver a arrancar:

    ```
    docker compose run --rm app python -m scripts.damage /data/boveda.pvlt
    docker compose up
    ```

- Debe verse: el primer comando responde «Se invirtió un bit del byte 200 de /data/boveda.pvlt.».
- Hacer: copiar el enlace nuevo que imprime la terminal y pegarlo en la misma pestaña de antes.
- Debe verse: la página se recarga sola y muestra «La bóveda está dañada, pero el respaldo está bien (generación N). Al restaurarlo el archivo actual se conserva aparte.» con el botón **Restaurar el respaldo**.
- Hacer: pulsar **Restaurar el respaldo** y aceptar la pregunta «¿Restaurar el respaldo? El archivo actual se conserva aparte para su análisis.».
- Debe verse: «Respaldo restaurado. El archivo anterior se guardó como boveda.pvlt.damaged-<fecha>.».
- Hacer: desbloquear con `demo-maestra-2`.
- Estado: dos entradas, `banco.ejemplo` y `correo.ejemplo` una vez. El respaldo es la versión previa al último guardado, así que la importación del paso 10 no aparece. Nada más se perdió.

**12. Comprobar los archivos en disco**
- Hacer: detener `pvlt` con **Ctrl+C** y listar los archivos del volumen:

    ```
    docker compose run --rm app ls -l /data
    ```

- Debe verse: `boveda.pvlt`, `boveda.pvlt.bak`, `boveda.pvlt.damaged-<fecha>`, `boveda.pvlt.lock` y `exportacion.pvlt`, todos con permisos `-rw-------` (solo el dueño puede leerlos) y ningún temporal `.tmp`.
- Hacer: buscar en todos esos archivos los datos que se escribieron durante la demostración:

    ```
    docker compose run --rm app sh -c 'for s in correo.ejemplo banco.ejemplo ana.editada luis.demo demo-maestra demo-exportar; do grep -rl $s /data || echo $s: sin coincidencias; done'
    ```

- Debe verse: «sin coincidencias» para los seis valores. Si alguno apareciera en claro, se imprimiría el nombre del archivo que lo contiene.

### Qué requisito demuestra cada paso

| Requisito del enunciado | Pasos de la interfaz web | Escenario automático |
|---|---|---|
| Crear, desbloquear y bloquear una bóveda | 0, 1, 7 | 1 |
| Agregar, buscar, consultar, modificar y eliminar | 2, 3, 4, 5 | 2 |
| Generador configurable y bloqueo por inactividad | 2, 8 | 2 |
| Cambio de contraseña maestra sin perder registros | 9 | 3 |
| Contraseña incorrecta sin crear ni sobrescribir nada | 7, 9 | 4 |
| Detectar modificaciones del archivo | 11 | 5 |
| Recuperación tras un fallo durante el guardado | 11 | 6 |
| Exportar e importar solo cifrado | 10, 12 | 7 |
| Sin copia legible en disco | 12 | 1 |
| Bóvedas de 1, 100 y 500 entradas | | 1 |

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

Las pruebas funcionales usan la configuración A de Argon2id (64 MiB) para ir más rápido.

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
| La configuración C falla o el sistema se queda sin memoria | Docker tiene menos de unos 2,5 GiB asignados. Aumentar la memoria en Docker Desktop o usar `--skip-c` al calibrar |
| En Brave, el portapapeles no se vacía a los 20 s, o aparece «quiere ver el texto y las imágenes copiados en el portapapeles» | Brave pide un permiso de portapapeles para que la página pueda vaciarlo sin un clic. Pulsar **Permitir**. Si ya se bloqueó, se cambia con el icono a la izquierda de la dirección, en los permisos del sitio. `pvlt` nunca lee el portapapeles |
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
| [`docs/informe/informe.pdf`](docs/informe/informe.pdf) | Informe final (12 páginas) |
| [`docs/diseno.md`](docs/diseno.md) | Especificación técnica: formato, protocolo, seguridad web, pruebas y experimentos |
| [`docs/entregable1/`](docs/entregable1/) | Entregable 1 (diseño y estado del arte) |

Todos los datos de prueba y de demostración son sintéticos.
