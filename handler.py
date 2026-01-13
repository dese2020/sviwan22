
import runpod
from runpod.serverless.utils import rp_upload
import os
import websocket
import base64
import json
import uuid
import logging
import urllib.request
import urllib.parse
import binascii  # Para manejo de errores Base64
import subprocess
import time

# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# Config
# ------------------------------------------------------------
server_address = os.getenv('SERVER_ADDRESS', '127.0.0.1')
client_id = str(uuid.uuid4())

# Ruta del workflow SVI ProSame (mantiene el espacio en el nombre)
WORKFLOW_SVI_PROSAME = os.path.join("workflow", "SVI ProSame_api.json")

# Negativo por defecto seguro (sin términos sensibles)
SAFE_NEGATIVE_PROMPT = (
    "overexposed, static, motion blur, artifacts, subtitles, style drift, worst quality, "
    "low quality, jpeg artifacts, ugly, incomplete, extra fingers, poorly drawn hands, "
    "poorly drawn faces, deformed, disfigured, fused fingers, messy background"
)

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------
def to_nearest_multiple_of_16(value):
    """
    Redondea al múltiplo de 16 más cercano. Mínimo 16.
    """
    try:
        numeric_value = float(value)
    except Exception:
        raise Exception(f"width/height debe ser numérico: {value}")
    adjusted = int(round(numeric_value / 16.0) * 16)
    if adjusted < 16:
        adjusted = 16
    return adjusted


def process_input(input_data, temp_dir, output_filename, input_type):
    """
    Procesa entradas (path/url/base64) y devuelve ruta local al archivo.
    """
    if input_type == "path":
        logger.info(f"📁 Entrada por ruta: {input_data}")
        return input_data
    elif input_type == "url":
        logger.info(f"🌐 Entrada por URL: {input_data}")
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.abspath(os.path.join(temp_dir, output_filename))
        return download_file_from_url(input_data, file_path)
    elif input_type == "base64":
        logger.info("🔢 Entrada en Base64")
        return save_base64_to_file(input_data, temp_dir, output_filename)
    else:
        raise Exception(f"Tipo de entrada no soportado: {input_type}")


def download_file_from_url(url, output_path):
    """Descarga un archivo desde URL usando wget."""
    try:
        result = subprocess.run(
            ['wget', '-O', output_path, '--no-verbose', url],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            logger.info(f"✅ Descarga exitosa: {url} -> {output_path}")
            return output_path
        else:
            logger.error(f"❌ Error wget: {result.stderr}")
            raise Exception(f"Fallo al descargar URL: {result.stderr}")
    except subprocess.TimeoutExpired:
        logger.error("❌ Descarga: tiempo excedido")
        raise Exception("Descarga: tiempo excedido")
    except Exception as e:
        logger.error(f"❌ Error en descarga: {e}")
        raise Exception(f"Error en descarga: {e}")


def save_base64_to_file(base64_data, temp_dir, output_filename):
    """Guarda datos Base64 en archivo."""
    try:
        decoded_data = base64.b64decode(base64_data)
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.abspath(os.path.join(temp_dir, output_filename))
        with open(file_path, 'wb') as f:
            f.write(decoded_data)
        logger.info(f"✅ Base64 guardado en '{file_path}'.")
        return file_path
    except (binascii.Error, ValueError) as e:
        logger.error(f"❌ Base64 decode falló: {e}")
        raise Exception(f"Base64 decode falló: {e}")


# ------------------------------------------------------------
# ComfyUI helpers
# ------------------------------------------------------------
def queue_prompt(prompt):
    url = f"http://{server_address}:8188/prompt"
    logger.info(f"Queueing prompt to: {url}")
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    return json.loads(urllib.request.urlopen(req).read())


def get_image(filename, subfolder, folder_type):
    """
    Descarga bytes de un artefacto (imagen o video) expuesto por /view.
    folder_type suele ser 'output' para salidas.
    """
    url = f"http://{server_address}:8188/view"
    logger.info(f"Getting artifact from: {url}")
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen(f"{url}?{url_values}") as response:
        return response.read()


def get_history(prompt_id):
    url = f"http://{server_address}:8188/history/{prompt_id}"
    logger.info(f"Getting history from: {url}")
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read())


