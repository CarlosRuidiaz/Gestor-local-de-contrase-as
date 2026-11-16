FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    PVLT_IN_DOCKER=1

WORKDIR /app

# Usuario sin privilegios. La bóveda vive en /data (volumen) con permisos 0700.
RUN useradd --create-home --uid 1000 pvlt \
    && mkdir -p /data && chown pvlt:pvlt /data /app && chmod 700 /data

# Dependencias fijadas con hashes. pip rechaza cualquier paquete que no coincida.
COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt

# El paquete se ejecuta desde /app (python -m pvlt.cli, python -m pvlt.web).
COPY --chown=pvlt:pvlt . .

USER pvlt
VOLUME ["/data"]

EXPOSE 8765
CMD ["python", "-m", "pvlt.web"]
