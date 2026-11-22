# Imagen para compilar el informe: docker build -t pvlt-informe docs/informe
FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        latexmk texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended \
        texlive-lang-spanish texlive-science texlive-pictures lmodern \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
