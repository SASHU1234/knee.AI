"""OpenRouter migration tests: client, chat, advice and vision paths.

All external HTTP is mocked — no OpenRouter calls, no Supabase calls, no real
patient data. Images are tiny OpenCV-synthesised arrays.

Run with the project venv from the repo root:
    .venv/bin/python tests/test_openrouter_migration.py
"""

import base64
import os
import sys
import tempfile
import unittest
from unittest import mock

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

import cv2
import httpx
import numpy as np

from services import openrouter_client as orc

TEST_ENV = {
    "OPENROUTER_API_KEY": "test-openrouter-key",
    "OPENROUTER_CHAT_MODEL": "test/chat-model:free",
    "OPENROUTER_ADVICE_MODEL": "test/advice-model:free",
    "OPENROUTER_VISION_MODEL": "test/vision-model:free",
}

MESSAGES = [{"role": "user", "content": "hello"}]


def ok_response(content="**Bold** answer\n1. one\n2. two"):
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
        request=req,
    )


def error_response(status):
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return httpx.Response(status, json={"error": {"message": "upstream detail"}}, request=req)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, TEST_ENV)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_url_and_auth_header(self):
        with mock.patch.object(orc.httpx, "post", return_value=ok_response()) as post:
            orc.chat(MESSAGES)
        _, kwargs = post.call_args
        self.assertEqual(post.call_args[0][0], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-openrouter-key")
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")

    def test_base_url_override(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_BASE_URL": "https://example.test/v1/"}):
            with mock.patch.object(orc.httpx, "post", return_value=ok_response()) as post:
                orc.chat(MESSAGES)
        self.assertEqual(post.call_args[0][0], "https://example.test/v1/chat/completions")

    def test_model_selection_from_env(self):
        self.assertEqual(orc.chat_model(), "test/chat-model:free")
        self.assertEqual(orc.advice_model(), "test/advice-model:free")
        self.assertEqual(orc.vision_model(), "test/vision-model:free")
        with mock.patch.object(orc.httpx, "post", return_value=ok_response()) as post:
            orc.chat(MESSAGES, model=orc.vision_model())
        self.assertEqual(post.call_args[1]["json"]["model"], "test/vision-model:free")

    def test_default_models_when_env_unset(self):
        for var in ("OPENROUTER_CHAT_MODEL", "OPENROUTER_ADVICE_MODEL", "OPENROUTER_VISION_MODEL"):
            os.environ.pop(var, None)
        self.assertEqual(orc.chat_model(), "nvidia/nemotron-3.5-lightning:free")
        self.assertEqual(orc.advice_model(), "nvidia/nemotron-3.5-lightning:free")
        self.assertEqual(orc.vision_model(), "nvidia/nemotron-3.5-super-vl:free")

    def test_success_parse(self):
        with mock.patch.object(orc.httpx, "post", return_value=ok_response("plain answer")):
            self.assertEqual(orc.chat(MESSAGES), "plain answer")

    def test_empty_response_rejected(self):
        with mock.patch.object(orc.httpx, "post", return_value=ok_response("   ")):
            with self.assertRaisesRegex(orc.OpenRouterError, "empty"):
                orc.chat(MESSAGES)

    def test_truncated_response_rejected_even_with_partial_text(self):
        # A reasoning model that exhausts its budget returns half an answer with
        # finish_reason "length"; that must not be served as if complete.
        truncated = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "For a 60-year-old woman with moderate knee"},
                               "finish_reason": "length"}]},
            request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
        )
        with mock.patch.object(orc.httpx, "post", return_value=truncated):
            with self.assertRaisesRegex(orc.OpenRouterError, "cut off before it finished"):
                orc.chat(MESSAGES)

    def test_budgets_are_centralized_constants(self):
        # Reasoning models need headroom for hidden chain-of-thought; these
        # numbers are the ones measured live against OpenRouter.
        self.assertGreaterEqual(orc.CHAT_MAX_TOKENS, 2000)
        self.assertGreaterEqual(orc.ADVICE_MAX_TOKENS, 8000)
        self.assertGreaterEqual(orc.VISION_MAX_TOKENS, 2000)

    def test_malformed_response_rejected(self):
        with mock.patch.object(orc.httpx, "post", return_value=ok_response()) as post:
            post.return_value = httpx.Response(
                200, json={"unexpected": True},
                request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
            )
            with self.assertRaisesRegex(orc.OpenRouterError, "Unexpected response shape"):
                orc.chat(MESSAGES)

    def test_timeout(self):
        with mock.patch.object(orc.httpx, "post", side_effect=httpx.TimeoutException("t")):
            with self.assertRaisesRegex(orc.OpenRouterError, "did not respond in time"):
                orc.chat(MESSAGES)

    def test_error_statuses(self):
        expectations = {
            401: "API key",
            402: "credits",
            429: "rate limit",
            500: "unavailable",
        }
        for status, needle in expectations.items():
            with mock.patch.object(orc.httpx, "post", return_value=error_response(status)):
                with self.assertRaises(orc.OpenRouterError) as ctx:
                    orc.chat(MESSAGES)
            self.assertIn(needle, str(ctx.exception), "status %d" % status)
            # Upstream body must never leak into the frontend-safe message.
            self.assertNotIn("upstream detail", str(ctx.exception))

    def test_missing_key(self):
        os.environ["OPENROUTER_API_KEY"] = ""
        with self.assertRaisesRegex(orc.OpenRouterError, "OPENROUTER_API_KEY"):
            orc.chat(MESSAGES)

    def test_optional_attribution_headers(self):
        with mock.patch.object(orc.httpx, "post", return_value=ok_response()) as post:
            orc.chat(MESSAGES)
        headers = post.call_args[1]["headers"]
        self.assertNotIn("HTTP-Referer", headers)
        self.assertNotIn("X-OpenRouter-Title", headers)
        extra = {"OPENROUTER_REFERER": "https://kneeai.example", "OPENROUTER_TITLE": "Knee.AI"}
        with mock.patch.dict(os.environ, extra):
            with mock.patch.object(orc.httpx, "post", return_value=ok_response()) as post:
                orc.chat(MESSAGES)
        headers = post.call_args[1]["headers"]
        self.assertEqual(headers["HTTP-Referer"], "https://kneeai.example")
        self.assertEqual(headers["X-OpenRouter-Title"], "Knee.AI")

    def test_language_instruction_whitelist(self):
        self.assertIn("Respond in Hindi", orc.language_instruction("Hindi"))
        self.assertEqual(orc.language_instruction("Klingon"), "")
        self.assertEqual(orc.language_instruction(None), "")

    def test_strip_markdown(self):
        self.assertEqual(orc.strip_markdown("**Bold**\n## Head\n1. item\n* star"), "Bold\nHead\n- item\n- star")


