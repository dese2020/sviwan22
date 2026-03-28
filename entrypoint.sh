#!/bin/bash
set -e

echo "========== RUNPOD WORKER INIT =========="

########################################
# 0. SYSTEM + CUDA DEBUG (NUEVO)
########################################
echo "========== SYSTEM DEBUG =========="

echo "[SYS] Python version:"
python --version || true

echo "[SYS] NVIDIA-SMI:"
nvidia-smi || echo "nvidia-smi failed"

echo "[SYS] CUDA ENV:"
env | grep CUDA || true

########################################
# 1. GPU VALIDATION (FAIL FAST)
########################################
echo "[CHECK] GPU info..."

GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n1 || echo "unknown")
VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n1 || echo "0")

echo "[INFO] GPU: $GPU_NAME"
echo "[INFO] VRAM: ${VRAM}MB"

MIN_VRAM=16000

if [ "$VRAM" -lt "$MIN_VRAM" ]; then
    echo "[FAIL] GPU incompatible (VRAM < ${MIN_VRAM}MB)"
    exit 2
fi

########################################
# 2. PYTORCH + CUDA DEBUG (CRÍTICO)
########################################
echo "========== TORCH CUDA DEBUG =========="

python - <<'EOF'
import torch, os, platform

print("[TORCH] Version:", torch.__version__)
print("[TORCH] CUDA compiled:", torch.version.cuda)
print("[TORCH] CUDA_VISIBLE_DEVICES:", os.environ.get("CUDA_VISIBLE_DEVICES"))

available = torch.cuda.is_available()
print("[TORCH] cuda.is_available():", available)
print("[TORCH] device_count:", torch.cuda.device_count())

if available:
    try:
        print("[TORCH] device:", torch.cuda.get_device_name(0))
        print("[TORCH] capability:", torch.cuda.get_device_capability(0))

        # TEST REAL (muy importante)
        x = torch.randn(1).cuda()
        print("[TORCH] CUDA test: OK")

        total = torch.cuda.get_device_properties(0).total_memory
        print(f"[TORCH] VRAM total: {total / 1024**3:.2f} GB")

    except Exception as e:
        print("[TORCH] CUDA test FAILED:", str(e))
        exit(10)
else:
    print("[TORCH] ❌ CUDA NOT AVAILABLE")
    exit(11)
EOF

########################################
# 3. START COMFYUI
########################################
echo "[START] Launching ComfyUI..."

python /ComfyUI/main.py --listen --use-sage-attention &
COMFY_PID=$!

echo "[INFO] ComfyUI PID: $COMFY_PID"

########################################
# 4. EARLY CRASH DETECTION
########################################
sleep 5

if ! kill -0 $COMFY_PID 2>/dev/null; then
    echo "[FAIL] ComfyUI crashed immediately"
    exit 3
fi

########################################
# 5. SMART HEALTHCHECK
########################################
echo "[WAIT] Waiting for ComfyUI API..."

max_wait=60
wait_count=0

while [ $wait_count -lt $max_wait ]; do

    if ! kill -0 $COMFY_PID 2>/dev/null; then
        echo "[FAIL] ComfyUI died during startup"
        exit 4
    fi

    if curl -s http://127.0.0.1:8188/ > /dev/null 2>&1; then
        echo "[OK] ComfyUI is ready"
        break
    fi

    echo "[WAIT] ${wait_count}s / ${max_wait}s"
    sleep 2
    wait_count=$((wait_count + 2))
done

if [ $wait_count -ge $max_wait ]; then
    echo "[FAIL] Timeout waiting for ComfyUI"
    kill -9 $COMFY_PID
    exit 5
fi

########################################
# 6. START HANDLER
########################################
echo "[START] Handler..."

exec python handler.py