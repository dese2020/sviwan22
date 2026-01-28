
# syntax=docker/dockerfile:1.7

# 1) Etapas de assets (alias distintos)
FROM dese251/sviwan22:files AS assets_b


# 2) Imagen final basada en runtime (una sola FROM final)
FROM dese251/sviwan22:comfy AS final
ENV PATH="/opt/venv/bin:${PATH}"
WORKDIR /

# Copiar modelos de las TRES etapas de assets
# Si hay colisiones de nombres, el último COPY gana.
COPY --from=assets_b /ComfyUI/models/ /ComfyUI/models/

# Archivos estables ya están en runtime (config.ini, extra_model_paths.yaml, entrypoint.sh)

# ---- Cambios frecuentes: SOLO aquí ----
WORKDIR /app
COPY handler.py /app/handler.py
COPY workflow/ /app/workflow/

# (Opcional) Verifica permisos del entrypoint si no estuvieran en la base:
# RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]