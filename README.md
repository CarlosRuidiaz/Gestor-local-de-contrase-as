# pvlt · Gestor local de contraseñas con Argon2id y AEAD

Proyecto final de Criptografía Aplicada (Universidad del Norte), Proyecto 2 del banco de proyectos. Docente: Ricardo Luis Villanueva-Polanco.

Equipo: Carlos Ruidiaz, Juan Bolivar, Juan Rojas y Claudia Elias.

`pvlt` es un gestor de contraseñas de un solo usuario que funciona por completo en el equipo, sin red ni sincronización. La bóveda guarda entre 1 y 500 credenciales (sitio, usuario, contraseña y notas) cifradas bajo una contraseña maestra. Se usa desde una interfaz web local o desde un CLI mínimo.

## Qué hace

- Crear, desbloquear y bloquear la bóveda. El bloqueo ocurre con un botón, al cerrar el programa o tras 5 minutos de inactividad (configurable entre 30 s y 1 h).
- Agregar, buscar, consultar, copiar, modificar y eliminar credenciales.
- Generador de contraseñas configurable (longitud de 8 a 128 y cuatro clases de caracteres) que muestra la entropía.
- Cambiar la contraseña maestra sin perder registros.
- Exportar e importar solo en formato cifrado, con contraseña propia y vista previa de conflictos.
- Guardado atómico con respaldo y recuperación tras un fallo o un archivo dañado.

## Criptografía en una línea

La contraseña maestra deriva una clave de envoltura (KEK) con **Argon2id v1.3** (256 MiB, 3 pasadas, 4 carriles, sal de 128 bits). La KEK cifra con **ChaCha20-Poly1305** una clave de datos (DEK) aleatoria que se renueva en cada guardado y cifra el contenido. La cabecera completa va como dato asociado con etiquetas de dominio separadas. Todo pasa por la biblioteca `cryptography` (pyca), sin primitivas propias.

```
KEK = Argon2id(contraseña, sal, m, t, p)
W   = ChaCha20-Poly1305(KEK).cifrar(N_w, DEK,     "PVLT/v1/wrap" || Hdr)
C   = ChaCha20-Poly1305(DEK).cifrar(N_d, pad(P),  "PVLT/v1/data" || Hdr || W)
```

El formato binario, el protocolo y el modelo de adversario están en [`docs/diseno.md`](docs/diseno.md). El análisis completo está en el informe final ([`docs/informe/`](docs/informe/)).

## Requisitos

- **Docker** con Docker Compose (Docker Desktop en Windows o macOS). Es la plataforma de referencia: Linux con Python 3.12 dentro de un contenedor.
- Unos 2 GB libres para la imagen, que incluye Chromium sin interfaz para las pruebas de navegador.
- Para medir la configuración C de Argon2id (2 GiB) el contenedor necesita algo más de 2 GiB de memoria libre. El uso normal no lo requiere.

