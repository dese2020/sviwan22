
# syntax=docker/dockerfile:1.7

# 1) Etapas de assets (alias distintos)
FROM dese251/sviwan22:bassets2 AS assets_b
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
COPY --from=assets_b /ComfyUI/models/ /ComfyUI/models/
#COPY --from=assets_h /ComfyUI/models/ /ComfyUI/models/
#COPY --from=assets_l /ComfyUI/models/ /ComfyUI/models/
#COPY --from=lora /ComfyUI/models/loras/ /ComfyUI/models/loras/
#COPY --from=lora2 /ComfyUI/models/loras/ /ComfyUI/models/loras/


# Archivos estables ya están en runtime (config.ini, extra_model_paths.yaml, entrypoint.sh)

# ---- Cambios frecuentes: SOLO aquí ----
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='BigDannyPt/Wan-2.2-Remix-GGUF', filename='I2V/v3.0/High/wan22RemixT2VI2V_i2vHighV30-Q8_0.gguf', local_dir='/ComfyUI/models/diffusion_models/', local_dir_use_symlinks=False)"
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='BigDannyPt/Wan-2.2-Remix-GGUF', filename='I2V/v3.0/Low/wan22RemixT2VI2V_i2vLowV30-Q8_0.gguf', local_dir='/ComfyUI/models/diffusion_models/', local_dir_use_symlinks=False)"
RUN mv /ComfyUI/models/diffusion_models/I2V/v3.0/High/wan22RemixT2VI2V_i2vHighV30-Q8_0.gguf /ComfyUI/models/diffusion_models/wan22RemixT2VI2V_i2vHighV30-Q8_0.gguf 
RUN mv /ComfyUI/models/diffusion_models/I2V/v3.0/Low/wan22RemixT2VI2V_i2vLowV30-Q8_0.gguf /ComfyUI/models/diffusion_models/wan22RemixT2VI2V_i2vLowV30-Q8_0.gguf 

RUN wget -q https://huggingface.co/hijdese2020/facialsplash/resolve/main/wan22-f4c3spl4sh-100epoc-high-k3nk.safetensors -O /ComfyUI/models/loras/wan22-f4c3spl4sh-100epoc-high-k3nk.safetensors         && \
	wget -q https://huggingface.co/hijdese2020/facialsplash/resolve/main/wan22-f4c3spl4sh-154epoc-low-k3nk.safetensors  -O /ComfyUI/models/loras/wan22-f4c3spl4sh-154epoc-low-k3nk.safetensors          && \
	wget -q https://huggingface.co/hijdese2020/oral_insert/resolve/main/wan2.2-i2v-high-oral-insertion-v1.0.safetensors -O /ComfyUI/models/loras/wan2.2-i2v-high-oral-insertion-v1.0.safetensors        && \
	wget -q https://huggingface.co/hijdese2020/oral_insert/resolve/main/wan2.2-i2v-low-oral-insertion-v1.0.safetensors  -O /ComfyUI/models/loras/wan2.2-i2v-low-oral-insertion-v1.0.safetensors         && \
	wget -q https://huggingface.co/hijdese2020/breast_insert/resolve/main/wan2.2-i2v-high-breast-insertion-v1.0.safetensors  -O /ComfyUI/models/loras/wan2.2-i2v-high-breast-insertion-v1.0.safetensors && \
	wget -q https://huggingface.co/hijdese2020/breast_insert/resolve/main/wan2.2-i2v-low-breast-insertion-v1.0.safetensors -O /ComfyUI/models/loras/wan2.2-i2v-low-breast-insertion-v1.0.safetensors    && \
	wget -q https://huggingface.co/hijdese2020/sex_fov/resolve/main/wan2.2-i2v-high-sex-fov-slider-v1.0.safetensors -O /ComfyUI/models/loras/wan2.2-i2v-high-sex-fov-slider-v1.0.safetensors            && \
	wget -q https://huggingface.co/hijdese2020/sex_fov/resolve/main/wan2.2-i2v-low-sex-fov-slider-v1.0.safetensors -O /ComfyUI/models/loras/wan2.2-i2v-low-sex-fov-slider-v1.0.safetensors         


RUN python3 - <<'EOF'
import os
from huggingface_hub import hf_hub_download

repo_id = "hijdese2020/wan22_datalora"
repo_type = "dataset"
local_dir = "/ComfyUI/models/loras/"

files = [
    "blowbang/bl0wb4ng_HN_80.safetensors",
    "blowbang/bl0wb4ng_LN_80.safetensors",
    "clearcum/CIM_WAN22_I2V_512_high_noise.safetensors",
    "clearcum/CIM_WAN22_I2V_512_low_noise.safetensors",
	"throatpie/Throatpie_WAN22_I2V_high_noise.safetensors",
	"throatpie/Throatpie_WAN22_I2V_low_noise.safetensors",
	"multi_nude/W22_Multiscene_Photoshoot_Softcore_i2v_HN.safetensors",
	"multi_nude/W22_Multiscene_Photoshoot_Softcore_i2v_LN.safetensors",
	"missionary/W22_HN_i2v_POV_Missionary_Insertion_v1.safetensors",
	"missionary/W22_LN_i2v_POV_Missionary_Insertion_v1.safetensors",
	"pov_ride/W22_POV_Cowgirl_Insertion_i2v_HN_v1A.safetensors",
	"pov_ride/W22_POV_Cowgirl_Insertion_i2v_LN_v1.safetensors",
	"blink_tit/iGoon_Blink_Titjob_I2V_HIGH.safetensors",
	"blink_tit/iGoon_Blink_Titjob_I2V_LOW.safetensors",
	"blink_hand/iGoon_Blink_Handjob_I2V_HIGH.safetensors", 
	"blink_hand/iGoon_Blink_Handjob_I2V_LOW.safetensors",
	"blink_blow/iGOON_Blink_Blowjob_I2V_HIGH.safetensors",
	"blink_blow/iGOON_Blink_Blowjob_I2V_LOW.safetensors", 
	"blink_cum/iGoon_Blink_Facial_I2V_HIGH.safetensors",
	"blink_cum/iGoon_Blink_Facial_I2V_LOW.safetensors",
	"allnsfw/wan22-k3nk4llinon3-15epoc-full-low-k3nk.safetensors",
	"allnsfw/wan22-k3nk4llinon3-16epoc-full-high-k3nk.safetensors",
	"blink_ride/Blink_Squatting_Cowgirl_Position_I2V_HIGH.safetensors",
	"blink_ride/Blink_Squatting_Cowgirl_Position_I2V_LOW.safetensors",
	"blink_doggy/iGoon-Blink_Front_Doggystyle_I2V_HIGH.safetensors",
	"blink_doggy/iGoon-Blink_Front_Doggystyle_I2V_LOW.safetensors"
]

for f in files:
    path = hf_hub_download(
        repo_id=repo_id,
        repo_type=repo_type,
        filename=f,
		local_dir=local_dir
    )

EOF

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