class EndpointTestBase(unittest.TestCase):
    """Spin up the real FastAPI app with auth overridden; mock only the
    OpenRouter HTTP call, so request/response contracts are exercised end
    to end."""

    @classmethod
    def setUpClass(cls):
        import main
        from fastapi.testclient import TestClient
        from routers.analysis import get_current_user

        main.app.dependency_overrides[get_current_user] = lambda: "test-user"
        cls.client = TestClient(main.app)

    def setUp(self):
        self.env = mock.patch.dict(os.environ, TEST_ENV)
        self.env.start()

    def tearDown(self):
        self.env.stop()


RECORD = {
    "patient": {"name": "Synthetic Demo", "age": 60, "sex": "Female", "affected_side": "Left",
                "imaging_type": "X-ray"},
    "meniscus": {
        "assessment": {"classification": "Moderate OA", "mean_thickness_mm": 3.4, "min_thickness_mm": 3.1},
        "kl_grade": {"grade": 2, "description": "Mild osteophytes"},
    },
    "implant": {"primary": {"system": "Attune", "size": "M", "confidence_pct": 88}},
}


class ChatEndpointTests(EndpointTestBase):
    def test_chat_uses_chat_model_and_language(self):
        with mock.patch.object(orc.httpx, "post", return_value=ok_response("**Hi** there")) as post:
            resp = self.client.post("/api/chat", json={
                "messages": [{"role": "user", "content": "what is my KL grade?"}],
                "record": RECORD,
                "language": "Hindi",
            })
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json(), {"reply": "Hi there"})
        payload = post.call_args[1]["json"]
        self.assertEqual(payload["model"], "test/chat-model:free")
        self.assertEqual(payload["max_tokens"], orc.CHAT_MAX_TOKENS)
        system = payload["messages"][0]
        self.assertEqual(system["role"], "system")
        self.assertIn("Respond in Hindi", system["content"])
        # Study context injection preserved.
        self.assertIn("age 60", system["content"])
        self.assertIn("Moderate OA", system["content"])
        # Conversation history passed through after the system prompt.
        self.assertEqual(payload["messages"][1], {"role": "user", "content": "what is my KL grade?"})

    def test_chat_limits(self):
        self.assertEqual(self.client.post("/api/chat", json={"messages": []}).status_code, 400)
        too_many = [{"role": "user", "content": "x"}] * 21
        self.assertEqual(self.client.post("/api/chat", json={"messages": too_many}).status_code, 400)
        bad_role = [{"role": "system", "content": "x"}]
        self.assertEqual(self.client.post("/api/chat", json={"messages": bad_role}).status_code, 400)
        last_not_user = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]
        self.assertEqual(self.client.post("/api/chat", json={"messages": last_not_user}).status_code, 400)

    def test_chat_provider_error_maps_to_502(self):
        with mock.patch.object(orc.httpx, "post", return_value=error_response(429)):
            resp = self.client.post("/api/chat", json={
                "messages": [{"role": "user", "content": "hi"}],
            })
        self.assertEqual(resp.status_code, 502)
        self.assertIn("rate limit", resp.json()["detail"])


