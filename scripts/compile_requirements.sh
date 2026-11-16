#!/bin/sh
# Regenera requirements.txt con hashes. Debe ejecutarse en python:3.12-slim (Linux)
# para que la resolución corresponda a la plataforma de referencia.
set -eu
pip install --quiet --root-user-action=ignore pip-tools
pip-compile --generate-hashes --allow-unsafe --strip-extras --quiet \
    --output-file requirements.txt requirements.in
echo "requirements.txt regenerado"
