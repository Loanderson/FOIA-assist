"""Model clients for the three ways agencies usually reach a model: the OpenAI
API, Azure OpenAI in a government cloud, and an OpenAI-compatible server on
their own network. All return parsed JSON that matches a schema."""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config" / "endpoints.json"


class ModelError(Exception):
    pass


def load_endpoints(path: str | Path = CONFIG) -> dict:
    cfg = json.loads(Path(path).read_text())
    return {"default": cfg["default"], "endpoints": {e["name"]: e for e in cfg["endpoints"]}}


class ChatClient:
    """OpenAI-compatible chat completions with structured outputs."""

    def __init__(self, endpoint: dict, opener=None, timeout_s: float = 60):
        self.e = endpoint
        self.timeout_s = timeout_s
        self._open = opener or urllib.request.urlopen

    def _request(self, body: dict) -> urllib.request.Request:
        key = os.environ.get(self.e.get("api_key_env", ""), "")
        if self.e["kind"] == "azure":
            url = (f"{self.e['base_url'].rstrip('/')}/openai/deployments/{self.e['deployment']}"
                   f"/chat/completions?api-version={self.e['api_version']}")
            headers = {"api-key": key}
        else:
            url = f"{self.e['base_url'].rstrip('/')}/chat/completions"
            headers = {"Authorization": f"Bearer {key}"}
            body = {"model": self.e["model"], **body}
        headers["Content-Type"] = "application/json"
        return urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")

    def complete_json(self, system: str, user: str, schema: dict, name: str) -> tuple[dict, dict]:
        body = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": name, "schema": schema, "strict": True}},
        }
        try:
            with self._open(self._request(body), timeout=self.timeout_s) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise ModelError(f"HTTP {e.code} from {self.e['name']}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise ModelError(f"{self.e['name']} unreachable: {e}") from e
        msg = data["choices"][0]["message"]
        if msg.get("refusal"):
            raise ModelError(f"model refused: {msg['refusal']}")
        try:
            parsed = json.loads(msg["content"])
        except (TypeError, json.JSONDecodeError) as e:
            raise ModelError("model returned non-JSON content") from e
        return parsed, data.get("usage") or {}
