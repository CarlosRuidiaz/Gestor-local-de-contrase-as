# Requisitos del Entregable 2 según el enunciado

Fuente: `docs/referencias/Enunciados.pdf`, páginas 2, 3, 7 y 8.

## Qué se entrega (60 % de la nota del proyecto)

- Repositorio ejecutable.
- Informe final de **8 a 12 páginas**. Puede corregir el diseño inicial, pero debe explicar las desviaciones entre la propuesta y la implementación (por eso existe `docs/desviaciones.md`).
- Pruebas automatizadas.
- Scripts y datos de experimentación.
- Demostración reproducible.
- Fecha: semana 10 del proyecto, que corresponde a la **semana académica 16**.

## Requisitos comunes del producto

- README con instalación desde cero, dependencias fijadas, comandos de ejecución y guion de demostración.
- Separación comprensible entre interfaz, lógica del protocolo, primitivas criptográficas, persistencia y pruebas.
- Formatos versionados, serialización inequívoca e identificación explícita de algoritmos y parámetros.
- Pruebas positivas, negativas y de manipulación. Una demostración exitosa no reemplaza las pruebas automatizadas.
- Datos sintéticos o autorizados. Prohibido registrar secretos, contraseñas, claves o textos claros sensibles.
- Bibliotecas mantenidas. No implementar operaciones internas salvo fines pedagógicos exigidos.
- Ejecución local o con contenedores reproducibles. No se requiere despliegue público.

## Criterios de evaluación

| Componente | Peso | Evidencia |
|---|---|---|
| Producto funcional | 30 % | Producto mínimo completo, integración, manejo de errores, experiencia de uso |
| Diseño y precisión técnica | 25 % | Protocolo, supuestos, formatos, modelo de adversario, decisiones justificadas desde las referencias |
| Criptografía aplicada | 20 % | Uso correcto de primitivas, claves, nonces, dominios, validaciones y límites de seguridad |
| Pruebas y experimentos | 15 % | Casos positivos y negativos, métricas reproducibles, análisis de resultados |
| Informe y reproducibilidad | 10 % | Claridad, referencias, README, scripts, calidad del repositorio |

## Proyecto 2: producto esperado

- Aplicación de escritorio, web local o CLI para crear, desbloquear y bloquear una bóveda. (Elegimos web local.)
- Agregar, buscar, consultar, modificar y eliminar credenciales con sitio, usuario, contraseña y notas.
- Generador configurable de contraseñas y bloqueo automático por inactividad.
- Cambio de contraseña maestra sin perder registros.
- Importación y exportación solo en formato cifrado, con recuperación segura ante fallo durante el guardado.

## Proyecto 2: requisitos técnicos mínimos

- Una bóveda, un usuario, 1 a 500 entradas.
- Argon2id versión 1.3 con sal aleatoria.
- AEAD estándar de una biblioteca mantenida.
- Nonce nuevo por cifrado bajo la misma clave y autenticación de metadatos críticos.
- Formato versionado con los parámetros necesarios para abrir y permitir migraciones.
- Contraseña maestra y claves derivadas fuera de logs, temporales y argumentos visibles del proceso.

## Proyecto 2: demostración y pruebas exigidas

- Crear, cerrar y reabrir bóvedas con 1, 100 y 500 entradas. (T1)
- Todas las operaciones sobre credenciales y el cambio de contraseña maestra. (T1, T2)
- Rechazar contraseña incorrecta sin crear bóveda vacía ni sobrescribir la existente. (T4)
- Detectar modificaciones en contenido cifrado, etiqueta, nonce y metadatos autenticados. (T5)
- Simular un fallo durante el guardado y recuperar la última versión íntegra. (T7)
- Medir tiempo y memoria de desbloqueo para al menos tres configuraciones de Argon2id y el tiempo de abrir y guardar bóvedas de distintos tamaños. (E1, E2)

## Fuera de alcance

- Sincronización en la nube, extensiones de navegador, autocompletado, cuentas compartidas, apps móviles.
- Protección completa frente a malware, keyloggers, volcados de memoria o control del sistema operativo.
- Diseñar una KDF o cifrador nuevos, o compatibilidad con formatos comerciales.

## Nota del docente

Cumplir el enunciado demuestra comprensión e integración, no certifica el software para uso real. El informe debe presentar los resultados como evidencia dentro del modelo definido.
