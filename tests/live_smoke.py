"""LIVE smoke check against OpenRouter — real network calls, no mocking.

This is deliberately separate from tests/test_openrouter_migration.py, which
mocks all provider traffic. Run this only when you explicitly want to verify a
real key and the real models:

    cd backend && ../.venv/Scripts/python.exe ../tests/live_smoke.py    (Windows)
    .venv/bin/python tests/live_smoke.py                                (macOS/Linux)

Uses synthetic data only: a generated knee-image array encoded with OpenCV and a
fabricated record. No patient images, no patient records, no stored files are
read or written beyond a temporary synthetic PNG.

Prints no API key. Response text is truncated for display.
"""

import base64
import os
import sys
import time

import cv2
import numpy as np

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND, ".env"))

from services import openrouter_client as orc  # noqa: E402

SYNTHETIC_RECORD = {
    "patient": {"name": "Synthetic Demo", "age": 60, "sex": "Female",
                "affected_side": "Left", "imaging_type": "X-ray"},
    "meniscus": {
        "assessment": {"classification": "Moderate OA", "mean_thickness_mm": 3.4,
                       "min_thickness_mm": 3.1},
        "kl_grade": {"grade": 2, "description": "Mild osteophytes"},
    },
    "implant": {"primary": {"system": "Attune", "size": "M", "confidence_pct": 88}},
}


def synthetic_knee_png() -> bytes:
    rs = np.random.RandomState(7)
    h, w = 900, 700
    img = np.full((h, w), 18, np.uint8)
    cv2.ellipse(img, (w // 2, int(h * .33)), (int(w * .27), int(h * .27)), 0, 0, 360, 190, -1)
    cv2.ellipse(img, (w // 2, int(h * .71)), (int(w * .28), int(h * .26)), 0, 0, 360, 180, -1)
    img = cv2.GaussianBlur(img, (7, 7), 0)
    img = np.clip(img.astype(np.int16) + (rs.randn(h, w) * 6).astype(np.int16), 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
    if not ok:
        raise RuntimeError("could not encode synthetic image")
    return buf.tobytes()


def show(label, value):
    print("  {:<22} {}".format(label, value))


def run_live_check() -> int:
    failures = []

    key = orc.api_key()
    if not key:
        print("FAIL  OPENROUTER_API_KEY is not set in backend/.env — nothing to test against.")
        return 1
    print("PASS  key present (len {}, prefix {})".format(len(key), key[:6]))

    print()
    print("Config")
    show("base URL", orc.base_url())
    show("chat model", orc.chat_model())
    show("advice model", orc.advice_model())
    show("vision model", orc.vision_model())

    print()
    print("1. Chat (text)")
    messages = [
        {"role": "system", "content": "You are a helpful assistant for a knee OA platform. Reply in plain text."},
        {"role": "user", "content": "In two sentences, what does a KL grade 2 mean for a knee?"},
    ]
    t0 = time.time()
    try:
        reply = orc.chat(messages, model=orc.chat_model(), max_tokens=orc.CHAT_MAX_TOKENS, temperature=0.6)
        show("status", "OK in {:.1f}s".format(time.time() - t0))
        show("chars", len(reply))
        print("  reply: {}".format(reply[:300].replace("\n", " ")))
    except orc.OpenRouterError as e:
        failures.append("chat")
        show("status", "FAILED: {}".format(e))

    print()
    print("2. Food advice (text, study context)")
    try:
        from routers.advice import _build_messages
        advice = orc.chat(_build_messages(SYNTHETIC_RECORD), model=orc.advice_model(),
                          max_tokens=orc.ADVICE_MAX_TOKENS)
        show("status", "OK in {:.1f}s".format(time.time() - t0))
        show("chars", len(advice))
        print("  reply: {}".format(advice[:300].replace("\n", " ")))
    except orc.OpenRouterError as e:
        failures.append("advice")
        show("status", "FAILED: {}".format(e))

    print()
    print("3. Vision (real image bytes, multimodal)")
    from routers import vision
    png = synthetic_knee_png()
    data_uri = vision._bytes_to_data_uri(png)
    show("image bytes", len(png))
    show("data URI prefix", data_uri[:24])
    show("decoded matches", base64.b64decode(data_uri.split(",", 1)[1]) == png)
    msgs = [
        {"role": "system", "content": vision.SYSTEM},
        {"role": "user", "content": [
            {"type": "text", "text": "Describe what you can see in this knee image."},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]},
    ]
    t0 = time.time()
    try:
        obs = orc.chat(msgs, model=orc.vision_model(), max_tokens=orc.VISION_MAX_TOKENS, temperature=0.4)
        show("status", "OK in {:.1f}s".format(time.time() - t0))
        show("chars", len(obs))
        print("  reply: {}".format(obs[:400].replace("\n", " ")))
    except orc.OpenRouterError as e:
        failures.append("vision")
        show("status", "FAILED: {}".format(e))

    print()
    print("4. BMP conversion path (unsupported -> PNG)")
    ok, bmp = cv2.imencode(".bmp", np.zeros((20, 30, 3), np.uint8))
    if not ok:
        raise RuntimeError("could not encode BMP")
    converted = vision._bytes_to_data_uri(bmp.tobytes())
    show("input", "image/bmp ({} bytes)".format(len(bmp.tobytes())))
    show("output prefix", converted[:22])
    if not converted.startswith("data:image/png;base64,"):
        failures.append("bmp-conversion")

    print()
    if failures:
        print("RESULT: FAILED paths -> {}".format(", ".join(failures)))
        return 1
    print("RESULT: all live paths succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(run_live_check())
