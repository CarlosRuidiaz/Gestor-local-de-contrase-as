# Guía de desarrollo de `pvlt`

Proyecto 2 del curso de Criptografía Aplicada (Universidad del Norte): gestor local de contraseñas con Argon2id y AEAD.
Equipo: Carlos Ruidiaz, Juan Bolivar, Juan Rojas, Claudia Elias.

Esta guía contiene lo que no cambia de una sesión de trabajo a otra: reglas, convenciones y flujo. Lo que sí cambia (qué está hecho, qué sigue, qué quedó a medias) vive en [`estado.md`](estado.md).

## Cómo retomar el trabajo

1. `git pull` sobre `main`.
2. Leer [`estado.md`](estado.md) completo. Dice en qué punto está el proyecto, cuál es la siguiente tarea y qué advertencias dejó la última persona.
3. Leer esta guía, sobre todo las reglas no negociables.
4. Leer de [`diseno.md`](diseno.md) las secciones que toca la fase que se va a trabajar. La sección "Qué leer por fase" de `estado.md` las enumera.
5. Comprobar que el entorno funciona antes de cambiar nada (ver "Comandos"). La suite debe estar en verde al empezar.
6. Trabajar en una rama, y **antes de cada push actualizar `estado.md`** (ver "Antes de cada push").

## Mapa de la documentación

| Archivo | Para qué sirve |
|---|---|
| `docs/estado.md` | Estado actual, siguiente paso, decisiones tomadas y bitácora. Se actualiza en cada push. |
| `docs/guia_desarrollo.md` | Este archivo. Reglas, convenciones y flujo de trabajo. |
| `docs/diseno.md` | **Fuente de verdad técnica.** Formato binario byte a byte, protocolo, comprobaciones, seguridad web, pruebas y experimentos. Se lee antes de escribir código criptográfico o de formato. |
| `docs/requisitos_entregable2.md` | Qué exige el enunciado para la entrega final y cómo se evalúa. |
| `docs/plan_implementacion.md` | Fases con casillas de verificación. Se marca cada casilla al terminarla. |
| `docs/desviaciones.md` | Registro obligatorio de todo cambio respecto al diseño entregado. El informe final debe explicarlos. |
| `docs/entregable1/Entregable1_Proyecto_final.pdf` | Documento de diseño que se entregó. Si contradice a `diseno.md`, manda el PDF. |
| `docs/referencias/` | PDF del curso. No se versionan, cada integrante los copia a mano (ver su README). |

## Stack

- Python 3.12 y una sola biblioteca criptográfica: `cryptography` (pyca), que aporta ChaCha20-Poly1305 y Argon2id.
- `fastapi` y `uvicorn` para la interfaz web local. Frontend en HTML y JS propios, sin frameworks ni CDN (la CSP es `default-src 'self'`).
- `pytest` para pruebas y `playwright` para las de navegador (T12 y T13, se añade en la Fase 5).
- Dependencias fijadas con hashes mediante `pip-tools` (`requirements.in` genera `requirements.txt`).
- Plataforma de referencia: Linux dentro de Docker. El equipo desarrolla en Windows, así que todo lo que dependa de `fsync`, `os.replace` o permisos 0600 se valida dentro del contenedor.

## Estructura del repositorio

```
pvlt/
  params.py   constantes públicas del protocolo (tamaños, etiquetas, límites, configuraciones). Sin dependencias.
  crypto/     funciones puras sobre `cryptography`. Sin estado, sin disco.
  storage/    formato binario v1, validación de límites, guardado atómico, respaldo, lock.
  vault/      sesión, entradas, operaciones (crear, abrir, guardar, cambiar contraseña, exportar, importar), generador.
              Única capa que sostiene la KEK. No importa nada de web/.
  web/        FastAPI, seguridad HTTP, plantillas y estáticos.
  cli.py      punto de entrada mínimo por línea de comandos para pruebas y experimentos.
tests/        pytest, organizado por capa.
bench/        scripts de los experimentos E1, E2, E3 y sus resultados en CSV.
scripts/      utilidades (verificación del entorno, regenerar dependencias).
docs/         contexto, diseño, estado y desviaciones.
```

Las dependencias van en un solo sentido: `web → vault → (crypto, storage)`. `storage/` nunca recibe claves ni texto claro. `crypto/` nunca toca el disco. `tests/test_smoke.py` hace fallar la suite si una capa importa hacia arriba.

## Reglas no negociables

Vienen del enunciado o del diseño entregado. Romper cualquiera afecta directamente la nota.

