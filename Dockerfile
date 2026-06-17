
# syntax=docker/dockerfile:1.7

# 1) Etapas de assets (alias distintos)
FROM dese251/sviwan22:bassets2 AS assets_b
FROM dese251/sviwan22:hassets2 AS assets_h
FROM dese251/sviwan22:lassets2 AS assets_l
FROM dese251/sviwan22:lora AS lora
FROM dese251/sviwan22:lora2 AS lora2


# 2) Imagen final basada en runtime (una sola FROM final)
FROM dese251/sviwan22:run AS final
ENV PATH="/opt/venv/bin:${PATH}"
WORKDIR /

# Copiar modelos de las TRES etapas de assets
# Si hay colisiones de nombres, el último COPY gana.
COPY --from=assets_b /ComfyUI/models/ /ComfyUI/models/
COPY --from=assets_h /ComfyUI/models/ /ComfyUI/models/
COPY --from=assets_l /ComfyUI/models/ /ComfyUI/models/
COPY --from=lora /ComfyUI/models/loras/ /ComfyUI/models/loras/
COPY --from=lora2 /ComfyUI/models/loras/ /ComfyUI/models/loras/


# Archivos estables ya están en runtime (config.ini, extra_model_paths.yaml, entrypoint.sh)

# ---- Cambios frecuentes: SOLO aquí ----
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='hijdese2020/wan22_datalora', repo_type='dataset', filename='blowbang/bl0wb4ng_HN_80.safetensors', local_dir='/ComfyUI/models/loras/', local_dir_use_symlinks=False)"
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='hijdese2020/wan22_datalora', repo_type='dataset', filename='blowbang/bl0wb4ng_LN_80.safetensors', local_dir='/ComfyUI/models/loras/', local_dir_use_symlinks=False)"
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='hijdese2020/wan22_datalora', repo_type='dataset', filename='clearcum/CIM_WAN22_I2V_512_high_noise.safetensors', local_dir='/ComfyUI/models/loras/', local_dir_use_symlinks=False)"
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='hijdese2020/wan22_datalora', repo_type='dataset', filename='clearcum/CIM_WAN22_I2V_512_low_noise.safetensors', local_dir='/ComfyUI/models/loras/', local_dir_use_symlinks=False)"

# (Opcional) Verifica permisos del entrypoint si no estuvieran en la base:
# RUN chmod +x /entrypoint.sh
COPY . .
RUN mkdir -p /ComfyUI/user/default/ComfyUI-Manager
COPY config.ini /ComfyUI/user/default/ComfyUI-Manager/config.ini
COPY extra_model_paths.yaml /ComfyUI/extra_model_paths.yaml
COPY rife49.pth /ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation/ckpts/rife/rife49.pth
RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]
