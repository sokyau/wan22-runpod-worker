---
title: Formula Faith Wan2.2 ComfyUI RunPod Worker
tags:
  - formula-faith
  - runpod
  - wan2-2
  - comfyui
---

# Formula Faith Wan2.2 ComfyUI RunPod Worker

This is the production-direction Wan2.2 worker for Formula and Faith.

It runs on RunPod Serverless with ComfyUI inside the container. It does not use
Hugging Face Spaces as runtime and does not require `HF_TOKEN`, `HF_HOME`, or
`TRANSFORMERS_CACHE` as endpoint variables.

## Runtime Contract

Input must be a RunPod Serverless payload with:

```json
{
  "input": {
    "workflow": {},
    "images": [
      {
        "name": "start_frame.jpg",
        "image": "data:image/jpeg;base64,..."
      }
    ],
    "output_key_prefix": "formula-faith/smoke/wan22",
    "metadata": {}
  }
}
```

The Formula and Faith VPS adapter already sends this shape.

The worker:

1. Uploads `input.images` into ComfyUI as input files.
2. Replaces `{{INPUT_IMAGE}}` and `{{START_FRAME}}` placeholders in the workflow with the uploaded file name.
3. Submits the workflow to local ComfyUI.
4. Waits for `/history/{prompt_id}`.
5. Downloads video/image outputs from `/view`.
6. Uploads outputs to R2 when `S3_*` env vars exist.
7. Returns a `status: generated` response with `output.url` or `output.path`.

## Files

```text
handler.py
Dockerfile
requirements.txt
test_input.json
.github/workflows/build.yml
```

## Build

```bash
docker build --platform linux/amd64 -t ghcr.io/sokyau/wan22-runpod-worker:latest .
docker push ghcr.io/sokyau/wan22-runpod-worker:latest
```

GitHub Actions builds and pushes this image on `main`.

## RunPod Endpoint Env

Required for durable MP4 output:

```text
S3_ENDPOINT_URL=https://bbce3f740f6fd58d4bfd51a6c45f97b8.r2.cloudflarestorage.com
S3_BUCKET=yt-ff
S3_REGION=auto
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_PUBLIC_BASE_URL=https://pub-7efb5fc6471f412fada808865048a88e.r2.dev
```

Optional:

```text
OUTPUT_DIR=/workspace/outputs
COMFYUI_URL=http://127.0.0.1:8188
COMFYUI_TIMEOUT_SECONDS=1800
COMFYUI_POLL_SECONDS=2
```

## VPS Hermes Env

Set these on the VPS profile that calls RunPod:

```text
RUNPOD_API_KEY=...
RUNPOD_WAN22_ENDPOINT_ID=...
```

Do not put `RUNPOD_API_KEY` into the RunPod endpoint.

## Model Files

The endpoint image is a ComfyUI worker. Wan2.2 model files must be available to
ComfyUI through the image or a RunPod Network Volume before real jobs run.

Do not rely on Hugging Face runtime downloads as the production path.

## Deploy Checklist

1. Push this repo to `main`.
2. Confirm GitHub Actions publishes `ghcr.io/sokyau/wan22-runpod-worker:latest`.
3. Create a RunPod Serverless endpoint from that image.
4. Add the `S3_*` endpoint variables.
5. Make sure Wan2.2 ComfyUI model files and custom nodes are present in the image or mounted volume.
6. Copy the endpoint ID to `~/.hermes/profiles/ff-yt-media/.env` as `RUNPOD_WAN22_ENDPOINT_ID`.
7. Run a dry-run through the Formula and Faith adapter.
8. Ask Jorge before the first real GPU smoke test.
