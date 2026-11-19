FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    PVLT_IN_DOCKER=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

WORKDIR /app

# Usuario sin privilegios. La bóveda vive en /data (volumen) con permisos 0700.
RUN useradd --create-home --uid 1000 pvlt \
    && mkdir -p /data && chown pvlt:pvlt /data /app && chmod 700 /data

# Dependencias fijadas con hashes. pip rechaza cualquier paquete que no coincida.
COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt

# Chromium sin interfaz para las pruebas de navegador (T12, T13), en una ruta
# compartida para que lo encuentre el usuario sin privilegios.
# El controlador de Playwright necesita libatomic antes de poder instalar el resto.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && python -m playwright install --with-deps --only-shell chromium \
    && chmod -R a+rX /opt/ms-playwright \
    && rm -rf /var/lib/apt/lists/*

# El paquete se ejecuta desde /app (python -m pvlt.cli, python -m pvlt.web).
COPY --chown=pvlt:pvlt . .

USER pvlt
VOLUME ["/data"]

EXPOSE 8765
CMD ["python", "-m", "pvlt.web"]
