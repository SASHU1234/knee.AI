"""One-time download of the pinned IndicTrans2 model into backend/.models/ (no symlinks needed, works on Windows).

Prereq: accept the model terms on Hugging Face and run `hf auth login` once.
Usage:  python tools/download_translation_model.py [--code-only]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
from huggingface_hub import snapshot_download

from services.local_translation_service import MODEL_DIR, MODEL_ID, MODEL_REVISION

patterns = ["*.py", "*.json", "LICENSE", "README.md", "model.SRC", "model.TGT"]
if "--code-only" not in sys.argv:
    patterns.append("model.safetensors")  # skip the duplicate pytorch_model.bin
snapshot_download(MODEL_ID, revision=MODEL_REVISION, local_dir=MODEL_DIR, allow_patterns=patterns)
print("Model files in", MODEL_DIR)
