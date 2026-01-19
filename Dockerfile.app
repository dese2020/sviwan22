
# syntax=docker/dockerfile:1.7

# 1) Runtime con ComfyUI y venv listo
FROM dese251/sviwan22:run AS runtime

# 2) Assets de modelos (solo para copiar modelos)
FROM dese251/sviwan22:wan2.2 AS assets

# 3) Imagen final: parte del runtime
FROM dese251/sviwan22:run
ENV PATH="/opt/venv/bin:${PATH}"
WORKDIR /

# Copia modelos desde la imagen de assets (rápido, sin re-descargar)
COPY --from=assets /ComfyUI/models /ComfyUI/models

# Archivos estables ya están en runtime (config.ini, extra_model_paths.yaml, entrypoint.sh)

# ---- Cambios frecuentes: SOLO aquí ----
WORKDIR /app
COPY handler.py /app/handler.py
COPY workflow/ /app/workflow/

CMD ["/entrypoint.sh"]
