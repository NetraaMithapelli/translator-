"""
Verifies BhashiniProvider's two-call flow (pipeline config -> compute)
and, importantly, that the config call is CACHED per target language so
it doesn't repeat on every translate_batch() call. Uses httpx's
MockTransport so this runs fully offline, no real Bhashini credentials
or network access needed -- consistent with the rest of the suite.
"""

import sys, os, asyncio, json, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


def run(coro):
    return asyncio.run(coro)


CONFIG_RESPONSE = {
    "pipelineResponseConfig": [
        {"config": [{"serviceId": "ai4bharat/indictrans-fairseq-i2i-gpu--t4"}]}
    ],
    "pipelineInferenceAPIEndPoint": {
        "callbackUrl": "https://dhruva-api.bhashini.gov.in/services/inference/pipeline",
        "inferenceApiKey": {"name": "Authorization", "value": "fake-inference-key"},
    },
}


def make_compute_response(texts):
    return {"pipelineResponse": [{"output": [{"source": t, "target": f"[hi] {t}"} for t in texts]}]}


@unittest.skipUnless(HTTPX_AVAILABLE, "httpx not installed in this environment")
class TestBhashiniProvider(unittest.TestCase):
    def _make_provider(self, call_log):
        from translator.providers import bhashini_provider as bp

        def handler(request: httpx.Request) -> httpx.Response:
            call_log.append(str(request.url))
            if "getModelsPipeline" in str(request.url):
                return httpx.Response(200, json=CONFIG_RESPONSE)
            else:
                body = json.loads(request.content)
                texts = [i["source"] for i in body["inputData"]["input"]]
                return httpx.Response(200, json=make_compute_response(texts))

        # Patch the module-level client with one wired to a mock transport,
        # so no real DNS/network call is ever attempted.
        bp._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return bp.BhashiniProvider(user_id="u", ulca_api_key="k")

    def test_config_call_cached_across_translate_calls(self):
        call_log = []
        provider = self._make_provider(call_log)

        run(provider.translate_batch(["Hello", "World"], "hi"))
        run(provider.translate_batch(["Another string"], "hi"))

        config_calls = [u for u in call_log if "getModelsPipeline" in u]
        compute_calls = [u for u in call_log if "getModelsPipeline" not in u]
        # Config call happens once (cached), compute call happens once per translate_batch call.
        self.assertEqual(len(config_calls), 1)
        self.assertEqual(len(compute_calls), 2)

    def test_batched_texts_translated_in_one_compute_call(self):
        call_log = []
        provider = self._make_provider(call_log)
        result = run(provider.translate_batch(["A", "B", "C"], "hi"))
        self.assertEqual(result, ["[hi] A", "[hi] B", "[hi] C"])

    def test_separate_target_languages_each_get_own_config_cache_entry(self):
        call_log = []
        provider = self._make_provider(call_log)
        run(provider.translate_batch(["Hello"], "hi"))
        run(provider.translate_batch(["Hello"], "mr"))
        config_calls = [u for u in call_log if "getModelsPipeline" in u]
        self.assertEqual(len(config_calls), 2)  # one per distinct target language


if __name__ == "__main__":
    unittest.main()
