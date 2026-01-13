
#!/usr/bin/env bash
set -euo pipefail

# =========================
# Config por variables de entorno
# =========================
RUN_MODE="${RUN_MODE:-pod}"                 # 'serverless' | 'pod' (default)
COMFY_HOST="${COMFY_HOST:-0.0.0.0}"         # 0.0.0.0 para exponer dentro del pod
COMFY_PORT="${COMFY_PORT:-8188}"            # puerto de ComfyUI
COMFY_ARGS="${COMFY_ARGS:---use-sage-attention}"  # flags extra para ComfyUI
COMFY_MAX_WAIT="${COMFY_MAX_WAIT:-600}"     # tiempo máximo de espera (s) para ready

echo "===================================================="
echo " Entrypoint híbrido - RUN_MODE=${RUN_MODE}"
echo "===================================================="

if [[ "${RUN_MODE}" == "serverless" ]]; then
  # ------------------------------------------------------
  # MODO SERVERLESS: ejecuta tu handler como proceso principal
  # ------------------------------------------------------
  echo "[serverless] Iniciando handler.py en foreground..."
  # Ajusta la ruta si tu handler está en otra carpeta:
  exec python /workspace/handler.py

else
  # ------------------------------------------------------
  # MODO POD: arranca ComfyUI y mantiene el contenedor vivo
  # ------------------------------------------------------
  echo "[pod] Iniciando ComfyUI..."
  python /ComfyUI/main.py --listen "${COMFY_HOST}" --port "${COMFY_PORT}" ${COMFY_ARGS} --no-auto-launch &

  COMFY_PID=$!
  echo "[pod] ComfyUI PID: ${COMFY_PID}"
  echo "[pod] Esperando a que ComfyUI quede ready en http://127.0.0.1:${COMFY_PORT}/ ... (max ${COMFY_MAX_WAIT}s)"

  # Health-wait: no salir si está ready; opcionalmente fallar si no está ready
  READY=0
  for i in $(seq 1 "${COMFY_MAX_WAIT}"); do
    if curl -fsS "http://127.0.0.1:${COMFY_PORT}/" >/dev/null; then
      echo "✅ ComfyUI is ready in ${i}s."
      READY=1
      break
    fi
    if (( i % 30 == 0 )); then
      echo "⏳ still waiting... (${i}/${COMFY_MAX_WAIT})"
    fi
    sleep 1
  done

  if [[ "${READY}" -eq 0 ]]; then
    echo "⚠️  Timeout: ComfyUI no respondió dentro de ${COMFY_MAX_WAIT}s."
    echo "🔎 Diagnóstico rápido:"
    ss -ltnp || true
    ps aux | grep -i comf[y] || true
    # Si deseas que el pod falle cuando ComfyUI no arranca, descomenta:
    # exit 1
  fi

  # -------------------------------
  # (Opcional) arrancar handler en background también en pod
  # -------------------------------
  if [[ "${START_HANDLER_IN_POD:-false}" == "true" ]]; then
    echo "[pod] Iniciando handler.py en background..."
    python /workspace/handler.py &
    HANDLER_PID=$!
    echo "[pod] handler.py PID: ${HANDLER_PID}"
  fi

  echo "[pod] El contenedor se mantendrá vivo mientras ComfyUI esté ejecutándose."
  # Bloquear hasta que ComfyUI termine (proceso principal del contenedor)
  wait "${COMFY_PID}"
fi
``
