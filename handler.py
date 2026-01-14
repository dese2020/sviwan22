
import runpod
from runpod.serverless.utils import rp_upload  # opcional
import os
import websocket
import base64
import json
import uuid
import logging
import urllib.request
import urllib.parse
import binascii
import subprocess
import time

# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# ComfyUI server address (env or default)
# ------------------------------------------------------------
server_address = os.getenv('SERVER_ADDRESS', '127.0.0.1')
client_id = str(uuid.uuid4())

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def to_nearest_multiple_of_16(value):
    """Corrige a múltiplo de 16 (mínimo 16)."""
    try:
        numeric_value = float(value)
    except Exception:
        raise Exception(f"width/height deben ser numéricos: {value}")
    adjusted = int(round(numeric_value / 16.0) * 16)
    return max(adjusted, 16)

def process_input(input_data, temp_dir, output_filename, input_type):
    """Normaliza una imagen de entrada a un fichero local y retorna su ruta."""
    if input_type == "path":
        logger.info(f"📁 Usando ruta local: {input_data}")
        return input_data
    elif input_type == "url":
        logger.info(f"🌐 Descargando URL: {input_data}")
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.abspath(os.path.join(temp_dir, output_filename))
        return download_file_from_url(input_data, file_path)
    elif input_type == "base64":
        logger.info("🔡 Decodificando Base64…")
        return save_base64_to_file(input_data, temp_dir, output_filename)
    else:
        raise Exception(f"input_type no soportado: {input_type}")

def download_file_from_url(url, output_path):
    try:
        result = subprocess.run(
            ['wget', '-O', output_path, '--no-verbose', url],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            logger.info(f"✅ Descargado: {url} → {output_path}")
            return output_path
        logger.error(f"❌ wget falló: {result.stderr}")
        raise Exception(f"URL download failed: {result.stderr}")
    except subprocess.TimeoutExpired:
        logger.error("❌ Timeout de descarga")
        raise Exception("Timeout de descarga")
    except Exception as e:
        logger.error(f"❌ Error de descarga: {e}")
        raise Exception(f"Error de descarga: {e}")

def save_base64_to_file(b64, temp_dir, output_filename):
    try:
        decoded = base64.b64decode(b64)
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.abspath(os.path.join(temp_dir, output_filename))
        with open(file_path, 'wb') as f:
            f.write(decoded)
        logger.info(f"✅ Base64 guardado en {file_path}")
        return file_path
    except (binascii.Error, ValueError) as e:
        logger.error(f"❌ Base64 inválido: {e}")
        raise Exception(f"Base64 inválido: {e}")

def queue_prompt(prompt):
    url = f"http://{server_address}:8188/prompt"
    logger.info(f"POST {url}")
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    return json.loads(urllib.request.urlopen(req).read())

def get_view_file(filename, subfolder, folder_type):
    """LEE un archivo del /view (fallback cuando no hay fullpath)."""
    url = f"http://{server_address}:8188/view"
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen(f"{url}?{url_values}") as response:
        return response.read()

def get_history(prompt_id):
    url = f"http://{server_address}:8188/history/{prompt_id}"
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read())

def get_media(ws, prompt):
    """Envía el prompt y devuelve los outputs (video priorizado)."""
    prompt_id = queue_prompt(prompt)['prompt_id']
    outputs = {}

    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            if message.get('type') == 'executing':
                data = message.get('data', {})
                if data.get('node') is None and data.get('prompt_id') == prompt_id:
                    break
            continue

    history = get_history(prompt_id)[prompt_id]
    for node_id, node_out in history.get('outputs', {}).items():
        media_list = []

        # Prioridad: videos, gifs, files, images
        for key in ['videos', 'gifs', 'files', 'images']:
            if key in node_out:
                for item in node_out[key]:
                    if 'fullpath' in item and item['fullpath'] and os.path.isfile(item['fullpath']):
                        with open(item['fullpath'], 'rb') as f:
                            media_list.append(base64.b64encode(f.read()).decode('utf-8'))
                    else:
                        try:
                            blob = get_view_file(
                                item.get('filename'), item.get('subfolder'), item.get('type')
                            )
                            media_list.append(base64.b64encode(blob).decode('utf-8'))
                        except Exception as e:
                            logger.warning(f"Fallback /view falló: {e}")
                if media_list:
                    outputs[node_id] = media_list
                    break

    return outputs

def load_workflow(workflow_path):
    with open(workflow_path, 'r') as f:
        return json.load(f)

