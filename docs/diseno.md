# Especificación técnica de `pvlt`

Este documento traduce el Entregable 1 (`docs/entregable1/Entregable1_Proyecto_final.pdf`) a una especificación implementable. Si algo aquí no coincide con el PDF, manda el PDF y la diferencia se corrige en este archivo. Los valores que el PDF no fija y que aquí se concretan están marcados como **(concreción)**. Si se cambian, basta con mantener este archivo coherente y anotarlo en `desviaciones.md` solo si contradice algo escrito en el PDF.

## 1. Escenario

- Un solo usuario, ejecución 100 % local, sin red ni sincronización.
- Bóveda de 1 a 500 entradas. Cada entrada tiene `site`, `username`, `password`, `notes`.
- Interfaz web local. `pvlt` arranca un servidor en la interfaz local y abre el navegador.
- Operaciones: crear, desbloquear, bloquear (botón, cierre, 5 minutos de inactividad), listar con búsqueda instantánea, ver, copiar, editar, eliminar, crear con generador, cambiar contraseña maestra, exportar, importar.
- En disco solo existen `boveda.pvlt`, `boveda.pvlt.bak` y, durante un guardado, `boveda.pvlt.tmp`. Todos cifrados con el mismo formato.

## 2. Modelo de adversario

| Id | Adversario | Capacidad |
|---|---|---|
| A1 | Lector fuera de línea | Copia el archivo y prueba contraseñas, incluso con hardware paralelo |
| A2 | Manipulador | Modifica cualquier byte, trunca o reemplaza el archivo |
| A3 | Fallo no malicioso | Interrumpe un guardado o corrompe bytes del disco |
| A4 | Usuario local sin privilegios | Lee argumentos de procesos, variables de entorno, archivos con permisos laxos, se conecta a puertos locales |
| A5 | Página web maliciosa | Intenta CSRF contra el servidor local, DNS rebinding o incrustar la app en un iframe |

Fuera del modelo: malware, keyloggers, extensiones maliciosas, volcados de memoria del servidor o del navegador con la bóveda abierta, contraseñas maestras muy débiles, observación física, guardado de la contraseña maestra por el gestor del navegador, retroceso a una copia antigua válida (solo se advierte).

## 3. Propiedades

| Id | Propiedad | Frente a | Mecanismo | Prueba |
|---|---|---|---|---|
| P1 | Confidencialidad | A1 | ChaCha20-Poly1305, relleno a 4 KiB | T3, T8 |
| P2 | Costo alto por intento | A1 | Argon2id, sal de 128 bits | E1 |
| P3 | Integridad del archivo completo | A2 | AEAD con cabecera como dato asociado | T4, T5 |
| P4 | Nonces únicos bajo cada clave | A3 | DEK nueva por guardado | T6 |
| P5 | Guardado atómico | A3 | Temporal, fsync, renombrado, respaldo | T7 |
| P6 | Ningún secreto en claro fuera de memoria | A4 | Sin logs, argumentos, URL ni temporales en claro, permisos 0600 | T9 |
| P7 | Parámetros acotados | A2 | Límites de m, t, p antes de derivar | T4 |
| P8 | Servidor usable solo por el usuario | A4, A5 | Token de arranque, cookie SameSite=Strict, CSRF, Host y Origin, CSP | T13 |

Limitación declarada: alterar la sal o `W` produce el mensaje "contraseña incorrecta", porque es indistinguible sin la clave.

## 4. Protocolo criptográfico

### 4.1 Jerarquía de claves

```
KEK = Argon2id v1.3 (password_utf8, salt, m_cost, t_cost, parallelism, length=32)
W   = ChaCha20Poly1305(KEK).encrypt(N_w, DEK, b"PVLT/v1/wrap" || Hdr)          # 32 + 16 = 48 bytes
C   = ChaCha20Poly1305(DEK).encrypt(N_d, pad(P), b"PVLT/v1/data" || Hdr || W)  # len(pad(P)) + 16
```

- Las etiquetas de dominio son bytes ASCII exactos, sin terminador: `PVLT/v1/wrap` y `PVLT/v1/data` (12 bytes cada una).
- `Hdr` son los 59 bytes de la cabecera tal como se escriben en disco, con la `generation` ya incrementada.
- La contraseña se codifica en UTF-8 sin normalización **(concreción)**. Si se decide normalizar (NFC), se anota.
- `N_w`, `N_d`: 12 bytes de `secrets.token_bytes`. `DEK`: 32 bytes de `secrets.token_bytes`.

