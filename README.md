---
title: Formula Faith Wan2.2 HF Port Worker
tags:
  - formula-faith
  - runpod
  - wan2-2
---

# Formula Faith Wan2.2 HF Port Worker

This worker ports the useful generation path from:

```text
https://huggingface.co/spaces/r3gm/wan2-2-fp8da-aoti-preview
```

It is prepared for RunPod Serverless. It does not include model weights.

## Files

```text
handler.py
Dockerfile
requirements.txt
test_input.json
spaces.py
space_src/app.py
space_src/aoti.py
space_src/model/
```

## Build

```bash
docker build --platform linux/amd64 -t YOUR_REGISTRY/formula-faith-wan22-hf-port:latest .
docker push YOUR_REGISTRY/formula-faith-wan22-hf-port:latest
```

## RunPod Env

Required by RunPod:

```text
RUNPOD_API_KEY
```

Optional for durable MP4 output:

```text
S3_ENDPOINT_URL
S3_BUCKET
S3_REGION
S3_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY
S3_PUBLIC_BASE_URL
```

## Test Locally In Container

This requires GPU and model downloads:

```bash
python handler.py --test_input "$(cat test_input.json)"
```

## Notes

The source Space loads models at import time. On RunPod, expect first startup to download/cache the model and take longer than normal inference.
