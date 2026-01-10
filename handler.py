
import runpod
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

# -----------------------------------------------------------------------------
# Configuración de logging
# -----------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dirección del servidor ComfyUI (e.g. dentro del mismo pod)
server_address = os.getenv('SERVER_ADDRESS', '127.0.0.1')
client_id = str(uuid.uuid4())

# Ruta del workflow SVI Pro (ajusta si lo guardas en otro lugar)
SVI_WORKFLOW_PATH = "SVI Pro - Same_api.json"

# IDs relevantes dentro de tu JSON SVI Pro
NODE_ID_LOAD_IMAGE = "67"       # LoadImage
NODE_ID_RESIZE = "68"           # ImageResizeKJv2


# -----------------------------------------------------------------------------
# Utilidades
# -----------------------------------------------------------------------------
def to_nearest_multiple_of_16(value: float) -> int:
    """Ajusta value al múltiplo de 16 más cercano, mínimo 16."""
    try:
        numeric_value = float(value)
    except Exception:
        raise Exception(f"width/height debe ser numérico: {value}")
    adjusted = int(round(numeric_value / 16.0) * 16)
    return max(adjusted, 16)


def process_input(input_data, temp_dir, output_filename, input_type):
    """
    Normaliza entradas (path/url/base64) a un archivo local y devuelve su ruta.
    """
    if input_type == "path":
        logger.info(f"📁 Path de entrada: {input_data}")
        return input_data
    elif input_type == "url":
        logger.info(f"🌐 URL de entrada: {input_data}")
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.abspath(os.path.join(temp_dir, output_filename))
        return download_file_from_url(input_data, file_path)
    elif input_type == "base64":
        logger.info("🔢 Base64 de entrada")
        return save_base64_to_file(input_data, temp_dir, output_filename)
    else:
        raise Exception(f"Tipo de entrada no soportado: {input_type}")


def download_file_from_url(url, output_path):
    """Descarga un archivo vía wget a output_path."""
    try:
        result = subprocess.run(
            ['wget', '-O', output_path, '--no-verbose', url],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            logger.info(f"✅ Descargado: {url} -> {output_path}")
            return output_path
        else:
            logger.error(f"❌ Error wget: {result.stderr}")
            raise Exception(f"Fallo al descargar URL: {result.stderr}")
    except subprocess.TimeoutExpired:
        logger.error("❌ Descarga expirada")
        raise Exception("Descarga expirada")
    except Exception as e:
        logger.error(f"❌ Error descargando: {e}")
        raise Exception(f"Error descargando: {e}")


def save_base64_to_file(base64_data, temp_dir, output_filename):
    """Decodifica base64 y guarda en disco."""
    try:
        decoded_data = base64.b64decode(base64_data)
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.abspath(os.path.join(temp_dir, output_filename))
        with open(file_path, 'wb') as f:
            f.write(decoded_data)
        logger.info(f"✅ Base64 guardado en '{file_path}'.")
        return file_path
    except (binascii.Error, ValueError) as e:
        logger.error(f"❌ Fallo al decodificar base64: {e}")
        raise Exception(f"Fallo al decodificar base64: {e}")


def queue_prompt(prompt):
    url = f"http://{server_address}:8188/prompt"
    logger.info(f"Encolando prompt en: {url}")
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    return json.loads(urllib.request.urlopen(req).read())


def get_image(filename, subfolder, folder_type):
    url = f"http://{server_address}:8188/view"
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen(f"{url}?{url_values}") as response:
        return response.read()


def get_history(prompt_id):
    url = f"http://{server_address}:8188/history/{prompt_id}"
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read())


def get_outputs(ws, prompt):
    """
    Envía el prompt y espera a que termine la ejecución. Devuelve artefactos
    como base64 en: {'videos': [...], 'gifs': [...], 'images': [...]}
    """
    prompt_id = queue_prompt(prompt)['prompt_id']
    outputs = {"videos": [], "gifs": [], "images": []}

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
    for node_id, node_output in history.get('outputs', {}).items():
        for key in ('videos', 'gifs', 'images'):
            if key in node_output:
                for item in node_output[key]:
                    fullpath = item.get('fullpath') or item.get('filename')
                    if not fullpath:
                        # Fallback para 'images' con metadata tipo comfy
                        fn = item.get('filename')
                        sub = item.get('subfolder', '')
                        ftype = item.get('type', 'output')
                        try:
                            raw = get_image(fn, sub, ftype)
                            b64 = base64.b64encode(raw).decode('utf-8')
                            outputs[key].append(b64)
                        except Exception:
                            pass
                        continue
                    try:
                        with open(fullpath, 'rb') as f:
                            b64 = base64.b64encode(f.read()).decode('utf-8')
                            outputs[key].append(b64)
                    except Exception:
                        pass

    return outputs


def load_workflow(workflow_path):
    """
    Carga un archivo JSON de workflow. Acepta rutas relativas al archivo actual.
    """
    if not os.path.isabs(workflow_path):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        workflow_path = os.path.join(current_dir, workflow_path)
    if not os.path.exists(workflow_path):
        raise FileNotFoundError(f"No se encontró el workflow: {workflow_path}")
    with open(workflow_path, 'r', encoding='utf-8') as file:
        return json.load(file)


