import base64
import json
import mimetypes
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

import boto3
import requests
import runpod


COMFYUI_URL = os.getenv("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
COMFYUI_ROOT = Path(os.getenv("COMFYUI_ROOT", "/workspace/ComfyUI"))
COMFYUI_MODEL_ROOT = Path(os.getenv("COMFYUI_MODEL_ROOT", str(COMFYUI_ROOT / "models")))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/workspace/outputs"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED_MODEL_FILES = [
    "diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    "diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
    "loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank128_bf16.safetensors",
    "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    "vae/wan_2.1_vae.safetensors",
]


def _is_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _missing_required_model_files() -> list[str]:
    return [
        str(COMFYUI_MODEL_ROOT / relative_path)
        for relative_path in REQUIRED_MODEL_FILES
        if not (COMFYUI_MODEL_ROOT / relative_path).is_file()
    ]


def _wait_for_comfyui_ready(timeout_seconds: int = 300, poll_seconds: int = 2) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{COMFYUI_URL}/system_stats", timeout=10)
            if response.status_code < 500:
                return
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(poll_seconds)
    raise TimeoutError(f"ComfyUI did not become ready within {timeout_seconds}s: {last_error}")


def _decode_data_uri(value: str) -> tuple[bytes, str]:
    if not value.startswith("data:") or ";base64," not in value:
        raise ValueError("image must be a data URI")
    header, payload = value.split(",", 1)
    content_type = header.removeprefix("data:").split(";", 1)[0] or "application/octet-stream"
    return base64.b64decode(payload), content_type


def _upload_comfy_image(item: dict) -> str:
    name = item.get("name") or f"input-{uuid.uuid4().hex}.png"
    image = item.get("image")
    if not image:
        raise ValueError(f"image item {name} is missing image data")
    content, content_type = _decode_data_uri(image)
    files = {
        "image": (name, content, content_type),
    }
    data = {
        "overwrite": "true",
        "type": "input",
    }
    response = requests.post(f"{COMFYUI_URL}/upload/image", files=files, data=data, timeout=120)
    response.raise_for_status()
    result = response.json()
    return result.get("name") or name


def _replace_placeholders(value, replacements: dict[str, str]):
    if isinstance(value, dict):
        return {key: _replace_placeholders(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_placeholders(item, replacements) for item in value]
    if isinstance(value, str):
        result = value
        for key, replacement in replacements.items():
            result = result.replace("{{" + key + "}}", replacement)
        return result
    return value


def _submit_workflow(workflow: dict) -> str:
    client_id = str(uuid.uuid4())
    response = requests.post(
        f"{COMFYUI_URL}/prompt",
        json={"prompt": workflow, "client_id": client_id},
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"ComfyUI /prompt HTTP {response.status_code}: {response.text[:4000]}")
    prompt_id = response.json().get("prompt_id")
    if not prompt_id:
        raise RuntimeError("ComfyUI did not return prompt_id")
    return prompt_id


def _workflow_node_types(workflow: dict) -> list[str]:
    node_types = set()
    for node in workflow.values():
        if isinstance(node, dict) and isinstance(node.get("class_type"), str):
            node_types.add(node["class_type"])
    return sorted(node_types)


def _missing_workflow_nodes(workflow: dict) -> list[str]:
    response = requests.get(f"{COMFYUI_URL}/object_info", timeout=60)
    response.raise_for_status()
    available_nodes = set(response.json().keys())
    return [node_type for node_type in _workflow_node_types(workflow) if node_type not in available_nodes]


def _wait_history(prompt_id: str, timeout_seconds: int, poll_seconds: int) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_history = {}
    while time.monotonic() < deadline:
        response = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=60)
        response.raise_for_status()
        history = response.json()
        last_history = history
        if prompt_id in history:
            return history[prompt_id]
        time.sleep(poll_seconds)
    raise TimeoutError(f"ComfyUI prompt did not finish within {timeout_seconds}s: {json.dumps(last_history)[:1000]}")


def _iter_output_files(history: dict):
    outputs = history.get("outputs") or {}
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for group in ("gifs", "videos", "animated", "images"):
            for file_item in node_output.get(group, []) or []:
                if isinstance(file_item, dict) and file_item.get("filename"):
                    yield group, file_item


def _download_comfy_file(file_item: dict, target_dir: Path) -> Path:
    params = {
        "filename": file_item["filename"],
        "type": file_item.get("type", "output"),
        "subfolder": file_item.get("subfolder", ""),
    }
    response = requests.get(f"{COMFYUI_URL}/view?{urlencode(params)}", timeout=180)
    response.raise_for_status()
    suffix = Path(file_item["filename"]).suffix or mimetypes.guess_extension(response.headers.get("Content-Type", "")) or ".bin"
    target = target_dir / f"{Path(file_item['filename']).stem}-{uuid.uuid4().hex[:8]}{suffix}"
    target.write_bytes(response.content)
    return target