# ------------------------------------------------------------
# Mapa de nodos del workflow SVI_extension_api.json (nuevo)
# ------------------------------------------------------------
NODES = {
    # Entrada y parámetros
    "LOAD_IMAGE": "10",
    "WIDTH": "159",             # PrimitiveInt: value
    "HEIGHT": "160",            # PrimitiveInt: value
    "FRAMES_PER_SECTION": "259",# easy int / Primitive: value
    "FPS": "262",               # PrimitiveInt: value

    # Prompts positivos (4 secciones)
    "P_POS_1": "21",
    "P_POS_2": "464",
    "P_POS_3": "469",
    "P_POS_4": "501",

    # Prompts negativos (4 secciones)
    "P_NEG_1": "1",
    "P_NEG_2": "465",
    "P_NEG_3": "471",
    "P_NEG_4": "502",

    # Video Combine (MP4)
    "VIDEO_COMBINE": "444",

    # --- LoRAs (últimos 2 por rama) ---
    # HIGH chain: ... -> 512 -> 515 -> ModelSamplingSD3(60)
    "LORA_HIGH_LAST_1": "512",
    "LORA_HIGH_LAST_2": "515",

    # LOW chain:  ... -> 513 -> 514 -> ModelSamplingSD3(402)
    "LORA_LOW_LAST_1": "513",
    "LORA_LOW_LAST_2": "514",
}

def apply_core_params(prompt_graph, args):
    """Inyecta imagen, tamaño, fps, frames y prompts en el grafo."""
    # Imagen
    prompt_graph[NODES["LOAD_IMAGE"]]["inputs"]["image"] = args["image_path"]

    # Dimensiones
    w = to_nearest_multiple_of_16(args.get("width", 480))
    h = to_nearest_multiple_of_16(args.get("height", 832))
    prompt_graph[NODES["WIDTH"]]["inputs"]["value"] = int(w)
    prompt_graph[NODES["HEIGHT"]]["inputs"]["value"] = int(h)

    # FPS y frames/section
    fps = int(args.get("fps", 16))
    frames = int(args.get("frames_per_section", 81))
    prompt_graph[NODES["FPS"]]["inputs"]["value"] = fps
    prompt_graph[NODES["FRAMES_PER_SECTION"]]["inputs"]["value"] = frames

    # Prompts
    p_list = args.get("prompts", None)
    if p_list and isinstance(p_list, list) and len(p_list) > 0:
        p1 = p_list[0]
        p2 = p_list[1] if len(p_list) > 1 else p1
        p3 = p_list[2] if len(p_list) > 2 else p1
        p4 = p_list[3] if len(p_list) > 3 else p1
    else:
        p = args.get("prompt", "A cinematic realistic video, natural motion, detailed lighting and composition")
        p1 = p2 = p3 = p4 = p

    neg = args.get("negative_prompt",
                   "bright tones, overexposed, static, blurred details, subtitles, worst quality, low quality, jpeg artifacts, ugly, extra fingers, bad hands, bad face, deformed, disfigured, fused fingers, messy background")

    prompt_graph[NODES["P_POS_1"]]["inputs"]["text"] = p1
    prompt_graph[NODES["P_POS_2"]]["inputs"]["text"] = p2
    prompt_graph[NODES["P_POS_3"]]["inputs"]["text"] = p3
    prompt_graph[NODES["P_POS__4"]]["inputs"]["text"] = p4

    prompt_graph[NODES["P_NEG_1"]]["inputs"]["text"] = neg
    prompt_graph[NODES["P_NEG_2"]]["inputs"]["text"] = neg
    prompt_graph[NODES["P_NEG_3"]]["inputs"]["text"] = neg
    prompt_graph[NODES["P_NEG_4"]]["inputs"]["text"] = neg

    # Guardado MP4 (tu nodo 444 ya está en save_output=true; dejamos por si quieres cambiar CRF)
    vc_inputs = prompt_graph[NODES["VIDEO_COMBINE"]]["inputs"]
    vc_inputs["frame_rate"] = fps
    if "crf" in args:
        vc_inputs["crf"] = int(args["crf"])

    return prompt_graph

def set_lora_inputs(node_obj, name=None, strength=None):
    """Escribe lora_name / strength_model si vienen en el payload."""
    if name is not None:
        node_obj["inputs"]["lora_name"] = name
    if strength is not None:
        node_obj["inputs"]["strength_model"] = float(strength)