def get_videos(ws, prompt):
    """
    Envía el prompt por WebSocket y recolecta salidas en historia.
    Ahora soporta 'gifs' y 'videos' (VHS_VideoCombine).
    """
    prompt_id = queue_prompt(prompt)['prompt_id']
    output_videos = {}

    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            if message['type'] == 'executing':
                data = message['data']
                if data['node'] is None and data['prompt_id'] == prompt_id:
                    break
        else:
            continue

    history = get_history(prompt_id)[prompt_id]
    for node_id in history['outputs']:
        node_output = history['outputs'][node_id]
        videos_output = []

        # GIFs escritos a disco (fullpath)
        if 'gifs' in node_output:
            for video in node_output['gifs']:
                with open(video['fullpath'], 'rb') as f:
                    video_data = base64.b64encode(f.read()).decode('utf-8')
                videos_output.append(video_data)

        # Videos expuestos vía /view
        if 'videos' in node_output:
            for v in node_output['videos']:
                bytes_data = get_image(
                    v.get('filename', ''),
                    v.get('subfolder', ''),
                    v.get('type', 'output')
                )
                video_data = base64.b64encode(bytes_data).decode('utf-8')
                videos_output.append(video_data)

        if videos_output:
            output_videos[node_id] = videos_output

    return output_videos


def load_workflow(workflow_path):
    """Carga un archivo de workflow JSON."""
    if not os.path.isabs(workflow_path):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        workflow_path = os.path.join(current_dir, workflow_path)
    with open(workflow_path, 'r', encoding='utf-8') as file:
        return json.load(file)


def get_next_available_node_id(prompt, start_id=1000):
    """Busca el siguiente node_id disponible (no usado) como string."""
    node_id = start_id
    while str(node_id) in prompt:
        node_id += 1
    return str(node_id)


def count_user_loras(lora_pairs):
    """
    Cuenta LoRAs del usuario excluyendo 'lightx2v_4steps_lora'.
    """
    if not lora_pairs:
        return 0
    count = 0
    for lora_pair in lora_pairs:
        high = lora_pair.get("high", "")
        low = lora_pair.get("low", "")
        if high and "lightx2v_4steps_lora" not in high:
            count += 1
        elif low and "lightx2v_4steps_lora" not in low:
            count += 1
        elif high and low and "lightx2v_4steps_lora" not in high and "lightx2v_4steps_lora" not in low:
            count += 1
    return count


def filter_user_loras(lora_pairs):
    """
    Devuelve solo LoRAs de usuario (excluye 'lightx2v_4steps_lora').
    """
    if not lora_pairs:
        return []
    filtered = []
    for lora_pair in lora_pairs:
        high = lora_pair.get("high", "")
        low = lora_pair.get("low", "")
        if high and "lightx2v_4steps_lora" in high:
            continue
        if low and "lightx2v_4steps_lora" in low:
            continue
        filtered.append(lora_pair)
    return filtered