def _maybe_upload(path: Path, key_prefix: str) -> dict:
    bucket = os.getenv("S3_BUCKET")
    endpoint_url = os.getenv("S3_ENDPOINT_URL")
    access_key = os.getenv("S3_ACCESS_KEY_ID")
    secret_key = os.getenv("S3_SECRET_ACCESS_KEY")
    if not (bucket and access_key and secret_key):
        return {"url": "", "path": str(path)}

    region = os.getenv("S3_REGION", "auto")
    key = f"{key_prefix.rstrip('/')}/{path.name}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url or None,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    client.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": content_type})
    public_base = os.getenv("S3_PUBLIC_BASE_URL", "").rstrip("/")
    url = f"{public_base}/{key}" if public_base else ""
    return {"url": url, "path": f"s3://{bucket}/{key}"}


def _pick_primary_output(files: list[dict]) -> dict | None:
    for item in files:
        if item["type"].startswith("video/"):
            return item
    return files[0] if files else None


def handler(job):
    data = job.get("input") or {}
    workflow = data.get("workflow")
    if not isinstance(workflow, dict):
        return {"status": "failed", "error": "input.workflow must be a ComfyUI API workflow object"}

    try:
        if not _is_truthy(data.get("skip_model_preflight") or os.getenv("SKIP_MODEL_PREFLIGHT")):
            missing_model_files = _missing_required_model_files()
            if missing_model_files:
                return {
                    "status": "failed",
                    "error": "missing_model_files",
                    "provider": "runpod",
                    "provider_model": "wan2.2-comfyui",
                    "model_root": str(COMFYUI_MODEL_ROOT),
                    "missing_model_files": missing_model_files,
                }

        _wait_for_comfyui_ready(
            int(data.get("comfyui_ready_timeout_seconds") or os.getenv("COMFYUI_READY_TIMEOUT_SECONDS", "300")),
            int(data.get("comfyui_ready_poll_seconds") or os.getenv("COMFYUI_READY_POLL_SECONDS", "2")),
        )

        uploaded = {}
        for image_item in data.get("images", []) or []:
            uploaded_name = _upload_comfy_image(image_item)
            uploaded[image_item.get("name") or uploaded_name] = uploaded_name

        replacements = {
            "INPUT_IMAGE": next(iter(uploaded.values()), ""),
            "START_FRAME": next(iter(uploaded.values()), ""),
        }
        workflow = _replace_placeholders(workflow, replacements)

        if not _is_truthy(data.get("skip_node_preflight") or os.getenv("SKIP_NODE_PREFLIGHT")):
            missing_nodes = _missing_workflow_nodes(workflow)
            if missing_nodes:
                return {
                    "status": "failed",
                    "error": "missing_comfyui_nodes",
                    "provider": "runpod",
                    "provider_model": "wan2.2-comfyui",
                    "missing_nodes": missing_nodes,
                }

        prompt_id = _submit_workflow(workflow)
        history = _wait_history(
            prompt_id,
            int(data.get("timeout_seconds") or os.getenv("COMFYUI_TIMEOUT_SECONDS", "1800")),
            int(data.get("poll_seconds") or os.getenv("COMFYUI_POLL_SECONDS", "2")),
        )

        output_files = []
        for group, file_item in _iter_output_files(history):
            local_path = _download_comfy_file(file_item, OUTPUT_DIR)
            persisted = _maybe_upload(local_path, data.get("output_key_prefix", "formula-faith/runpod/wan22"))
            content_type = mimetypes.guess_type(local_path.name)[0] or (
                "video/mp4" if group in {"gifs", "videos", "animated"} else "application/octet-stream"
            )
            output_files.append({
                "type": content_type,
                "url": persisted["url"],
                "path": persisted["path"],
                "filename": local_path.name,
                "comfyui_group": group,
            })

        primary = _pick_primary_output(output_files)
        if not primary:
            return {
                "status": "failed",
                "provider": "runpod",
                "provider_model": "wan2.2-comfyui",
                "prompt_id": prompt_id,
                "error": "ComfyUI finished without downloadable outputs",
                "history": history,
            }

        return {
            "status": "generated",
            "provider": "runpod",
            "provider_model": "wan2.2-comfyui",
            "prompt_id": prompt_id,
            "output": primary,
            "outputs": output_files,
            "metadata": data.get("metadata") or {},
        }
    except Exception as exc:
        return {"status": "failed", "error": str(exc), "provider": "runpod", "provider_model": "wan2.2-comfyui"}


runpod.serverless.start({"handler": handler})
