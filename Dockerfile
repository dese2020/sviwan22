# syntax=docker/dockerfile:1.7

# 1. Imagen base oficial de NVIDIA con CUDA 13 (devel para permitir compilar custom nodes)
FROM nvidia/cuda:13.2.1-devel-ubuntu22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    HF_HUB_ENABLE_HF_TRANSFER=1

WORKDIR /

# 2. Instalación de dependencias del sistema y Python 3.10
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    wget \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    python3.10 \
    python3-pip \
    python3-venv \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Crear entorno virtual e instalar PyTorch compilado con soporte CUDA 13
RUN python3 -m venv /opt/venv && \
    pip install --no-cache-dir -U pip setuptools wheel && \
    pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130

RUN pip install --no-cache-dir "huggingface_hub[hf_transfer]" runpod websocket-client
RUN pip install --no-cache-dir sageattention

# 3. Clonado de ComfyUI y Nodos Personalizados
RUN git config --global http.version HTTP/1.1 && \
    git config --global http.lowSpeedLimit 1 && \
    git config --global http.lowSpeedTime 600 && \
    git config --global http.postBuffer 524288000

RUN git clone --depth=1 https://github.com/comfyanonymous/ComfyUI.git /ComfyUI && \
    pip install --no-cache-dir -r /ComfyUI/requirements.txt

WORKDIR /ComfyUI/custom_nodes

RUN git clone --depth=1 https://github.com/kijai/ComfyUI-KJNodes && \
    pip install --no-cache-dir -r ComfyUI-KJNodes/requirements.txt && \
    \
    git clone --depth=1 https://github.com/Fannovel16/ComfyUI-Frame-Interpolation && \
    python3 ComfyUI-Frame-Interpolation/install.py && \
    \
    git clone --depth=1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite && \
    pip install --no-cache-dir -r ComfyUI-VideoHelperSuite/requirements.txt && \
    \
    git clone --depth=1 https://github.com/yolain/ComfyUI-Easy-Use && \
    pip install --no-cache-dir -r ComfyUI-Easy-Use/requirements.txt && \
    \
    git clone --depth=1 https://github.com/city96/ComfyUI-GGUF && \
    pip install --no-cache-dir -r ComfyUI-GGUF/requirements.txt && \
    \
    git clone --depth=1 https://github.com/wallen0322/ComfyUI-Wan22FMLF && \
    \
    git clone --depth=1 https://github.com/cubiq/ComfyUI_essentials && \
    pip install --no-cache-dir -r ComfyUI_essentials/requirements.txt && \
    \
    git clone --depth=1 https://github.com/M1kep/ComfyLiterals

RUN find /ComfyUI -name ".git" -type d -exec rm -rf {} +

WORKDIR /

# 4. Descarga de Modelos Wan 2.2, VAE, GGUF y LoRAs (SVI)
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='BigDannyPt/Wan-2.2-Remix-GGUF', filename='I2V/v3.0/High/wan22RemixT2VI2V_i2vHighV30-Q8_0.gguf', local_dir='/ComfyUI/models/diffusion_models/', local_dir_use_symlinks=False)" && \
    python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='BigDannyPt/Wan-2.2-Remix-GGUF', filename='I2V/v3.0/Low/wan22RemixT2VI2V_i2vLowV30-Q8_0.gguf', local_dir='/ComfyUI/models/diffusion_models/', local_dir_use_symlinks=False)" && \
    mv /ComfyUI/models/diffusion_models/I2V/v3.0/High/wan22RemixT2VI2V_i2vHighV30-Q8_0.gguf /ComfyUI/models/diffusion_models/wan22RemixT2VI2V_i2vHighV30-Q8_0.gguf && \
    mv /ComfyUI/models/diffusion_models/I2V/v3.0/Low/wan22RemixT2VI2V_i2vLowV30-Q8_0.gguf /ComfyUI/models/diffusion_models/wan22RemixT2VI2V_i2vLowV30-Q8_0.gguf && \
    rm -rf /ComfyUI/models/diffusion_models/I2V

RUN python3 - <<'EOF'
from huggingface_hub import hf_hub_download

downloads = [
	('Kijai/WanVideo_comfy', 'LoRAs/Stable-Video-Infinity/v2.0/SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors'),
	('Kijai/WanVideo_comfy', 'LoRAs/Stable-Video-Infinity/v2.0/SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors'),
	('Comfy-Org/Wan_2.2_ComfyUI_Repackaged', 'split_files/vae/wan_2.1_vae.safetensors'),
	('city96/umt5-xxl-encoder-gguf', 'umt5-xxl-encoder-Q8_0.gguf')
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

RUN mkdir -p /ComfyUI/models/vae /ComfyUI/models/text_encoders && \
    mv /ComfyUI/models/loras/split_files/vae/wan_2.1_vae.safetensors /ComfyUI/models/vae/wan_2.1_vae.safetensors && \
    mv /ComfyUI/models/loras/umt5-xxl-encoder-Q8_0.gguf /ComfyUI/models/text_encoders/umt5-xxl-encoder-Q8_0.gguf && \
    mv /ComfyUI/models/loras/LoRAs/Stable-Video-Infinity/v2.0/SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors /ComfyUI/models/loras/SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors && \
    mv /ComfyUI/models/loras/LoRAs/Stable-Video-Infinity/v2.0/SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors /ComfyUI/models/loras/SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors && \
    rm -rf /ComfyUI/models/loras/split_files /ComfyUI/models/loras/LoRAs

# 5. Copia de archivos del usuario y entrada
COPY . /app
WORKDIR /app

RUN mkdir -p /ComfyUI/user/default/ComfyUI-Manager /ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation/ckpts/rife
RUN [ -f config.ini ] && cp config.ini /ComfyUI/user/default/ComfyUI-Manager/config.ini || true
RUN [ -f extra_model_paths.yaml ] && cp extra_model_paths.yaml /ComfyUI/extra_model_paths.yaml || true
RUN [ -f rife49.pth ] && cp rife49.pth /ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation/ckpts/rife/rife49.pth || true

RUN chmod +x /app/entrypoint.sh

# CAMBIO AQUÍ: Mantener el WORKDIR en /app en lugar de volver a /
WORKDIR /app

CMD ["/app/entrypoint.sh"]