def apply_loras_to_workflow(prompt, lora_pairs, is_flf2v, workflow_file):
    """
    Aplica LoRAs a workflows 'wan22_*' actualizando 'lora_name' y 'strength_model'
    en los nodos mapeados. No se usa para el workflow SVI ProSame.
    """
    if not lora_pairs:
        return

    lora_node_mapping = {
        "workflow/wan22_nolora.json": {
            "high": [],
            "low": []
        },
        "workflow/wan22_1lora.json": {
            "high": ["282"],
            "low": ["336"]
        },
        "workflow/wan22_2lora.json": {
            "high": ["282", "339"],
            "low": ["336", "285"]
        },
        "workflow/wan22_3lora.json": {
            "high": ["282", "339", "340"],
            "low": ["336", "285", "286"]
        },
        "workflow/wan22_4lora.json": {
            "high": ["282", "339", "340", "341"],
            "low": ["336", "285", "286", "337"]
        },
        "workflow/wan22_flf2v.json": {
            "high": [],
            "low": []
        }
    }

    workflow_key = None
    for key in lora_node_mapping.keys():
        if key in workflow_file:
            workflow_key = key
            break
    if workflow_key is None:
        logger.warning(f"No se encontró mapeo LoRA para {workflow_file}.")
        return

    high_user_nodes = lora_node_mapping[workflow_key]["high"]
    low_user_nodes = lora_node_mapping[workflow_key]["low"]
    logger.info(f"Workflow: {workflow_key}")
    logger.info(f"Nodos HIGH LoRA: {high_user_nodes}")
    logger.info(f"Nodos LOW LoRA: {low_user_nodes}")

    if len(high_user_nodes) < len(lora_pairs) or len(low_user_nodes) < len(lora_pairs):
        logger.warning(
            "Nodos para LoRA insuficientes. "
            f"Necesario HIGH={len(lora_pairs)}, LOW={len(lora_pairs)}; "
            f"hallado HIGH={len(high_user_nodes)}, LOW={len(low_user_nodes)}"
        )
        return

    for i, lora_pair in enumerate(lora_pairs):
        if i < len(high_user_nodes) and lora_pair.get("high"):
            high_node_id = high_user_nodes[i]
            prompt[high_node_id]["inputs"]["lora_name"] = lora_pair["high"]
            prompt[high_node_id]["inputs"]["strength_model"] = lora_pair.get("high_weight", 1.0)
            logger.info(
                f"✅ HIGH LoRA {i+1}: {lora_pair['high']} "
                f"(w={lora_pair.get('high_weight', 1.0)}) -> nodo {high_node_id}"
            )
        if i < len(low_user_nodes) and lora_pair.get("low"):
            low_node_id = low_user_nodes[i]
            prompt[low_node_id]["inputs"]["lora_name"] = lora_pair["low"]
            prompt[low_node_id]["inputs"]["strength_model"] = lora_pair.get("low_weight", 1.0)
            logger.info(
                f"✅ LOW LoRA  {i+1}: {lora_pair['low']} "
                f"(w={lora_pair.get('low_weight', 1.0)}) -> nodo {low_node_id}"
            )