### 4.2 Crear

1. Validar la contraseña (pedirla dos veces en la interfaz).
2. Generar `salt` (16 B) y `vault_id` (16 B). `generation = 1`.
3. Derivar la KEK con la configuración vigente.
4. Guardar (4.3) con la lista de entradas vacía.

Concreciones **(concreción)**: la contraseña maestra y la de exportación deben tener entre 8 y 1024 caracteres al fijarse. `create` se niega a sobrescribir cualquier archivo existente.

### 4.3 Guardar

1. `generation += 1` (salvo al crear).
2. Nueva DEK, nuevos `N_w` y `N_d`.
3. Construir Hdr, calcular W y C, añadir `len_C` y el `digest` final.
4. Escribir con el procedimiento atómico (sección 7).
5. No se ejecuta Argon2id: la KEK sigue en memoria durante la sesión.

### 4.4 Desbloquear: cuatro comprobaciones en orden

| Orden | Comprobación | Error y mensaje |
|---|---|---|
| 1 | Longitud mínima, `magic`, `format_version` soportada, `purpose` esperado, ids de KDF y AEAD conocidos, `kdf_version == 0x13`, parámetros dentro de límites, `len_C` coherente con el tamaño total | `FormatError`: "Formato no reconocido" |
| 2 | SHA-256 de todo lo anterior coincide con `digest` | `CorruptedFileError`: "Archivo dañado", se ofrece restaurar `.bak` |
| 3 | Derivar KEK y abrir `W` | `WrongPasswordError`: "Contraseña incorrecta" |
| 4 | Abrir `C` con la DEK, quitar relleno, parsear JSON y validar esquema | `TamperedContentError`: "Contenido manipulado" |

- El resumen SHA-256 solo detecta errores accidentales. La aceptación depende de 3 y 4.
- Ningún fallo escribe en disco ni crea bóveda.
- Comparar el digest con `hmac.compare_digest`.

### 4.5 Cambiar contraseña maestra

Verificar la actual (derivar con la sal vigente y abrir W), nueva sal, nueva KEK, guardar normalmente y **regenerar también el `.bak`** con la nueva contraseña. El contenido no cambia.

### 4.6 Exportar e importar

- Exportación: mismo formato, `purpose = 0x02`, contraseña de exportación propia (sal y KEK propias), `vault_id` nuevo **(concreción)**.
- Importación: mismas cuatro comprobaciones exigiendo `purpose = 0x02`, validar cada entrada, vista previa. Conflicto si coincide el UUID o el par `(site, username)`: el usuario elige omitir, sustituir o conservar ambos (conservar ambos asigna UUID nuevo).

Concreciones de la importación **(concreción)**:

- Un conflicto sin decisión del usuario se omite, que es la opción que no destruye nada.
- Sustituir conserva el UUID y la fecha de creación de la entrada local y toma los datos de la importada.
- Los conflictos se recalculan al aplicar, por si la bóveda cambió después de la vista previa o dos entradas importadas chocan entre sí.
- Toda la importación se escribe con un solo guardado. Si el resultado supera las 500 entradas no se importa nada.
- La exportación usa los mismos parámetros de Argon2id que la bóveda y nunca deja respaldo.

### 4.7 Unicidad de nonces

Bajo cada DEK hay un único cifrado. Bajo la KEK, nonce aleatorio de 96 bits por guardado, probabilidad de colisión a lo sumo q²/2^97, cota conservadora de 2^32 cifrados por clave tomada de SP 800-38D. La KEK cambia con cada cambio de contraseña.

### 4.8 Generador

- Solo `secrets`. Longitud 8 a 128, por defecto 20. Clases: minúsculas, mayúsculas, dígitos, símbolos.
- Muestreo por rechazo: generar candidata uniforme sobre la unión de clases elegidas, descartar si falta alguna clase, repetir.
- Mostrar entropía = longitud × log2(tamaño del alfabeto).
- Conjunto de símbolos **(concreción)**: `!#$%&()*+,-./:;<=>?@[]^_{|}~` (sin comillas ni barra invertida para evitar problemas al pegar).