# -----------------------------------------------------------------------------
# Handler principal (SOLO SVI Pro)
# -----------------------------------------------------------------------------
def handler(job):
    job_input = job.get("input", {})
    logger.info(f"Received job input: {job_input}")
    task_id = f"task_{uuid.uuid4()}"

    # -------------------------------------------------------------------------
    # 1) Normalización de imagen (opcional)
    #    Acepta: image, image_path, image_url, image_base64
    # -------------------------------------------------------------------------
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
            raise Exception("El parámetro 'image' debe ser cadena (path/url/base64).")
    elif "image_path" in job_input:
        image_path = process_input(job_input["image_path"], task_id, "input_image.jpg", "path")
    elif "image_url" in job_input:
        image_path = process_input(job_input["image_url"], task_id, "input_image.jpg", "url")
    elif "image_base64" in job_input:
        image_path = process_input(job_input["image_base64"], task_id, "input_image.jpg", "base64")
    # Si no pasas imagen, se respeta lo que define el JSON del workflow.

    # -------------------------------------------------------------------------
    # 2) Cargar workflow SVI Pro
    # -------------------------------------------------------------------------
    prompt = load_workflow(SVI_WORKFLOW_PATH)

    # -------------------------------------------------------------------------
    # 3) Overrides mínimos y seguros (solo si el usuario los provee)
    #    - Inyectar imagen en nodo LoadImage (ID "67")
    #    - Ajustar width/height en nodo Resize (ID "68")
    #    No se toca el resto.
    # -------------------------------------------------------------------------
    try:
        if image_path is not None and NODE_ID_LOAD_IMAGE in prompt:
            prompt[NODE_ID_LOAD_IMAGE]["inputs"]["image"] = image_path
            logger.info(f"Imagen aplicada en nodo {NODE_ID_LOAD_IMAGE}: {image_path}")

        width = job_input.get("width")
        height = job_input.get("height")
        if (width is not None or height is not None) and NODE_ID_RESIZE in prompt:
            if width is not None:
                prompt[NODE_ID_RESIZE]["inputs"]["width"] = to_nearest_multiple_of_16(width)
            if height is not None:
                prompt[NODE_ID_RESIZE]["inputs"]["height"] = to_nearest_multiple_of_16(height)
            logger.info(f"Resize en nodo {NODE_ID_RESIZE}: width={prompt[NODE_ID_RESIZE]['inputs'].get('width')} height={prompt[NODE_ID_RESIZE]['inputs'].get('height')}")
    except Exception as e:
        logger.warning(f"No se pudieron aplicar overrides mínimos: {e}")

    # -------------------------------------------------------------------------
    # 4) Conexión a ComfyUI (HTTP + WebSocket)
    # -------------------------------------------------------------------------
    ws_url = f"ws://{server_address}:8188/ws?clientId={client_id}"
    http_url = f"http://{server_address}:8188/"
    logger.info(f"Comprobando HTTP: {http_url}")

    # Esperar hasta 3 minutos a que la UI esté arriba
    max_http_attempts = 180
    for http_attempt in range(max_http_attempts):
        try:
            urllib.request.urlopen(http_url, timeout=5)
            logger.info(f"HTTP OK (intento {http_attempt+1})")
            break
        except Exception as e:
            logger.warning(f"HTTP fallo (intento {http_attempt+1}/{max_http_attempts}): {e}")
            if http_attempt == max_http_attempts - 1:
                raise Exception("No se pudo conectar a ComfyUI. ¿Está ejecutándose?")
            time.sleep(1)

    ws = websocket.WebSocket()
    max_ws_attempts = int(180/5)  # 3 minutos, reintento cada 5s
    for attempt in range(max_ws_attempts):
        try:
            ws.connect(ws_url)
            logger.info(f"WebSocket OK (intento {attempt+1})")
            break
        except Exception as e:
            logger.warning(f"WebSocket fallo (intento {attempt+1}/{max_ws_attempts}): {e}")
            if attempt == max_ws_attempts - 1:
                raise Exception("Timeout conectando WebSocket (3 minutos).")
            time.sleep(5)

    # -------------------------------------------------------------------------
    # 5) Ejecutar y recolectar artefactos
    # -------------------------------------------------------------------------
    artifacts = get_outputs(ws, prompt)
    ws.close()

    # Preferencia de retorno: video -> gif -> image
    if artifacts.get("videos"):
        return {"video": artifacts["videos"][0], "artifacts": artifacts}
    if artifacts.get("gifs"):
        return {"gif": artifacts["gifs"][0], "artifacts": artifacts}
    if artifacts.get("images"):
        return {"image": artifacts["images"][0], "artifacts": artifacts}

    return {"error": "No se pudo obtener ningún artefacto de salida."}


# Registrar handler con Runpod
runpod.serverless.start({"handler": handler})