# ------------------------------------------------------------
# Handler
# ------------------------------------------------------------
def handler(job):
    job_input = job.get("input", {})
    logger.info(f"Received job input: {job_input}")
    task_id = f"task_{uuid.uuid4()}"

    # --------------------------------------------------------
    # Imagen de entrada: soporta image / image_path / image_url / image_base64
    # --------------------------------------------------------
    image_path = None
    if "image" in job_input:
        image_data = job_input["image"]
        if isinstance(image_data, str):
            if image_data.startswith("http://") or image_data.startswith("https://"):
                image_path = process_input(image_data, task_id, "input_image.jpg", "url")
            elif os.path.exists(image_data) or image_data.startswith("/"):
                image_path = process_input(image_data, task_id, "input_image.jpg", "path")
            else:
                image_path = process_input(image_data, task_id, "input_image.jpg", "base64")
        else:
            raise Exception("El parámetro 'image' debe ser string (url, path o base64).")
    elif "image_path" in job_input:
        image_path = process_input(job_input["image_path"], task_id, "input_image.jpg", "path")
    elif "image_url" in job_input:
        image_path = process_input(job_input["image_url"], task_id, "input_image.jpg", "url")
    elif "image_base64" in job_input:
        image_path = process_input(job_input["image_base64"], task_id, "input_image.jpg", "base64")
    else:
        image_path = "/example_image.png"
        logger.info("Usando imagen por defecto: /example_image.png")

    # --------------------------------------------------------
    # End image (para FLF2V) - opcional
    # --------------------------------------------------------
    end_image_path_local = None
    if "end_image" in job_input:
        end_image_data = job_input["end_image"]
        if isinstance(end_image_data, str):
            if end_image_data.startswith("http://") or end_image_data.startswith("https://"):
                end_image_path_local = process_input(end_image_data, task_id, "end_image.jpg", "url")
            elif os.path.exists(end_image_data) or end_image_data.startswith("/"):
                end_image_path_local = process_input(end_image_data, task_id, "end_image.jpg", "path")
            else:
                end_image_path_local = process_input(end_image_data, task_id, "end_image.jpg", "base64")
        else:
            raise Exception("El parámetro 'end_image' debe ser string.")
    elif "end_image_path" in job_input:
        end_image_path_local = process_input(job_input["end_image_path"], task_id, "end_image.jpg", "path")
    elif "end_image_url" in job_input:
        end_image_path_local = process_input(job_input["end_image_url"], task_id, "end_image.jpg", "url")
    elif "end_image_base64" in job_input:
        end_image_path_local = process_input(job_input["end_image_base64"], task_id, "end_image.jpg", "base64")

    # ¿Usamos FLF2V?
    is_flf2v = end_image_path_local is not None

    # --------------------------------------------------------
    # LoRAs de entrada (para workflows wan22_*)
    # --------------------------------------------------------
    lora_pairs = job_input.get("lora_pairs", [])
    user_lora_pairs = filter_user_loras(lora_pairs)
    lora_count = count_user_loras(lora_pairs)
    logger.info(f"LoRAs de usuario (excluyendo 'lightx2v'): {lora_count}")

    # --------------------------------------------------------
    # Parámetros comunes
    # --------------------------------------------------------
    length = job_input.get("length", 81)
    original_width = job_input.get("width", 480)
    original_height = job_input.get("height", 720)
    adjusted_width = to_nearest_multiple_of_16(original_width)
    adjusted_height = to_nearest_multiple_of_16(original_height)
    if adjusted_width != original_width:
        logger.info(f"Width ajustado a múltiplo de 16: {original_width} -> {adjusted_width}")
    if adjusted_height != original_height:
        logger.info(f"Height ajustado a múltiplo de 16: {original_height} -> {adjusted_height}")

    # --------------------------------------------------------
    # Selección de workflow
    # --------------------------------------------------------
    use_svi_prosame = str(job_input.get("workflow", "")).lower() in {"svi_prosame", "svi", "prosame"} \
                      or bool(job_input.get("use_svi_prosame", False))

    if use_svi_prosame:
        workflow_file = WORKFLOW_SVI_PROSAME
        logger.info(f"Using SVI ProSame workflow: {workflow_file}")
    else:
        if is_flf2v:
            workflow_file = "workflow/wan22_flf2v.json"
            logger.info(f"Using FLF2V workflow: {workflow_file}")
        else:
            if lora_count == 0:
                workflow_file = "workflow/wan22_nolora.json"
            elif lora_count == 1:
                workflow_file = "workflow/wan22_1lora.json"
            elif lora_count == 2:
                workflow_file = "workflow/wan22_2lora.json"
            elif lora_count == 3:
                workflow_file = "workflow/wan22_3lora.json"
            elif lora_count >= 4:
                workflow_file = "workflow/wan22_4lora.json"
                if lora_count > 4:
                    logger.warning(
                        f"Se recibieron {lora_count} LoRAs; se soportan hasta 4. "
                        "Usaré solo las primeras 4."
                    )
                    user_lora_pairs = user_lora_pairs[:4]
            else:
                workflow_file = "workflow/wan22_nolora.json"
            logger.info(f"Using single image workflow: {workflow_file} (LoRAs: {lora_count})")

    # --------------------------------------------------------
    # Cargar workflow
    # --------------------------------------------------------
    prompt = load_workflow(workflow_file)

    # --------------------------------------------------------
    # Asignación de nodos según workflow
    # --------------------------------------------------------
    if use_svi_prosame:
        # ========== Mapeo SVI ProSame ==========
        # Imagen de entrada -> LoadImage (id 67)
        if "67" in prompt and "inputs" in prompt["67"]:
            prompt["67"]["inputs"]["image"] = image_path

        # Resize -> ImageResizeKJv2 (id 68)
        if "68" in prompt and "inputs" in prompt["68"]:
            prompt["68"]["inputs"]["width"] = adjusted_width
            prompt["68"]["inputs"]["height"] = adjusted_height

        # Frames -> INTConstant (ids 780, 781, 782)
        for frames_id in ("780", "781", "782"):
            if frames_id in prompt and "inputs" in prompt[frames_id]:
                prompt[frames_id]["inputs"]["value"] = length

        # Prompts -> WanVideoTextEncode (ids 388, 464, 688)
        safe_positive = job_input.get("prompt", "") or ""
        safe_negative = job_input.get("negative_prompt", "") or SAFE_NEGATIVE_PROMPT
        for text_id in ("388", "464", "688"):
            if text_id in prompt and "inputs" in prompt[text_id]:
                prompt[text_id]["inputs"]["positive_prompt"] = safe_positive
                prompt[text_id]["inputs"]["negative_prompt"] = safe_negative

        # LoRA opcional para SVI: selectores múltiples (381=HIGH, 382=LOW)
        high_lora = job_input.get("high_lora_name")
        low_lora = job_input.get("low_lora_name")
        high_w = float(job_input.get("high_lora_strength", 1.0))
        low_w = float(job_input.get("low_lora_strength", 1.0))
        if high_lora and "381" in prompt:
            prompt["381"]["inputs"]["lora_1"] = high_lora
            prompt["381"]["inputs"]["strength_1"] = high_w
        if low_lora and "382" in prompt:
            prompt["382"]["inputs"]["lora_1"] = low_lora
            prompt["382"]["inputs"]["strength_1"] = low_w

        # (No aplicamos apply_loras_to_workflow en SVI ProSame)
    else:
        # ========== Mapeo para workflows wan22_* ==========
        # Imagen
        if "260" in prompt and "inputs" in prompt["260"]:
            prompt["260"]["inputs"]["image"] = image_path

        # Prompt positivo
        if "246" in prompt and "inputs" in prompt["246"]:
            prompt["246"]["inputs"]["value"] = job_input.get("prompt", "")

        # Prompt negativo (seguro por defecto)
        negative_prompt = job_input.get("negative_prompt", SAFE_NEGATIVE_PROMPT)
        if "247" in prompt and "inputs" in prompt["247"]:
            prompt["247"]["inputs"]["value"] = negative_prompt

        # Dimensiones
        if "849" in prompt and "inputs" in prompt["849"]:
            prompt["849"]["inputs"]["value"] = adjusted_width
        if "848" in prompt and "inputs" in prompt["848"]:
            prompt["848"]["inputs"]["value"] = adjusted_height

        # Frames
        if "846" in prompt and "inputs" in prompt["846"]:
            prompt["846"]["inputs"]["value"] = length

        # End image (solo FLF2V)
        if is_flf2v and "483" in prompt and "inputs" in prompt["483"]:
            prompt["483"]["inputs"]["image"] = end_image_path_local

        # LoRAs (wan22_*)
        if user_lora_pairs:
            apply_loras_to_workflow(prompt, user_lora_pairs, is_flf2v, workflow_file)

    # --------------------------------------------------------
    # Conexión y ejecución
    # --------------------------------------------------------
    ws_url = f"ws://{server_address}:8188/ws?clientId={client_id}"
    logger.info(f"Connecting to WebSocket: {ws_url}")

    # Comprobación previa de HTTP (hasta 3 min)
    http_url = f"http://{server_address}:8188/"
    logger.info(f"Checking HTTP connection to: {http_url}")
    max_http_attempts = 180  # ~3 minutos (1s entre intentos)
    for http_attempt in range(max_http_attempts):
        try:
            urllib.request.urlopen(http_url, timeout=5)
            logger.info(f"HTTP OK (intento {http_attempt+1})")
            break
        except Exception as e:
            logger.warning(f"HTTP fallo ({http_attempt+1}/{max_http_attempts}): {e}")
            if http_attempt == max_http_attempts - 1:
                raise Exception("No es posible conectar con ComfyUI. Verifica que el servidor esté activo.")
            time.sleep(1)

    ws = websocket.WebSocket()
    max_attempts = int(180 / 5)  # ~3 minutos, un intento cada 5s
    for attempt in range(max_attempts):
        try:
            ws.connect(ws_url)
            logger.info(f"WebSocket conectado (intento {attempt+1})")
            break
        except Exception as e:
            logger.warning(f"WebSocket fallo ({attempt+1}/{max_attempts}): {e}")
            if attempt == max_attempts - 1:
                raise Exception("Tiempo de conexión WebSocket excedido (~3 min).")
            time.sleep(5)

    videos = get_videos(ws, prompt)
    ws.close()

    # Devuelve el primer video encontrado (Base64)
    for node_id in videos:
        if videos[node_id]:
            return {"video": videos[node_id][0]}

    return {"error": "No se encontró video en la salida."}


# Iniciar servidor Runpod
runpod.serverless.start({"handler": handler})