def apply_last_two_loras(prompt_graph, loras):
    """
    loras = {
      "high": [
        {"name": "...", "strength": 1.0},  # → NODES["LORA_HIGH_LAST_1"] (512)
        {"name": "...", "strength": 1.0}   # → NODES["LORA_HIGH_LAST_2"] (515)
      ],
      "low": [
        {"name": "...", "strength": 1.0},  # → NODES["LORA_LOW_LAST_1"] (513)
        {"name": "...", "strength": 1.0}   # → NODES["LORA_LOW_LAST_2"] (514)
      ]
    }
    Solo se aplican los que vengan; los anteriores (lightx2v, SVI) NO se tocan.
    """
    if not isinstance(loras, dict):
        return prompt_graph

    # HIGH
    high = loras.get("high")
    if isinstance(high, list) and len(high) > 0:
        # slot 1 → 512
        slot1 = high[0] if len(high) >= 1 else None
        if isinstance(slot1, dict):
            set_lora_inputs(prompt_graph[NODES["LORA_HIGH_LAST_1"]],
                            name=slot1.get("name"),
                            strength=slot1.get("strength"))
        # slot 2 → 515
        slot2 = high[1] if len(high) >= 2 else None
        if isinstance(slot2, dict):
            set_lora_inputs(prompt_graph[NODES["LORA_HIGH_LAST_2"]],
                            name=slot2.get("name"),
                            strength=slot2.get("strength"))

    # LOW
    low = loras.get("low")
    if isinstance(low, list) and len(low) > 0:
        # slot 1 → 513
        slot1 = low[0] if len(low) >= 1 else None
        if isinstance(slot1, dict):
            set_lora_inputs(prompt_graph[NODES["LORA_LOW_LAST_1"]],
                            name=slot1.get("name"),
                            strength=slot1.get("strength"))
        # slot 2 → 514
        slot2 = low[1] if len(low) >= 2 else None
        if isinstance(slot2, dict):
            set_lora_inputs(prompt_graph[NODES["LORA_LOW_LAST_2"]],
                            name=slot2.get("name"),
                            strength=slot2.get("strength"))

    return prompt_graph

# ------------------------------------------------------------
# Handler principal
# ------------------------------------------------------------
def handler(job):
    job_input = job.get("input", {})
    logger.info(f"Job input: {job_input}")
    task_id = f"task_{uuid.uuid4()}"

    # 1) Normalizar imagen de entrada
    image_path = None
    if "image_path" in job_input:
        image_path = process_input(job_input["image_path"], task_id, "input_image.jpg", "path")
    elif "image_url" in job_input:
        image_path = process_input(job_input["image_url"], task_id, "input_image.jpg", "url")
    elif "image_base64" in job_input:
        image_path = process_input(job_input["image_base64"], task_id, "input_image.jpg", "base64")
    else:
        image_path = "/example.png"
        logger.info("Usando imagen por defecto /example.png")

    # 2) Cargar workflow y aplicar parámetros
    workflow_path = job_input.get("workflow_path", "SVI_extension_api.json")
    prompt_graph = load_workflow(workflow_path)

    args = {
        "image_path": image_path,
        "width": job_input.get("width", 480),
        "height": job_input.get("height", 832),
        "fps": job_input.get("fps", 16),
        "frames_per_section": job_input.get("frames_per_section", 81),
        "prompt": job_input.get("prompt"),
        "prompts": job_input.get("prompts"),  # lista opcional de 1–4
        "negative_prompt": job_input.get("negative_prompt"),
        "crf": job_input.get("crf"),
    }
    prompt_graph = apply_core_params(prompt_graph, args)

    # 3) Aplicar SOLO los últimos 2 LoRAs por rama (si vienen)
    loras = job_input.get("loras", None)
    if loras:
        prompt_graph = apply_last_two_loras(prompt_graph, loras)

    # 4) Esperar ComfyUI y abrir WebSocket
    http_url = f"http://{server_address}:8188/"
    logger.info(f"Ping a ComfyUI: {http_url}")

    max_http_attempts = 180
    for i in range(max_http_attempts):
        try:
            urllib.request.urlopen(http_url, timeout=5)
            logger.info(f"ComfyUI OK (intento {i+1})")
            break
        except Exception:
            if i == max_http_attempts - 1:
                raise Exception("No se pudo conectar a ComfyUI (HTTP).")
            time.sleep(1)

    ws_url = f"ws://{server_address}:8188/ws?clientId={client_id}"
    logger.info(f"Conectando WS: {ws_url}")
    ws = websocket.WebSocket()

    max_ws_attempts = int(180 / 5)
    for attempt in range(max_ws_attempts):
        try:
            ws.connect(ws_url)
            logger.info(f"WebSocket OK (intento {attempt+1})")
            break
        except Exception:
            if attempt == max_ws_attempts - 1:
                raise Exception("Timeout conectando WebSocket (3 min).")
            time.sleep(5)

    # 5) Ejecutar y recolectar outputs
    outputs = get_media(ws, prompt_graph)
    ws.close()

    for node_id, files in outputs.items():
        if files:
            return {
                "video": files[0],     # base64 del primer artefacto (MP4 esperado)
                "meta": {
                    "node_id": node_id,
                    "width": to_nearest_multiple_of_16(args["width"]),
                    "height": to_nearest_multiple_of_16(args["height"]),
                    "fps": int(args["fps"]),
                    "frames_per_section": int(args["frames_per_section"]),
                    "sections": 4
                }
            }

    return {"error": "No se encontró salida de video."}

# Inicia el worker de RunPod (modo asíncrono recomendado)
runpod.serverless.start({"handler": handler})