Nota **(concreción)**: la entropía mostrada es una cota superior. Descartar las candidatas a las que les falta una clase quita una fracción de bit (unos 0,15 bits con la configuración por defecto). Por la misma razón, en contraseñas cortas las clases pequeñas aparecen algo más de lo que les correspondería por tamaño, aunque dentro de cada clase todos los caracteres siguen siendo equiprobables. T11 comprueba la uniformidad dentro de cada clase y, con longitud 128, sobre el alfabeto completo.

### 4.9 Bloqueo y memoria

- Bloqueo por botón, cierre del programa o 5 minutos de inactividad (configurable).
- La KEK se guarda en un `bytearray` propio y se sobrescribe con ceros al bloquear (usar `derive_into` si existe). Se eliminan referencias al contenido. Es esfuerzo razonable, no garantía.

Concreciones **(concreción)**:

- Cada operación comprueba primero la inactividad y, si no venció, cuenta como actividad. Consultar si la bóveda está bloqueada no cuenta como actividad.
- El contenido descifrado vive en cadenas inmutables de Python, que no pueden sobrescribirse. Al bloquear se sobrescribe la KEK y se sueltan las referencias al contenido.
- Todo cambio se escribe en disco antes de hacerse visible en memoria. Si el guardado falla, la sesión y el archivo quedan como estaban.
- Al cambiar la contraseña maestra hay una ventana breve, entre el guardado y la reescritura del respaldo, en la que el `.bak` todavía abre con la contraseña anterior.

## 5. Formato binario v1

Enteros sin signo big-endian. Desplazamientos en bytes.

| Desde | Hasta | Campo | Tamaño | Valor o significado |
|---|---|---|---|---|
| 0 | 4 | `magic` | 4 | `b"PVLT"` |
| 4 | 6 | `format_version` | 2 | `1` |
| 6 | 7 | `purpose` | 1 | `0x01` bóveda, `0x02` exportación |
| 7 | 8 | `kdf_id` | 1 | `0x01` Argon2id |
| 8 | 9 | `kdf_version` | 1 | `0x13` (Argon2 v1.3) |
| 9 | 13 | `m_cost` | 4 | memoria en KiB |
| 13 | 17 | `t_cost` | 4 | pasadas |
| 17 | 18 | `parallelism` | 1 | carriles |
| 18 | 34 | `salt` | 16 | aleatoria |
| 34 | 35 | `aead_id` | 1 | `0x01` ChaCha20-Poly1305 |
| 35 | 51 | `vault_id` | 16 | aleatorio |
| 51 | 59 | `generation` | 8 | contador de guardados |
| 59 | 71 | `nonce_w` | 12 | |
| 71 | 119 | `W` | 48 | DEK cifrada y etiqueta |
| 119 | 131 | `nonce_d` | 12 | |
| 131 | 135 | `len_C` | 4 | longitud de C |
| 135 | 135+len_C | `C` | len_C | contenido cifrado y etiqueta |
| 135+len_C | +32 | `digest` | 32 | SHA-256 de los bytes [0, 135+len_C) |

- `Hdr` = bytes [0, 59).
- El tamaño total debe ser exactamente `135 + len_C + 32`. Cualquier byte sobrante o faltante es `FormatError`.
- `len_C` debe ser `≥ 4096 + 16` y `(len_C − 16) % 4096 == 0`.

- `len_C` no puede superar `16 + 4096 × 4096` bytes, es decir 16 MiB de contenido rellenado **(concreción)**. Un archivo mayor se rechaza como `FormatError` sin leerlo completo. Con 500 entradas el contenido real queda muy por debajo.
- `generation` debe ser al menos 1 **(concreción)**. El valor 0 no puede producirse al guardar y se rechaza como `FormatError`.
- El resumen SHA-256 se calcula con `cryptography` (`hashes.SHA256`), igual que el resto de operaciones.

Límites al abrir: `m_cost ≤ 4 GiB` (4 194 304 KiB), `1 ≤ t_cost ≤ 16`, `1 ≤ parallelism ≤ 16`, y `m_cost ≥ 8 × parallelism` (mínimo de Argon2). Al crear se exige `m_cost ≥ 64 MiB` (65 536 KiB).

### 5.1 Contenido P

JSON UTF-8 canónico: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.

```json
{
  "schema": 1,
  "entries": [
    {
      "id": "uuid4 en minúsculas",
      "site": "...",
      "username": "...",
      "password": "...",
      "notes": "...",
      "created": "2026-11-15T21:00:00Z",
      "modified": "2026-11-15T21:00:00Z"
    }
  ],
  "settings": {
    "autolock_seconds": 300,
    "generator": {"length": 20, "lower": true, "upper": true, "digits": true, "symbols": true}
  }
}
```