1. **No implementar primitivas propias.** Toda operación criptográfica pasa por `cryptography`. Aleatoriedad solo con `secrets` (u `os.urandom`). Nunca `random`.
2. **Nunca registrar secretos.** Ni contraseñas, claves, sitios, usuarios ni notas en logs, excepciones, mensajes de error, temporales, argumentos de proceso, variables de entorno ni URL. El log de acceso de uvicorn va desactivado. Cuidado con el `repr` de objetos que contengan secretos y con las trazas de excepciones.
3. **La contraseña maestra solo entra por el cuerpo de un POST local** (o por `getpass` en el CLI). Nunca por argumentos ni variables de entorno.
4. **Cada guardado usa una DEK nueva y nonces nuevos.** Nada de contadores persistentes.
5. **La cabecera completa va como dato asociado** con las etiquetas de dominio exactas de `diseno.md` (están en `pvlt/params.py`).
6. **Validar los límites de parámetros antes de ejecutar Argon2id.**
7. **Ningún fallo de apertura escribe en disco** ni crea una bóveda vacía.
8. **Escritura siempre atómica** (temporal, fsync, verificación, respaldo, `os.replace`, fsync del directorio). Ya está resuelto en `pvlt/storage/store.py`. Ninguna otra capa escribe archivos de bóveda por su cuenta.
9. **Datos de prueba sintéticos.** Nunca contraseñas reales.
10. **Cualquier cambio al formato, protocolo o parámetros se anota en `desviaciones.md`** con fecha, qué cambió y por qué.

## Convenciones de código

- Identificadores, nombres de módulos y docstrings técnicos en inglés. Mensajes de la interfaz, README, documentación e informe en español.
- Tipado con anotaciones y `mypy` en modo estricto para `crypto/`, `storage/` y `vault/`.
- Excepciones propias por categoría de fallo (formato, archivo dañado, contraseña incorrecta, contenido manipulado), sin texto secreto en sus mensajes.
- Las pruebas funcionales usan la configuración A de Argon2id (64 MiB) para que la suite corra rápido. Las pruebas que solo ejercitan la interfaz pueden usar parámetros mínimos.
- En la documentación y el informe: registro académico natural y **sin punto y coma**.
- Lo que el diseño no fija y se decide al implementar se anota en `diseno.md` marcado como **(concreción)**. Solo va a `desviaciones.md` si contradice el PDF entregado.

## Comandos

Todo se ejecuta dentro del contenedor. El código se copia a la imagen al construirla, así que **hay que reconstruir después de cada cambio** o las pruebas correrán contra la versión anterior.

```
docker compose build
docker compose run --rm app pytest
docker compose run --rm app pytest -m "not slow"   # sin las dos pruebas largas, para iterar
docker compose run --rm app mypy
docker compose run --rm app ruff check .
docker compose run --rm app ruff format --check .
docker compose run --rm app python scripts/check_env.py
```

Aplicar las correcciones automáticas de `ruff` sobre los archivos del equipo anfitrión (PowerShell):

```
docker run --rm -u root -v "${PWD}:/app" -w /app pvlt:dev sh -c "ruff check . --fix --no-cache; ruff format . --no-cache"
```

Regenerar `requirements.txt` con hashes. Siempre en la imagen de referencia, nunca en Windows, porque la resolución depende de la plataforma:

```
docker run --rm -e PIP_DEFAULT_TIMEOUT=120 -v "${PWD}:/app" -w /app python:3.12-slim sh scripts/compile_requirements.sh
```

## Flujo de trabajo con git

- Una rama por fase o por tema: `feat/crypto`, `feat/storage`, `feat/vault`, `fix/...`, `docs/...`.
- Commits pequeños por tema con Conventional Commits en español, en minúsculas y sin tildes en el asunto: `feat(storage): ...`, `test(vault): ...`, `fix(web): ...`, `docs: ...`, `refactor(params): ...`, `chore: ...`. El cuerpo es opcional, una o dos frases que expliquen el porqué.
- Cada integrante hace los commits con su propia identidad de git (nombre y correo asociados a su cuenta de GitHub).
- La rama se fusiona en `main` con un commit de merge (`git merge --no-ff`) cuando la suite, `mypy` y `ruff` están en verde. Después se borra.
- No se versionan bóvedas (`*.pvlt` y derivados), resultados crudos de experimentos, entornos virtuales, los PDF del curso ni archivos de configuración personales de editores o herramientas.

## Antes de cada push

Es el paso que permite que la siguiente persona retome con solo hacer `git pull`. No es opcional.

1. `pytest`, `mypy`, `ruff check` y `ruff format --check` en verde dentro del contenedor.
2. Marcar en `plan_implementacion.md` las casillas terminadas.
3. Actualizar `estado.md`:
   - la tabla de fases y la sección "Siguiente paso",
   - las decisiones nuevas, si las hubo,
   - una entrada nueva al principio de la bitácora.
4. Si se cambió algo del formato, protocolo o parámetros, anotarlo en `desviaciones.md` o como concreción en `diseno.md`.
5. Si el trabajo queda a medias, decirlo con claridad en la bitácora: qué funciona, qué no, y por dónde seguir. Es preferible subir una rama a medias bien descrita que dejar el trabajo solo en un equipo.
