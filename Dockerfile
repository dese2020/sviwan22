
# syntax=docker/dockerfile:1.7

# 1) Etapas de assets (alias distintos)
#FROM dese251/sviwan22:bassets2 AS assets_b
#FROM dese251/sviwan22:hassets2 AS assets_h
#FROM dese251/sviwan22:lassets2 AS assets_l
#FROM dese251/sviwan22:lora AS lora
#FROM dese251/sviwan22:lora2 AS lora2


# 2) Imagen final basada en runtime (una sola FROM final)
FROM dese251/sviwan22:run AS final
ENV PATH="/opt/venv/bin:${PATH}"
WORKDIR /

# Copiar modelos de las TRES etapas de assets
# Si hay colisiones de nombres, el último COPY gana.
#COPY --from=assets_b /ComfyUI/models/ /ComfyUI/models/
#COPY --from=assets_h /ComfyUI/models/ /ComfyUI/models/
#COPY --from=assets_l /ComfyUI/models/ /ComfyUI/models/
#COPY --from=lora /ComfyUI/models/loras/ /ComfyUI/models/loras/
#COPY --from=lora2 /ComfyUI/models/loras/ /ComfyUI/models/loras/


# Archivos estables ya están en runtime (config.ini, extra_model_paths.yaml, entrypoint.sh)

# ---- Cambios frecuentes: SOLO aquí ---- pronto sin modelos
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='BigDannyPt/Wan-2.2-Remix-GGUF', filename='I2V/v3.0/High/wan22RemixT2VI2V_i2vHighV30-Q8_0.gguf', local_dir='/ComfyUI/models/diffusion_models/', local_dir_use_symlinks=False)"
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='BigDannyPt/Wan-2.2-Remix-GGUF', filename='I2V/v3.0/Low/wan22RemixT2VI2V_i2vLowV30-Q8_0.gguf', local_dir='/ComfyUI/models/diffusion_models/', local_dir_use_symlinks=False)"
RUN mv /ComfyUI/models/diffusion_models/I2V/v3.0/High/wan22RemixT2VI2V_i2vHighV30-Q8_0.gguf /ComfyUI/models/diffusion_models/wan22RemixT2VI2V_i2vHighV30-Q8_0.gguf 
RUN mv /ComfyUI/models/diffusion_models/I2V/v3.0/Low/wan22RemixT2VI2V_i2vLowV30-Q8_0.gguf /ComfyUI/models/diffusion_models/wan22RemixT2VI2V_i2vLowV30-Q8_0.gguf 


RUN python3 - <<'EOF'
from huggingface_hub import hf_hub_download

downloads = [
	('Kijai/WanVideo_comfy',      'LoRAs/Stable-Video-Infinity/v2.0/SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors'),
	('Kijai/WanVideo_comfy',      'LoRAs/Stable-Video-Infinity/v2.0/SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors'),
	('Comfy-Org/Wan_2.2_ComfyUI_Repackaged',      'split_files/vae/wan_2.1_vae.safetensors'),
	('city96/umt5-xxl-encoder-gguf',      'umt5-xxl-encoder-Q8_0.gguf')
]

for repo_id, filename in downloads:
    print(f'Downloading {filename}...')
    hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir='/ComfyUI/models/loras',
        local_dir_use_symlinks=False
    )
EOF

RUN mv /ComfyUI/models/loras/split_files/vae/wan_2.1_vae.safetensors /ComfyUI/models/vae/wan_2.1_vae.safetensors && \
	mv /ComfyUI/models/loras/umt5-xxl-encoder-Q8_0.gguf /ComfyUI/models/text_encoders/umt5-xxl-encoder-Q8_0.gguf && \
	mv /ComfyUI/models/loras/LoRAs/Stable-Video-Infinity/v2.0/SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors /ComfyUI/models/loras/SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors && \
	mv /ComfyUI/models/loras/LoRAs/Stable-Video-Infinity/v2.0/SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors /ComfyUI/models/loras/SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors 


RUN find /ComfyUI/models/loras -mindepth 2 -maxdepth 2 -type f -name '*.safetensors' \
    -exec mv -t /ComfyUI/models/loras {} +


# (Opcional) Verifica permisos del entrypoint si no estuvieran en la bases:
# RUN chmod +x /entrypoint.sh
COPY . .
RUN mkdir -p /ComfyUI/user/default/ComfyUI-Manager
COPY config.ini /ComfyUI/user/default/ComfyUI-Manager/config.ini
COPY extra_model_paths.yaml /ComfyUI/extra_model_paths.yaml
COPY rife49.pth /ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation/ckpts/rife/rife49.pth
RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]