Relleno: `pad(P) = P || 0x80 || 0x00 * k`, con k mínimo tal que la longitud sea múltiplo de 4096. Al quitarlo, buscar el último `0x80` y exigir que todo lo posterior sea cero. Si no, `TamperedContentError`.

Concreciones del contenido **(concreción)**:

- Límites por campo, en caracteres: `site` de 1 a 256, `username` de 0 a 256, `password` de 1 a 1024 y `notes` de 0 a 8192. Ningún campo admite el carácter nulo.
- `autolock_seconds` entre 30 y 3600. `generator.length` entre 8 y 128 y al menos una clase activa.
- Al abrir solo se acepta la codificación canónica: tras parsear, el contenido se vuelve a serializar y debe coincidir byte a byte con lo descifrado. También se rechazan claves duplicadas, claves desconocidas, tipos incorrectos, identificadores repetidos y más de 500 entradas. Todo ello es `TamperedContentError`.
- El relleno debe ser mínimo: más de 4095 ceros tras el `0x80` se rechaza.

Versionado: `format_version` (estructura binaria) y `schema` (JSON) son independientes. Versiones desconocidas se rechazan. Migración futura: abrir con el lector anterior y guardar con el nuevo.

## 6. Configuraciones de Argon2id

| Config | Memoria | Pasadas | Carriles | Uso |
|---|---|---|---|---|
| A | 64 MiB | 3 | 4 | Pruebas funcionales. Segunda recomendación de RFC 9106 |
| B | 256 MiB | 3 | 4 | Por defecto propuesta |
| C | 2 GiB | 1 | 4 | Primera recomendación de RFC 9106. Si no cabe, 1 GiB y 2 pasadas |

La configuración final es la de mayor memoria con desbloqueo ≤ 1 s en el equipo de referencia (E1). E1 también comprueba si los carriles se procesan en paralelo.

Resultado de E1 **(concreción)**: la configuración final es **B**, con un desbloqueo de 0,422 s (mediana de 20) frente a 1,908 s de C en el equipo de referencia (Intel Core i5-10300H, Docker sobre WSL2). Coincide con el valor por defecto propuesto, así que `CONFIG_B` sigue siendo el de `Vault.create`. Con 256 MiB y 3 pasadas, pasar de 1 a 4 carriles baja el tiempo de pared de 0,840 s a 0,414 s con un tiempo de CPU parecido, así que los carriles sí se procesan en paralelo.

## 7. Persistencia y guardado atómico

1. Adquirir el archivo de bloqueo (`boveda.pvlt.lock`) al iniciar. Si ya existe un proceso vivo, negarse a abrir.
2. Serializar el archivo completo en memoria.
3. Escribir en `boveda.pvlt.tmp` del mismo directorio con permisos 0600 (`os.open` con `O_CREAT|O_EXCL|O_WRONLY`, modo `0o600`), `flush` y `os.fsync`.
4. Releer el temporal y verificar estructura y digest.
5. Copiar la versión vigente a `boveda.pvlt.bak` con el mismo procedimiento (temporal propio y `os.replace`).
6. `os.replace(tmp, boveda.pvlt)`.
7. `fsync` del directorio (en POSIX).

Al iniciar: eliminar temporales sobrantes. Si la bóveda falla las comprobaciones 1 o 2 y el respaldo las supera, ofrecer restaurarlo sin sobrescribir el dañado (renombrarlo para análisis). Si el respaldo tiene `generation` mayor, advertir posible retroceso.

Concreciones de la implementación **(concreción)**:

- El archivo de bloqueo está vacío y permanece en disco entre ejecuciones. Lo que impide la segunda apertura es un bloqueo del núcleo sobre ese archivo (`flock` en POSIX, `msvcrt.locking` en Windows), que se libera solo cuando el proceso termina. Así una caída nunca deja la bóveda bloqueada y no hace falta guardar ni comprobar un PID.
- En el paso 5 la versión vigente solo se copia al respaldo si supera las comprobaciones 1 y 2. Una bóveda dañada no reemplaza al último respaldo bueno.
- Al restaurar, el archivo dañado se renombra a `boveda.pvlt.damaged-<fecha UTC>` y el respaldo se conserva.
- Un error real de escritura (por ejemplo disco lleno) elimina el temporal parcial y deja la bóveda como estaba.

