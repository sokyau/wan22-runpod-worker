FROM runpod/worker-comfyui:5.8.5-base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OUTPUT_DIR=/workspace/outputs \
    COMFYUI_URL=http://127.0.0.1:8188

WORKDIR /

COPY requirements.txt /tmp/formula-faith-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/formula-faith-requirements.txt

COPY handler.py /handler.py

RUN mkdir -p /workspace/outputs

CMD ["/start.sh"]
