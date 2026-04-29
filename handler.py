import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

import boto3
import requests
import runpod
from PIL import Image

APP_DIR = Path(__file__).resolve().parent
SPACE_SRC = APP_DIR / "space_src"
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/workspace/outputs"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SPACE_SRC))

import app as space_app  # noqa: E402


def _download_file(url: str, suffix: str = "") -> Path:
    parsed = urlparse(url)
    suffix = suffix or Path(parsed.path).suffix or ".bin"
    target = Path(tempfile.mktemp(suffix=suffix))
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    return target


def _load_image(value: str | None) -> Image.Image | None:
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        path = _download_file(value, ".jpg")
    else:
        path = Path(value)
    return Image.open(path).convert("RGB")


def _maybe_upload(path: Path, key_prefix: str) -> dict:
    bucket = os.getenv("S3_BUCKET")
    endpoint_url = os.getenv("S3_ENDPOINT_URL")
    access_key = os.getenv("S3_ACCESS_KEY_ID")
    secret_key = os.getenv("S3_SECRET_ACCESS_KEY")
    if not (bucket and access_key and secret_key):
        return {"url": "", "path": str(path)}

    region = os.getenv("S3_REGION", "auto")
    key = f"{key_prefix.rstrip('/')}/{path.name}"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url or None,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    client.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": "video/mp4"})
    public_base = os.getenv("S3_PUBLIC_BASE_URL", "").rstrip("/")
    url = f"{public_base}/{key}" if public_base else ""
    return {"url": url, "path": f"s3://{bucket}/{key}"}


def handler(job):
    data = job.get("input") or {}
    job_id = job.get("id") or str(uuid.uuid4())
    image = _load_image(data.get("input_image_url") or data.get("image_url"))
    last_image = _load_image(data.get("last_image_url"))

    if image is None:
        return {"status": "failed", "error": "input_image_url is required"}

    prompt = data.get("prompt") or "make this image come alive, cinematic motion, smooth animation"
    negative_prompt = data.get("negative_prompt") or space_app.default_negative_prompt
    seed = int(data.get("seed", 1007968632))
    duration_seconds = float(data.get("duration_seconds", 3))
    steps = int(data.get("steps", 4))
    quality = int(data.get("quality", 5))
    scheduler = data.get("scheduler", "UniPCMultistep")
    frame_multiplier = int(data.get("frame_multiplier", space_app.FIXED_FPS))
    guidance_scale = float(data.get("guidance_scale", 1))
    guidance_scale_2 = float(data.get("guidance_scale_2", 1))
    flow_shift = float(data.get("flow_shift", 3.0))

    _preview, video_path, used_seed = space_app.generate_video(
        input_image=image,
        last_image=last_image,
        prompt=prompt,
        steps=steps,
        negative_prompt=negative_prompt,
        duration_seconds=duration_seconds,
        guidance_scale=guidance_scale,
        guidance_scale_2=guidance_scale_2,
        seed=seed,
        randomize_seed=False,
        quality=quality,
        scheduler=scheduler,
        flow_shift=flow_shift,
        frame_multiplier=frame_multiplier,
        video_component=False,
    )

    if not video_path:
        return {"status": "failed", "error": "generation returned no video_path", "seed": used_seed}

    output_path = OUTPUT_DIR / f"wan22-{job_id}.mp4"
    shutil.copyfile(video_path, output_path)
    persisted = _maybe_upload(output_path, data.get("output_key_prefix", "formula-faith/runpod/wan22"))

    return {
        "status": "generated",
        "provider": "runpod",
        "provider_model": "wan2.2-i2v-lightning-hf-port",
        "output": {
            "type": "video/mp4",
            "url": persisted["url"],
            "path": persisted["path"],
        },
        "seed": used_seed,
        "duration_seconds": duration_seconds,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
    }


runpod.serverless.start({"handler": handler})
