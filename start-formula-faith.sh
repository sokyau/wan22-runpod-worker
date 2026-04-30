#!/usr/bin/env sh
set -eu

COMFYUI_ROOT="${COMFYUI_ROOT:-/workspace/ComfyUI}"
COMFYUI_MODEL_ROOT="${COMFYUI_MODEL_ROOT:-$COMFYUI_ROOT/models}"
MODEL_VOLUME_ROOT="${MODEL_VOLUME_ROOT:-/runpod-volume/ComfyUI/models}"

if [ -d "$MODEL_VOLUME_ROOT" ]; then
  for category in diffusion_models loras text_encoders vae; do
    source_dir="$MODEL_VOLUME_ROOT/$category"
    target_dir="$COMFYUI_MODEL_ROOT/$category"
    mkdir -p "$target_dir"
    if [ -d "$source_dir" ]; then
      for source_file in "$source_dir"/*; do
        [ -f "$source_file" ] || continue
        target_file="$target_dir/$(basename "$source_file")"
        if [ ! -e "$target_file" ]; then
          ln -s "$source_file" "$target_file"
        fi
      done
    fi
  done
fi

exec /start.sh