Sin Docker también funciona con Python 3.12 o superior (ver [Instalación local](#instalación-local-sin-docker)).

## Instalación desde cero con Docker

```
git clone https://github.com/CarlosRuidiaz/Gestor-local-de-contrase-as.git
cd Gestor-local-de-contrase-as
docker compose build
```

La imagen instala las dependencias de `requirements.txt` con `pip install --require-hashes`, así que cualquier paquete cuyo hash no coincida se rechaza. Las versiones están fijadas con `pip-tools` a partir de `requirements.in`.

Después de cambiar el código hay que volver a ejecutar `docker compose build`, porque el código se copia a la imagen y no se monta.

## Uso de la interfaz web

```
docker compose up
```

1. La terminal imprime una URL de la forma `http://127.0.0.1:8765/#t=...`. Se abre en el navegador del equipo.
2. El enlace sirve **una sola vez**. Al cargarse se canjea por una cookie de sesión y desaparece de la barra de direcciones. Recargar la página conserva la sesión, pero otra pestaña u otro navegador necesitan reiniciar `pvlt`.
3. La primera vez se crea la bóveda eligiendo la contraseña maestra (de 8 a 1024 caracteres). Conviene rechazar el ofrecimiento del navegador de guardarla.
4. Ctrl+C en la terminal cierra el servidor y bloquea la bóveda.

La bóveda vive en el volumen de Docker `pvlt-data`, en `/data/boveda.pvlt`. El puerto solo se publica en la interfaz local del equipo (`127.0.0.1:8765`), así que ningún otro equipo puede conectarse.

Para usar otra bóveda:

```
docker compose run --rm --service-ports app python -m pvlt.web --vault /data/otra.pvlt
```

`docker compose run` necesita `--service-ports` para publicar el puerto.

Exportar e importar trabajan con nombres de archivo `.pvlt` dentro de la carpeta de la bóveda. Para sacar una exportación del volumen se usa `docker compose cp app:/data/exportacion.pvlt .` con el contenedor en marcha.

## Uso del CLI

El CLI es un punto de entrada mínimo para pruebas y experimentos. Las contraseñas se piden con `getpass` y el resto de datos sensibles (sitio, usuario, notas, búsqueda) por teclado, nunca como argumento.

```
docker compose run --rm app python -m pvlt.cli create --config A
docker compose run --rm app python -m pvlt.cli add --generate
docker compose run --rm app python -m pvlt.cli list --search
docker compose run --rm app python -m pvlt.cli --help
```

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

La ruta se elige con `--vault RUTA`. Sin ella se usa `$PVLT_VAULT_DIR/boveda.pvlt` (en el contenedor, `/data`) o `./boveda.pvlt`. Los códigos de salida están documentados en `pvlt/cli.py`.

## Instalación local (sin Docker)

Con Python 3.12 o superior:

```
python -m venv .venv
.venv\Scripts\activate            # en Linux o macOS: source .venv/bin/activate
pip install --require-hashes -r requirements.txt
pip install --no-deps -e .
```

Quedan disponibles dos comandos:

- `pvlt` arranca la interfaz web en `127.0.0.1` con un puerto aleatorio y abre el navegador. Acepta `--vault RUTA`, `--port N` y `--no-browser`.
- `pvlt-cli` es el CLI descrito arriba.

Fuera de Docker no se garantiza la semántica POSIX de `fsync` y `os.replace` ni los permisos 0600. Windows y macOS son compatibles, pero las mediciones y las pruebas de fallo de referencia se hicieron en el contenedor.

## Pruebas

```
docker compose run --rm app pytest
docker compose run --rm app mypy
docker compose run --rm app ruff check .
docker compose run --rm app ruff format --check .
```

La suite completa tarda unos tres minutos y cubre las pruebas T1 a T13 del diseño, los scripts de experimentos y el guion de demostración. Las pruebas funcionales usan la configuración A de Argon2id (64 MiB) para ir más rápido.

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

Marcas útiles para iterar: `pytest -m "not slow"` excluye las pruebas largas y `pytest -m "not browser"` las de navegador.

## Guion de demostración

### Demostración automática

```
docker compose run --rm app python -m scripts.demo
```

Recorre en una carpeta temporal, con datos sintéticos y sin mostrar ninguna contraseña, cada escenario que exige el enunciado. Cada paso termina en una comprobación marcada como `[OK]` o `[FALLO]`:

1. Crear, cerrar y reabrir bóvedas con 1, 100 y 500 entradas, y comprobar que ningún dato aparece en claro en el archivo.
2. Agregar con el generador, buscar, consultar, modificar y eliminar, y el bloqueo por inactividad con un reloj simulado.
3. Cambiar la contraseña maestra: la nueva abre la bóveda y el respaldo, la anterior ya no.
4. Rechazar una contraseña incorrecta sin tocar ningún archivo ni crear una bóveda vacía. También un archivo truncado, una versión desconocida y una memoria de Argon2id fuera de límite.
5. Detectar un bit alterado en la sal, el identificador, la generación, los nonces, W, C y sus etiquetas, con el resumen recalculado como haría un atacante. También un byte dañado sin recalcular el resumen y el contenido de otra bóveda.
6. Simular una caída tras cada paso del guardado atómico y comprobar que siempre abre una versión íntegra. Después, dañar la bóveda y restaurar el respaldo.
7. Exportar y comprobar que no hay texto claro, rechazar la importación con la contraseña equivocada y aplicar una importación con un conflicto.

Tarda alrededor de un minuto, casi todo en los 500 guardados del primer escenario. `--config B` usa la configuración final de Argon2id en lugar de la A, y `--keep` conserva los archivos generados.

### Demostración en la interfaz web

1. `docker compose up` y abrir la URL impresa.
2. **Crear** la bóveda con una contraseña maestra sintética, por ejemplo `demo-maestra-1`.
3. **Nueva entrada** con el generador: elegir la longitud y las clases, ver la entropía y guardar. Agregar dos o tres entradas más.
4. **Buscar** escribiendo en el cuadro de búsqueda. La lista se filtra sin pedir nada al servidor.
5. **Ver**, **Copiar** (el portapapeles se vacía a los 20 s), **Editar** y **Eliminar** sobre una entrada.
6. Escribir en las notas de una entrada `<img src=x onerror=alert(1)>` y comprobar que se muestra como texto.
7. **Bloquear** y desbloquear con una contraseña equivocada: aparece «Contraseña incorrecta» y la bóveda no cambia. Desbloquear con la correcta.
8. **Ajustes**: bajar el bloqueo por inactividad a 30 s, esperar y comprobar que la página vuelve a pedir la contraseña.
9. **Cambiar la contraseña maestra**, bloquear y abrir con la nueva.
10. **Exportar** a `exportacion.pvlt` con una contraseña de exportación. **Importar** ese mismo archivo: la vista previa marca todas las entradas como conflicto, y se puede elegir omitir, sustituir o conservar ambas.
11. **Recuperación del respaldo**: detener el servidor con Ctrl+C, dañar un bit de la bóveda y volver a arrancar.

    ```
    docker compose run --rm app python -m scripts.damage /data/boveda.pvlt
    docker compose up
    ```

    La página informa que la bóveda está dañada y ofrece restaurar el respaldo. Al confirmar, el archivo dañado se conserva como `boveda.pvlt.damaged-<fecha>` y la bóveda abre con la versión anterior.

## Experimentos

```
docker compose run --rm -e PVLT_BENCH_HOST="descripción del equipo" -v "${PWD}/bench/results:/app/bench/results" app python -m bench.run_all
```

- **E1**: tiempo de desbloqueo (mediana de 20) y pico de memoria residente para las configuraciones A, B y C de Argon2id, paralelismo de los carriles y costo de un ataque de diccionario.
- **E2**: abrir y guardar sin Argon2id con 1, 100 y 500 entradas (mediana de 50).
- **E3**: tamaño del archivo frente al JSON sin cifrar.

Tarda unos 5 minutos. Los CSV de resumen y las gráficas quedan en [`bench/results/`](bench/results/), junto con `sistema.csv`, que describe el equipo. `--quick` lo recorre con pocas repeticiones, solo para comprobar que funciona. Mientras se mide conviene no ejecutar nada pesado en el equipo.

Resultados en el equipo de referencia (Intel Core i5-10300H, Docker sobre WSL2):

| Configuración | Memoria | Pasadas | Desbloqueo (mediana) | Pico de memoria |
|---|---|---|---|---|
| A | 64 MiB | 3 | 0,109 s | 98 MiB |
| **B (final)** | 256 MiB | 3 | 0,422 s | 290 MiB |
| C | 2 GiB | 1 | 1,908 s | 2 082 MiB |

La configuración final es B, la de mayor memoria que desbloquea en 1 s o menos en el equipo de referencia.

## Estructura del repositorio

```
pvlt/
  crypto/     Argon2id, ChaCha20-Poly1305, aleatoriedad y borrado. Funciones puras, sin disco
  storage/    formato binario v1, límites, guardado atómico, respaldo y lock. Nunca recibe claves
  vault/      sesión, entradas, operaciones y generador. Única capa que sostiene la KEK
  web/        FastAPI, seguridad HTTP y frontend en HTML, CSS y JS propios
  cli.py      CLI mínimo
  params.py   constantes públicas del protocolo y configuraciones de Argon2id
tests/        pruebas por capa (crypto, storage, vault, web, bench, CLI y demostración)
bench/        experimentos E1, E2 y E3 y sus resultados en bench/results/
scripts/      guion de demostración, daño controlado de un archivo y verificación del entorno
docs/         diseño, desviaciones, requisitos, estado e informe final
```

Las dependencias van en un solo sentido: `web → vault → (crypto, storage)`. Una prueba de humo lo verifica.

## Límites de seguridad

`pvlt` protege la bóveda frente a quien copia o modifica el archivo cuando la bóveda está cerrada, frente a fallos al guardar y frente a otros usuarios locales y páginas web que intenten usar el servidor. No protege frente a malware, keyloggers, extensiones maliciosas ni volcados de memoria con la bóveda abierta, ni frente a una contraseña maestra débil. El retroceso a una copia antigua válida solo se advierte. Las limitaciones completas están en el informe.

## Documentación

| Archivo | Contenido |
|---|---|
| [`docs/informe/`](docs/informe/) | Informe final (fuente LaTeX y PDF) |
| [`docs/diseno.md`](docs/diseno.md) | Especificación técnica: formato, protocolo, seguridad web, pruebas y experimentos |
| [`docs/desviaciones.md`](docs/desviaciones.md) | Cambios respecto al Entregable 1 |
| [`docs/requisitos_entregable2.md`](docs/requisitos_entregable2.md) | Lo que exige el enunciado |
| [`docs/entregable1/`](docs/entregable1/) | Entregable 1 (diseño y estado del arte) |

Todos los datos de prueba y de demostración son sintéticos.