class AdviceEndpointTests(EndpointTestBase):
    def test_advice_uses_advice_model_and_language(self):
        with mock.patch.object(orc.httpx, "post", return_value=ok_response("## Eat well\n1. fish")) as post:
            resp = self.client.post("/api/advice", json={"record": RECORD, "language": "Tamil"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json(), {"advice": "Eat well\n- fish"})
        payload = post.call_args[1]["json"]
        self.assertEqual(payload["model"], "test/advice-model:free")
        self.assertEqual(payload["max_tokens"], orc.ADVICE_MAX_TOKENS)
        system, user = payload["messages"]
        self.assertIn("Respond in Tamil", system["content"])
        # Study context: severity, age, sex preserved in the user message.
        self.assertIn("Moderate OA", user["content"])
        self.assertIn("age 60", user["content"])
        self.assertIn("Female", user["content"])


def tiny_image(ext):
    img = np.full((20, 30, 3), 127, np.uint8)
    ok, buf = cv2.imencode(ext, img)
    assert ok
    return buf.tobytes()


class VisionEndpointTests(EndpointTestBase):
    def test_sniff_mime(self):
        from routers import vision
        self.assertEqual(vision._sniff_mime(tiny_image(".png")), "image/png")
        self.assertEqual(vision._sniff_mime(tiny_image(".jpg")), "image/jpeg")
        self.assertEqual(vision._sniff_mime(tiny_image(".bmp")), "image/bmp")
        self.assertEqual(vision._sniff_mime(tiny_image(".tiff")), "image/tiff")
        self.assertIsNone(vision._sniff_mime(b"not an image"))

    def test_supported_formats_pass_through(self):
        from routers import vision
        for ext, mime in ((".png", "image/png"), (".jpg", "image/jpeg"), (".webp", "image/webp")):
            data = tiny_image(ext)
            uri = vision._bytes_to_data_uri(data)
            self.assertTrue(uri.startswith("data:%s;base64," % mime))
            self.assertEqual(base64.b64decode(uri.split(",", 1)[1]), data)

    def test_bmp_tiff_converted_to_png(self):
        from routers import vision
        for ext in (".bmp", ".tiff"):
            uri = vision._bytes_to_data_uri(tiny_image(ext))
            self.assertTrue(uri.startswith("data:image/png;base64,"))
            converted = base64.b64decode(uri.split(",", 1)[1])
            self.assertEqual(converted[:8], b"\x89PNG\r\n\x1a\n")
            # Decodes back to a real image of the same dimensions.
            arr = cv2.imdecode(np.frombuffer(converted, np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual(arr.shape, (20, 30, 3))

    def test_vision_sends_actual_image_and_restrictions(self):
        from routers import vision
        png = tiny_image(".png")
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "study_original.png"), "wb") as fh:
                fh.write(png)
            with mock.patch.object(vision.store, "IMAGE_DIR", tmp):
                with mock.patch.object(orc.httpx, "post", return_value=ok_response("Joint space preserved.")) as post:
                    resp = self.client.post("/api/vision", json={
                        "filename": "study_original.png",
                        "record": RECORD,
                        "language": "Telugu",
                    })
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json(), {"observations": "Joint space preserved."})
        payload = post.call_args[1]["json"]
        self.assertEqual(payload["model"], "test/vision-model:free")
        self.assertEqual(payload["max_tokens"], orc.VISION_MAX_TOKENS)
        system, user = payload["messages"]
        # Clinical observation-only restrictions intact.
        self.assertIn("never state a diagnosis", system["content"])
        self.assertIn("Respond in Telugu", system["content"])
        # Multimodal structure: text part + image_url part with the real bytes.
        self.assertEqual(user["content"][0]["type"], "text")
        image_part = user["content"][1]
        self.assertEqual(image_part["type"], "image_url")
        url = image_part["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(url.split(",", 1)[1]), png)

    def test_vision_production_resolution_path(self):
        from routers import vision
        jpeg = tiny_image(".jpg")
        fake = httpx.Response(
            200, content=jpeg, headers={"content-type": "image/jpeg"},
            request=httpx.Request("GET", "https://storage.example/img.jpg"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(vision.store, "IMAGE_DIR", tmp):
                with mock.patch.object(vision.db, "get_image_url", return_value="https://storage.example/img.jpg"):
                    with mock.patch.object(vision.httpx, "get", return_value=fake):
                        uri = vision._resolve_image_data_uri("remote_original.jpg")
        self.assertTrue(uri.startswith("data:image/jpeg;base64,"))
        self.assertEqual(base64.b64decode(uri.split(",", 1)[1]), jpeg)

    def test_vision_missing_image_404(self):
        from routers import vision
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(vision.store, "IMAGE_DIR", tmp):
                with mock.patch.object(vision.db, "get_image_url", return_value=""):
                    resp = self.client.post("/api/vision", json={"filename": "nope.png"})
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
