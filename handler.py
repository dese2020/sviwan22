
# /workspace/handler.py (GGUF-ready)
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

# ------------------------------------------------------------
# Config + Logging
# ------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Prefer COMFY_HOST/COMFY_PORT. Keep SERVER_ADDRESS for backward compat
COMFY_HOST = os.getenv("COMFY_HOST", os.getenv("SERVER_ADDRESS", "127.0.0.1"))
COMFY_PORT = int(os.getenv("COMFY_PORT", "8188"))

# WS client id for ComfyUI
client_id = str(uuid.uuid4())

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def to_nearest_multiple_of_16(value):
    """Round to nearest multiple of 16 (minimum 16)."""
    try:
        numeric_value = float(value)
    except Exception:
        raise Exception(f"width/height must be numeric: {value}")
    adjusted = int(round(numeric_value / 16.0) * 16)
    return max(adjusted, 16)


def download_file_from_url(url, output_path):
    """Download using wget with retries/timeouts."""
    try:
        result = subprocess.run(
            [
                "wget", "-O", output_path, "--no-verbose",
                "--tries=5", "--timeout=60", "--read-timeout=60",
                "--retry-connrefused", "--waitretry=5",
                url
            ],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            logger.info(f"✅ Downloaded: {url} → {output_path}")
            return output_path
        logger.error(f"❌ wget failed: {result.stderr}")
        raise Exception(f"URL download failed: {result.stderr}")
    except subprocess.TimeoutExpired:
        logger.error("❌ Download timeout")
        raise Exception("Download timeout")
    except Exception as e:
        logger.error(f"❌ Download error: {e}")
        raise Exception(f"Download error: {e}")


def save_base64_to_file(b64, temp_dir, output_filename):
    """Save base64 to a local file and return its path."""
    try:
        decoded = base64.b64decode(b64)
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.abspath(os.path.join(temp_dir, output_filename))
        with open(file_path, 'wb') as f:
            f.write(decoded)
        logger.info(f"✅ Base64 saved at {file_path}")
        return file_path
    except (binascii.Error, ValueError) as e:
        logger.error(f"❌ Invalid Base64: {e}")
        raise Exception(f"Invalid Base64: {e}")


def process_input(input_data, temp_dir, output_filename, input_type):
    """Normalize an input image into a local file and return its path."""
    if input_type == "path":
        logger.info(f"📁 Using local path: {input_data}")
        return input_data
    elif input_type == "url":
        logger.info(f"🌐 Downloading URL: {input_data}")
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.abspath(os.path.join(temp_dir, output_filename))
        return download_file_from_url(input_data, file_path)
    elif input_type == "base64":
        logger.info("🧬 Decoding Base64…")
        return save_base64_to_file(input_data, temp_dir, output_filename)
    else:
        raise Exception(f"Unsupported input_type: {input_type}")


# ------------------------------------------------------------
# ComfyUI control (lazy start)
# ------------------------------------------------------------

def comfy_http_url() -> str:
    return f"http://{COMFY_HOST}:{COMFY_PORT}/"


def comfy_ws_url(cid: str) -> str:
    return f"ws://{COMFY_HOST}:{COMFY_PORT}/ws?clientId={cid}"


def comfy_ping(timeout=2) -> bool:
    try:
        urllib.request.urlopen(comfy_http_url(), timeout=timeout)
        return True
    except Exception:
        return False


def ensure_comfyui_running(timeout=180):
    """
    Launch ComfyUI in background if it isn't responding.
    Wait up to `timeout` seconds.
    """
    if comfy_ping(timeout=1):
        logger.info("ComfyUI already running.")
        return

    logger.info(f"ComfyUI not responding at {COMFY_HOST}:{COMFY_PORT}, starting process…")
    logs_path = "/tmp/comfyui-start.log"
    with open(logs_path, "ab", buffering=0) as logf:
        proc = subprocess.Popen(
            [
                "python", "/ComfyUI/main.py",
                "--listen", COMFY_HOST,
                "--port", str(COMFY_PORT),
                "--use-sage-attention"
            ],
            stdout=logf, stderr=subprocess.STDOUT
        )
    logger.info(f"ComfyUI launched PID={proc.pid} (logs: {logs_path})")

    start = time.time()
    while time.time() - start < timeout:
        if comfy_ping(timeout=2):
            logger.info("✅ ComfyUI is ready.")
            return
        time.sleep(1)

    try:
        tail = subprocess.run(["tail", "-n", "120", logs_path], capture_output=True, text=True)
        logger.error("⚠️ Timeout waiting for ComfyUI; last logs:
" + tail.stdout)
    except Exception:
        pass
    raise RuntimeError("Timeout waiting for ComfyUI.")


# ------------------------------------------------------------
# ComfyUI HTTP/WS API helpers
# ------------------------------------------------------------

def queue_prompt(prompt):
    url = f"{comfy_http_url()}prompt"
    logger.info(f"POST {url}")
    payload = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    return json.loads(urllib.request.urlopen(req).read())


def get_view_file(filename, subfolder, folder_type):
    url = f"{comfy_http_url()}view"
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen(f"{url}?{url_values}") as response:
        return response.read()


def get_history(prompt_id):
    url = f"{comfy_http_url()}history/{prompt_id}"
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read())


def get_media(ws, prompt, preferred_node_id=None):
    """Send prompt and return outputs (prioritize video, prefer a specific node when provided)."""
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
    # Build outputs map: node_id -> list of base64 media
    for node_id, node_out in history.get('outputs', {}).items():
        media_list = []
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
                            logger.warning(f"/view fallback failed: {e}")
        if media_list:
            outputs[node_id] = media_list

    # Prefer a node if requested
    if preferred_node_id and preferred_node_id in outputs:
        return {preferred_node_id: outputs[preferred_node_id]}

    # else first node with any media
    return outputs


def load_workflow(workflow_path):
    with open(workflow_path, 'r') as f:
        return json.load(f)


# ------------------------------------------------------------
# Node map for SVI_extension_gguf_api.json
# (IDs must match the uploaded ComfyUI workflow)
# ------------------------------------------------------------
NODES = {
    # Inputs & parameters
    "LOAD_IMAGE": "10",           # LoadImage: inputs.image
    "WIDTH": "159",               # PrimitiveInt: inputs.value
    "HEIGHT": "160",              # PrimitiveInt: inputs.value
    "FRAMES_PER_SECTION": "259",  # easy int / Primitive: inputs.value
    "FPS": "262",                 # PrimitiveInt: inputs.value

    # Text encoders (positive per section)
    "P_POS_1": "21",
    "P_POS_2": "464",
    "P_POS_3": "469",
    "P_POS_4": "501",

    # Text encoders (negative per section)
    "P_NEG_1": "1",
    "P_NEG_2": "465",
    "P_NEG_3": "471",
    "P_NEG_4": "502",

    # Video combine (MP4)
    "VIDEO_COMBINE": "444",

    # Model/Clip/VAE loaders (GGUF + VAE)
    "UNET_HIGH_GGUF": "512",      # UnetLoaderGGUF: inputs.unet_name
    "UNET_LOW_GGUF":  "513",      # UnetLoaderGGUF: inputs.unet_name
    "CLIP_GGUF":      "514",      # CLIPLoaderGGUF: inputs.clip_name, inputs.type
    "VAE":            "3",        # VAELoader: inputs.vae_name

    # Last 2 LoRAs in each branch (those safe to override)
    # High branch chain: 512 -> 18 -> 409 -> 515 -> 517 -> ModelSamplingSD3(60)
    "LORA_HIGH_LAST_1": "515",
    "LORA_HIGH_LAST_2": "517",
    # Low branch chain: 513 -> 404 -> 408 -> 516 -> 518 -> ModelSamplingSD3(402)
    "LORA_LOW_LAST_1":  "516",
    "LORA_LOW_LAST_2":  "518",
}


def apply_core_params(prompt_graph, args):
    """Inject image, size, fps, frames/section and prompts in the graph."""
    # Image
    prompt_graph[NODES["LOAD_IMAGE"]]["inputs"]["image"] = args["image_path"]

    # Dimensions
    w = to_nearest_multiple_of_16(args.get("width", 480))
    h = to_nearest_multiple_of_16(args.get("height", 832))
    prompt_graph[NODES["WIDTH"]]["inputs"]["value"] = int(w)
    prompt_graph[NODES["HEIGHT"]]["inputs"]["value"] = int(h)

    # FPS & frames/section
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
        p = args.get(
            "prompt",
            "A cinematic realistic video, natural motion, detailed lighting and composition"
        )
        p1 = p2 = p3 = p4 = p

    neg = args.get(
        "negative_prompt",
        "bright tones, overexposed, static, blurred details, subtitles, worst quality, low quality, jpeg artifacts, ugly, extra fingers, bad hands, bad face, deformed, disfigured, fused fingers, messy background"
    )

    prompt_graph[NODES["P_POS_1"]]["inputs"]["text"] = p1
    prompt_graph[NODES["P_POS_2"]]["inputs"]["text"] = p2
    prompt_graph[NODES["P_POS_3"]]["inputs"]["text"] = p3
    prompt_graph[NODES["P_POS_4"]]["inputs"]["text"] = p4

    prompt_graph[NODES["P_NEG_1"]]["inputs"]["text"] = neg
    prompt_graph[NODES["P_NEG_2"]]["inputs"]["text"] = neg
    prompt_graph[NODES["P_NEG_3"]]["inputs"]["text"] = neg
    prompt_graph[NODES["P_NEG_4"]]["inputs"]["text"] = neg

    # Video encode tune
    vc_inputs = prompt_graph[NODES["VIDEO_COMBINE"]]["inputs"]
    vc_inputs["frame_rate"] = fps
    if "crf" in args and args["crf"] is not None:
        vc_inputs["crf"] = int(args["crf"])
    if "pix_fmt" in args and args["pix_fmt"]:
        vc_inputs["pix_fmt"] = str(args["pix_fmt"])  # e.g. "yuv420p"
    if "format" in args and args["format"]:
        vc_inputs["format"] = str(args["format"])     # e.g. "video/h264-mp4"

    return prompt_graph


def set_lora_inputs(node_obj, name=None, strength=None):
    """Write lora_name / strength_model when provided in payload."""
    if name is not None:
        node_obj["inputs"]["lora_name"] = name
    if strength is not None:
        node_obj["inputs"]["strength_model"] = float(strength)


def apply_last_two_loras(prompt_graph, loras):
    """
    loras = {
        "high": [
            {"name": "...", "strength": 1.0},  # -> NODES["LORA_HIGH_LAST_1"] (515)
            {"name": "...", "strength": 1.0},  # -> NODES["LORA_HIGH_LAST_2"] (517)
        ],
        "low": [
            {"name": "...", "strength": 1.0},  # -> NODES["LORA_LOW_LAST_1"]  (516)
            {"name": "...", "strength": 1.0},  # -> NODES["LORA_LOW_LAST_2"]  (518)
        ]
    }
    Only the last two LoRAs per branch are overridden; earlier ones (lightx2v, SVI) are kept.
    """
    if not isinstance(loras, dict):
        return prompt_graph

    # HIGH
    high = loras.get("high")
    if isinstance(high, list) and len(high) > 0:
        slot1 = high[0] if len(high) >= 1 else None
        if isinstance(slot1, dict):
            set_lora_inputs(
                prompt_graph[NODES["LORA_HIGH_LAST_1"]],
                name=slot1.get("name"),
                strength=slot1.get("strength"),
            )
        slot2 = high[1] if len(high) >= 2 else None
        if isinstance(slot2, dict):
            set_lora_inputs(
                prompt_graph[NODES["LORA_HIGH_LAST_2"]],
                name=slot2.get("name"),
                strength=slot2.get("strength"),
            )

    # LOW
    low = loras.get("low")
    if isinstance(low, list) and len(low) > 0:
        slot1 = low[0] if len(low) >= 1 else None
        if isinstance(slot1, dict):
            set_lora_inputs(
                prompt_graph[NODES["LORA_LOW_LAST_1"]],
                name=slot1.get("name"),
                strength=slot1.get("strength"),
            )
        slot2 = low[1] if len(low) >= 2 else None
        if isinstance(slot2, dict):
            set_lora_inputs(
                prompt_graph[NODES["LORA_LOW_LAST_2"]],
                name=slot2.get("name"),
                strength=slot2.get("strength"),
            )

    return prompt_graph


def apply_gguf_models(prompt_graph, gguf_models):
    """
    Optionally override GGUF/weights:
    gguf_models = {
        "clip_name": "umt5-xxl-encoder-Q8_0.gguf",   # NODES["CLIP_GGUF"] inputs.clip_name
        "clip_type": "wan",                            # optional, defaults to existing
        "unet_high": "Wan2.2-I2V-A14B-HighNoise-Q8_0.gguf",  # NODES["UNET_HIGH_GGUF"] inputs.unet_name
        "unet_low":  "Wan2.2-I2V-A14B-LowNoise-Q8_0.gguf",   # NODES["UNET_LOW_GGUF"] inputs.unet_name
        "vae_name":  "wan_2.1_vae.safetensors"               # NODES["VAE"] inputs.vae_name
    }
    """
    if not isinstance(gguf_models, dict):
        return prompt_graph

    # CLIP
    if gguf_models.get("clip_name") is not None:
        prompt_graph[NODES["CLIP_GGUF"]]["inputs"]["clip_name"] = gguf_models.get("clip_name")
    if gguf_models.get("clip_type") is not None:
        prompt_graph[NODES["CLIP_GGUF"]]["inputs"]["type"] = gguf_models.get("clip_type")

    # UNETs
    if gguf_models.get("unet_high") is not None:
        prompt_graph[NODES["UNET_HIGH_GGUF"]]["inputs"]["unet_name"] = gguf_models.get("unet_high")
    if gguf_models.get("unet_low") is not None:
        prompt_graph[NODES["UNET_LOW_GGUF"]]["inputs"]["unet_name"] = gguf_models.get("unet_low")

    # VAE
    if gguf_models.get("vae_name") is not None:
        prompt_graph[NODES["VAE"]]["inputs"]["vae_name"] = gguf_models.get("vae_name")

    return prompt_graph


# ------------------------------------------------------------
# Main handler
# ------------------------------------------------------------

def handler(job):
    job_input = job.get("input", {})
    logger.info(f"Job input: {job_input}")
    task_id = f"task_{uuid.uuid4()}"

    # 0) Ensure ComfyUI is running on this worker
    ensure_comfyui_running()

    # 1) Normalize input image
    image_path = None
    if "image_path" in job_input:
        image_path = process_input(job_input["image_path"], task_id, "input_image.jpg", "path")
    elif "image_url" in job_input:
        image_path = process_input(job_input["image_url"], task_id, "input_image.jpg", "url")
    elif "image_base64" in job_input:
        image_path = process_input(job_input["image_base64"], task_id, "input_image.jpg", "base64")
    else:
        image_path = "/example.png"
        logger.info("Using default image /example.png")

    # 2) Load workflow and apply parameters
    workflow_path = job_input.get("workflow_path", "SVI_extension_gguf_api.json")
    prompt_graph = load_workflow(workflow_path)

    args = {
        "image_path": image_path,
        "width": job_input.get("width", 480),
        "height": job_input.get("height", 832),
        "fps": job_input.get("fps", 16),
        "frames_per_section": job_input.get("frames_per_section", 81),
        "prompt": job_input.get("prompt"),
        "prompts": job_input.get("prompts"),  # optional list (1–4)
        "negative_prompt": job_input.get("negative_prompt"),
        "crf": job_input.get("crf"),
        "pix_fmt": job_input.get("pix_fmt"),
        "format": job_input.get("format"),
    }
    prompt_graph = apply_core_params(prompt_graph, args)

    # 3) Optionally override GGUF/weights
    gguf_models = job_input.get("gguf", None)
    if gguf_models:
        prompt_graph = apply_gguf_models(prompt_graph, gguf_models)

    # 4) Apply only the last two LoRAs per branch (if provided)
    loras = job_input.get("loras", None)
    if loras:
        prompt_graph = apply_last_two_loras(prompt_graph, loras)

    # 5) Connect WebSocket
    ws_url = comfy_ws_url(client_id)
    logger.info(f"Connecting WS: {ws_url}")
    ws = websocket.WebSocket()
    max_ws_attempts = 36  # ~3 min (36 * 5s)
    for attempt in range(max_ws_attempts):
        try:
            ws.connect(ws_url)
            logger.info(f"WebSocket OK (attempt {attempt+1})")
            break
        except Exception as e:
            if attempt == max_ws_attempts - 1:
                raise Exception(f"Timeout connecting WebSocket (3 min). Last error: {e}")
            time.sleep(5)

    # 6) Execute and collect outputs; prefer the VideoCombine node
    outputs = get_media(ws, prompt_graph, preferred_node_id=NODES.get("VIDEO_COMBINE"))
    ws.close()

    for node_id, files in outputs.items():
        if files:
            return {
                "video": files[0],  # base64 of first artifact (expect MP4)
                "meta": {
                    "node_id": node_id,
                    "width": to_nearest_multiple_of_16(args["width"]),
                    "height": to_nearest_multiple_of_16(args["height"]),
                    "fps": int(args["fps"]),
                    "frames_per_section": int(args["frames_per_section"]),
                    "sections": 4
                }
            }

    return {"error": "No video output found."}


# RunPod serverless entrypoint
if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