Puntos de inyección de fallos: cada paso debe poder interrumpirse en pruebas (T7). Diseñar `storage/` con un hook o parámetro que permita simular la caída tras cada paso.

## 8. Capa web

- Al iniciar: token de 256 bits, URL `http://127.0.0.1:<puerto>/#t=<token>`. El token viaja en el fragmento.
- La página lee el fragmento, lo canjea **una sola vez** por una cookie de sesión `HttpOnly`, `SameSite=Strict`, y limpia el fragmento con `history.replaceState`.
- Toda petición que cambia estado exige token CSRF (cabecera propia, por ejemplo `X-CSRF-Token`).
- Rechazar `Host` distinto de `127.0.0.1:<puerto>` o `localhost:<puerto>`, y `Origin` ajeno. Sin CORS.
- Cabeceras: `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- Renderizar datos de usuario solo con `textContent`. Nunca `innerHTML` con datos de la bóveda.
- La lista no incluye contraseñas. Se piden una a una al pulsar "Ver" o "Copiar".
- Campo de contraseña maestra con `autocomplete="new-password"`. La interfaz recomienda no guardarla en el navegador.
- Portapapeles: `navigator.clipboard.writeText(valor)` y a los 20 s `writeText("")` sin leer antes. Se advierte que no ocurre si se cierra la pestaña.
- Log de acceso de uvicorn desactivado.
- Fuera de Docker: escucha en `127.0.0.1` con puerto aleatorio y abre el navegador.
- En Docker: escucha en `0.0.0.0:8765` dentro del contenedor y se publica con `-p 127.0.0.1:8765:8765`. La URL con el token se imprime en la terminal. En ese caso `Host` aceptado es `127.0.0.1:8765` y `localhost:8765`.

Concreciones de la capa web **(concreción)**:

- El token de arranque, la cookie de sesión y el token CSRF son de 256 bits (`secrets.token_urlsafe(32)`) y se comparan con `hmac.compare_digest`. El canje es `POST /api/session` con el token en el cuerpo. Tras el primer canje correcto el token de arranque se olvida. Un token incorrecto no lo consume.
- La cookie es `pvlt_session`, `HttpOnly`, `SameSite=Strict`, `Path=/` y de sesión (sin caducidad). No lleva `Secure` porque el servidor es HTTP sobre la interfaz local.
- El token CSRF se exige en **todas** las peticiones a `/api/` salvo el canje, no solo en las que cambian estado, y viaja en la cabecera `X-CSRF-Token`. La página lo guarda en `sessionStorage`, que depende del puerto, para sobrevivir a una recarga. No existe ninguna ruta que lo vuelva a entregar a partir de la cookie, porque las cookies no distinguen puertos y otro servidor local podría recibirla.
- Orden de las comprobaciones: `Host` (403), `Origin` (403), cookie (401) y CSRF (403). `Origin` ajeno se rechaza siempre, y su ausencia solo se admite en GET, HEAD y OPTIONS.
- Cabeceras adicionales a las de arriba: `X-Frame-Options: DENY` y `Cross-Origin-Resource-Policy: same-origin`. La documentación automática de FastAPI (`/docs`, `/redoc`, `/openapi.json`) está desactivada.
- Ningún dato del usuario va en la URL. La búsqueda se hace en la página sobre la lista ya descargada. Los identificadores de entrada, que son UUID aleatorios, son lo único que aparece en una ruta.
- Las respuestas de error son `{"error", "message", "field"}` con mensajes fijos en español. Se sustituye el manejador de validación de FastAPI, que devolvería los valores enviados, y cualquier excepción se captura antes de llegar al registro de uvicorn. Un error desconocido solo muestra el nombre de su clase.
- La sesión se bloquea por botón, por inactividad y al cerrar el servidor (Ctrl+C o SIGTERM). Un hilo comprueba la inactividad cada 5 s para borrar la KEK a tiempo aunque no llegue ninguna petición. Consultar el estado no cuenta como actividad. Recargar la página no bloquea la bóveda.
- Exportar e importar usan un nombre de archivo, no una ruta: letras, dígitos, `.`, `_` y `-`, terminado en `.pvlt`, en la carpeta de la bóveda y distinto de la bóveda. Así no hay que transferir archivos por el navegador ni escribir temporales fuera del procedimiento atómico.
- Los formularios usan `method="post"` para que un envío anterior a la carga del script nunca ponga una contraseña en la URL. La CSP impide cualquier código o estilo en línea, así que la página no tiene ninguno.
- Fuera de Docker el servidor abre el navegador con `webbrowser.open(url)`. Mientras el sistema lanza el navegador, la URL con el token puede verse en los argumentos de ese proceso. Como el token solo sirve una vez, si otro proceso lo canjeara antes la página del usuario mostraría que el enlace ya se usó (limitación declarada).

## 9. Pruebas

| Id | Caso | Resultado esperado |
|---|---|---|
| T1 | Crear, cerrar y reabrir con 1, 100 y 500 entradas. Agregar, buscar, consultar, modificar, eliminar. Inactividad simulada | Contenido idéntico tras reabrir y bloqueo al vencer el tiempo |
| T2 | Cambiar la contraseña maestra | La nueva abre bóveda y respaldo, la antigua no |
| T3 | Buscar los datos sintéticos en los bytes del archivo | Ninguno aparece en claro |
| T4 | Contraseña incorrecta, archivo truncado, versión desconocida, parámetros fuera de límite | Mensaje correcto, archivo intacto, ninguna bóveda vacía |
| T5 | Alterar un bit en cada campo de la cabecera, en los nonces, en W, en C y en cada etiqueta. Intercambiar C entre bóvedas | Rechazo en todos los casos |
| T6 | 10 000 guardados consecutivos | Ninguna DEK ni nonce repetido |
| T7 | Interrumpir el guardado tras cada paso. Dañar bytes sin recalcular el resumen | Se abre una versión íntegra o se restaura el respaldo |
| T8 | Exportar e importar con y sin la contraseña de exportación | Sin texto claro, solo importa con su contraseña |
| T9 | Revisar logs, temporales, argumentos y URL | La contraseña sintética no aparece |
| T10 | Vectores de RFC 8439 y RFC 9106 | Salidas esperadas |
| T11 | 10 000 contraseñas con distintas combinaciones de clases | Longitud correcta, todas las clases, sin sesgo significativo (χ²) |
| T12 | Copiar en Playwright con permisos de portapapeles y esperar el plazo | Portapapeles vacío |
| T13 | Peticiones sin cookie, sin CSRF, con Host u Origin ajenos, notas con HTML, carga en iframe | 401 o 403, texto escapado, carga bloqueada |

- T5 se parametriza sobre la tabla de campos de la sección 5 (una sola fuente de verdad para los desplazamientos).
- Pruebas funcionales con configuración A.
- Para alterar "un bit en cada etiqueta": las etiquetas son los últimos 16 bytes de W y de C.
- En T4 y T5 verificar además que el archivo queda byte a byte idéntico y que no aparece `boveda.pvlt.tmp`.

## 10. Experimentos

- **E1**: tiempo de desbloqueo (mediana de 20) y pico de memoria residente del proceso (no `tracemalloc`) para A, B y C. Comprobar uso de varios núcleos. Estimar costo de diccionario t × |D|.
- **E2**: abrir y guardar sin Argon2id con 1, 100 y 500 entradas (mediana de 50).
- **E3**: tamaño del archivo frente al JSON sin cifrar.
- Reportar CPU, RAM y SO. Guardar resultados en CSV dentro de `bench/results/` y generar gráficas para el informe.

Concreciones del método **(concreción)**:

- E1 mide `Vault.unlock` completo (comprobaciones 1 a 4). Cada configuración corre en un proceso hijo nuevo, y el pico es su `ru_maxrss`. También se anota la memoria residente antes de crear la bóveda, para separar lo que ocupa el intérprete.
- El uso de varios núcleos se mide con el cociente entre `time.process_time` (CPU de todos los hilos) y el tiempo de pared, sobre B con 1, 2 y 4 carriles (mediana de 10).
- El costo de diccionario se da como t × |D| con t la mediana de pared, y también en horas de núcleo con el tiempo de CPU, para cuatro tamaños de |D|.
- E2 usa una KEK aleatoria y separa sellar, escritura atómica, lectura con comprobaciones 1 y 2, y comprobaciones 3 y 4 con el análisis del JSON. Cada guardado escribe la generación siguiente, igual que `Vault`.
- E3 cubre de 0 a 500 entradas (el máximo) y separa el JSON, el relleno y la parte fija.
- Las entradas son sintéticas: sitio y usuario cortos, contraseña generada de 20 caracteres y una nota breve.
