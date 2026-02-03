# /workspace/handler.py

import os
import time
import json
import uuid
import base64
import binascii
import logging
import urllib.request
import urllib.parse
import subprocess

import websocket
import runpod

# --------------------------------------------------------------------------------------
# Config + Logging
# --------------------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

COMFY_HOST = os.getenv("COMFY_HOST", os.getenv("SERVER_ADDRESS", "127.0.0.1"))
COMFY_PORT = int(os.getenv("COMFY_PORT", "8188"))

client_id = str(uuid.uuid4())

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def save_base64_to_file(b64, temp_dir, output_filename):
    try:
        decoded = base64.b64decode(b64)
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.abspath(os.path.join(temp_dir, output_filename))
        with open(file_path, "wb") as f:
            f.write(decoded)
        logger.info(f"✅ Imagen guardada: {file_path}")
        return file_path
    except (binascii.Error, ValueError) as e:
        raise Exception(f"Base64 inválido: {e}")


def load_workflow_from_payload(workflow_payload):
    if isinstance(workflow_payload, dict):
        return workflow_payload
    if isinstance(workflow_payload, str):
        return json.loads(workflow_payload)
    raise Exception("workflow debe ser dict o string JSON")


# --------------------------------------------------------------------------------------
# ComfyUI control
# --------------------------------------------------------------------------------------
def comfy_http_url():
    return f"http://{COMFY_HOST}:{COMFY_PORT}/"


def comfy_ws_url(cid):
    return f"ws://{COMFY_HOST}:{COMFY_PORT}/ws?clientId={cid}"


def comfy_ping(timeout=2):
    try:
        urllib.request.urlopen(comfy_http_url(), timeout=timeout)
        return True
    except Exception:
        return False


def ensure_comfyui_running(timeout=180):
    if comfy_ping():
        logger.info("ComfyUI ya está corriendo.")
        return

    logger.info("ComfyUI no responde, lanzando proceso...")
    logs_path = "/tmp/comfyui-start.log"

    with open(logs_path, "ab", buffering=0) as logf:
        proc = subprocess.Popen(
            [
                "python",
                "/ComfyUI/main.py",
                "--listen",
                COMFY_HOST,
                "--port",
                str(COMFY_PORT),
                "--use-sage-attention",
            ],
            stdout=logf,
            stderr=subprocess.STDOUT,
        )

    logger.info(f"ComfyUI lanzado PID={proc.pid}")

    start = time.time()
    while time.time() - start < timeout:
        if comfy_ping():
            logger.info("✅ ComfyUI listo.")
            return
        time.sleep(1)

    raise RuntimeError("Timeout esperando ComfyUI")


# --------------------------------------------------------------------------------------
# ComfyUI API
# --------------------------------------------------------------------------------------
def queue_prompt(prompt):
    url = f"{comfy_http_url()}prompt"
    payload = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    return json.loads(urllib.request.urlopen(req).read())


def get_view_file(filename, subfolder, folder_type):
    url = f"{comfy_http_url()}view"
    params = urllib.parse.urlencode(
        {"filename": filename, "subfolder": subfolder, "type": folder_type}
    )
    with urllib.request.urlopen(f"{url}?{params}") as response:
        return response.read()


def get_history(prompt_id):
    url = f"{comfy_http_url()}history/{prompt_id}"
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read())


def get_media(ws, prompt):
    prompt_id = queue_prompt(prompt)["prompt_id"]
    outputs = {}

    while True:
        msg = ws.recv()
        if isinstance(msg, str):
            data = json.loads(msg)
            if data.get("type") == "executing":
                d = data.get("data", {})
                if d.get("node") is None and d.get("prompt_id") == prompt_id:
                    break

    history = get_history(prompt_id)[prompt_id]

    for node_id, node_out in history.get("outputs", {}).items():
        media = []
        for key in ["videos", "gifs", "files", "images"]:
            if key in node_out:
                for item in node_out[key]:
                    if item.get("fullpath") and os.path.isfile(item["fullpath"]):
                        with open(item["fullpath"], "rb") as f:
                            media.append(base64.b64encode(f.read()).decode())
                    else:
                        blob = get_view_file(
                            item.get("filename"),
                            item.get("subfolder"),
                            item.get("type"),
                        )
                        media.append(base64.b64encode(blob).decode())
        if media:
            outputs[node_id] = media
            break

    return outputs


# --------------------------------------------------------------------------------------
# Utils workflow
# --------------------------------------------------------------------------------------
def find_load_image_node(workflow):
    for node_id, node in workflow.items():
        if node.get("class_type") == "LoadImage":
            return node_id
    raise Exception("No se encontró nodo LoadImage en el workflow")


# --------------------------------------------------------------------------------------
# Handler principal
# --------------------------------------------------------------------------------------
def handler(job):
    job_input = job.get("input", {})
    logger.info("📥 Job recibido")

    if "workflow" not in job_input:
        raise Exception("El payload debe incluir 'workflow'")

    if "image_base64" not in job_input:
        raise Exception("El payload debe incluir 'image_base64'")

    ensure_comfyui_running()

    task_id = f"task_{uuid.uuid4()}"
    image_path = save_base64_to_file(
        job_input["image_base64"], task_id, "input_image.jpg"
    )

    workflow = load_workflow_from_payload(job_input["workflow"])

    load_image_node_id = find_load_image_node(workflow)
    workflow[load_image_node_id]["inputs"]["image"] = image_path

    ws = websocket.WebSocket()
    ws.connect(comfy_ws_url(client_id))

    outputs = get_media(ws, workflow)
    ws.close()

    for node_id, files in outputs.items():
        if files:
            return {
                "video": files[0],
                "meta": {
                    "node_id": node_id,
                },
            }

    return {"error": "No se encontró salida de video"}


# --------------------------------------------------------------------------------------
# RunPod
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
