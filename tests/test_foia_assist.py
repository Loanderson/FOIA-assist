import io
import json
import threading
import unittest
import urllib.error
import urllib.request

from foia_assist import policy, prescreen, triage
from foia_assist.corpus import Document, load, parse
from foia_assist.gateway import AuditLog, Gateway
from foia_assist.llm import ChatClient, ModelError
from foia_assist.pipeline import Assistant
from foia_assist.search import Index

DOCS = load()
BY_ID = {d.id: d for d in DOCS}


def doc(body, marking="INTERNAL", status="final"):
    return Document("T-1", "t", "2025-01-01", "o", "memo", marking, status, body)


class PolicyTests(unittest.TestCase):
    def test_ordering(self):
        self.assertTrue(policy.allowed("PUBLIC", "CUI"))
        self.assertFalse(policy.allowed("CUI", "INTERNAL"))
        self.assertEqual(policy.max_level(["PUBLIC", "CUI", "INTERNAL"]), "CUI")

    def test_unknown_marking_rejected_at_load(self):
        with self.assertRaises(ValueError):
            parse("---\nid: X\ntitle: t\ndate: 2025-01-01\noffice: o\ntype: memo\nmarking: SECRET\nstatus: final\n---\nbody")

    def test_check_raises(self):
        with self.assertRaises(policy.PolicyViolation):
            policy.check(["PUBLIC", "CUI"], {"name": "x", "authorized_level": "INTERNAL"})


class SearchTests(unittest.TestCase):
    def test_finds_audit_by_synonym(self):
        hits = Index(DOCS).search("inspector general review of improper payments")
        self.assertEqual(hits[0][0].id, "FGA-005")

    def test_year_filter(self):
        hits = Index(DOCS).search("performance report", years=(2025, 2025))
        self.assertNotIn("FGA-009", [d.id for d, _, _ in hits])


class PrescreenTests(unittest.TestCase):
    def test_ssn_and_dob(self):
        kinds = {f.reason for f in prescreen.screen(BY_ID["FGA-005"])}
        self.assertIn("Social Security number", kinds)
        self.assertIn("Date of birth", kinds)

    def test_gov_email_not_flagged_personal_is(self):
        flags = [f.text for f in prescreen.screen(BY_ID["FGA-004"]) if f.reason == "Personal email address"]
        self.assertEqual(flags, ["dwilliams.coop@gmail.com"])

    def test_draft_flags_b5(self):
        self.assertIn("b(5)", {f.exemption for f in prescreen.screen(BY_ID["FGA-006"])})

    def test_redaction_replaces_spans(self):
        d = doc("Call (555) 555-0100 or write 12 Elm Street.")
        out = prescreen.redact(d, prescreen.screen(d))
        self.assertNotIn("555-0100", out)
        self.assertNotIn("Elm Street", out)
        self.assertEqual(out.count("[b(6)]"), 2)


class TriageTests(unittest.TestCase):
    def test_fiscal_year_is_not_a_date_filter(self):
        self.assertEqual(triage.years("budget for fiscal year 2026"), (None, None))
        self.assertEqual(triage.years("FY2026 budget written in 2025"), (2025, 2025))

    def test_since(self):
        self.assertEqual(triage.years("since 2024"), (2024, triage.CURRENT_YEAR))

    def test_vague_request(self):
        t = triage.rules("I want all emails.")
        self.assertTrue(t["needs_clarification"])
        self.assertTrue(t["clarification_question"])

    def test_fee_category_is_deterministic(self):
        self.assertEqual(triage.fee_category("media"), "news media")
        self.assertEqual(triage.fee_category("anything"), "all other")


class FakeClient:
    def __init__(self):
        self.sent = []

    def complete_json(self, system, user, schema, name):
        self.sent.append(user)
        if name == "foia_triage":
            return triage.rules(user), {}
        return {"responsive": "likely", "reason": "matches"}, {"total_tokens": 10}


def public_assistant(client):
    eps = {"default": "pub", "endpoints": {"pub": {"name": "pub", "kind": "openai", "authorized_level": "PUBLIC"}}}
    audit = AuditLog(None)
    return Assistant(DOCS, eps, audit, {"pub": client}), audit


class GatewayAndPipelineTests(unittest.TestCase):
    def test_restricted_records_never_reach_public_endpoint(self):
        client = FakeClient()
        a, audit = public_assistant(client)
        p = a.process("Any audit or investigation of improper payments in the broadband program.", "media")
        cui = next(c for c in p["candidates"] if c["id"] == "FGA-005")
        self.assertEqual(cui["note_source"], "withheld")
        self.assertFalse(any("219-09-9999" in s for s in client.sent))
        self.assertTrue(any(r["event"] == "record_withheld_from_model" for r in audit.records))
        public = [c for c in p["candidates"] if c["marking"] == "PUBLIC"]
        self.assertTrue(public and all(c["note_source"] == "model" for c in public))

    def test_blocked_attempt_is_audited(self):
        audit = AuditLog(None)
        gw = Gateway({"name": "pub", "kind": "openai", "authorized_level": "PUBLIC"}, audit, FakeClient())
        secret = "SUBJECT SSN 219-09-9999"
        with self.assertRaises(policy.PolicyViolation):
            gw.ask("R", "x", "system", secret, {}, sources=[("FGA-005", "CUI")])
        self.assertEqual(audit.records[-1]["event"], "model_call_blocked")
        self.assertNotIn("219-09-9999", json.dumps(audit.records))  # audit holds IDs and hashes, not content

    def test_offline_needs_no_network(self):
        p = Assistant(DOCS, audit=AuditLog(None)).process("water infrastructure funding notice 2025")
        self.assertEqual(p["candidates"][0]["id"], "FGA-013")
        self.assertTrue(all(c["note_source"] == "rules" for c in p["candidates"]))

    def test_vague_request_skips_search(self):
        p = Assistant(DOCS, audit=AuditLog(None)).process("I want all emails.")
        self.assertEqual(p["candidates"], [])
        self.assertIn("clarification", p["acknowledgment_letter"])


class ChatClientTests(unittest.TestCase):
    def capture(self, payload=None, error=None):
        def opener(req, timeout):
            self.req = req
            if error:
                raise error
            return io.BytesIO(json.dumps(payload).encode())
        return opener

    def ok(self, content):
        return {"choices": [{"message": {"content": json.dumps(content)}}], "usage": {"total_tokens": 5}}

    def test_azure_url_and_header(self):
        e = {"name": "az", "kind": "azure", "base_url": "https://r.openai.azure.us", "deployment": "d",
             "api_version": "2024-10-21", "api_key_env": "NOPE"}
        out, _ = ChatClient(e, self.capture(self.ok({"a": 1}))).complete_json("s", "u", {}, "n")
        self.assertEqual(out, {"a": 1})
        self.assertIn("/openai/deployments/d/chat/completions?api-version=2024-10-21", self.req.full_url)
        self.assertIn("Api-key", self.req.headers)
        self.assertEqual(json.loads(self.req.data)["response_format"]["json_schema"]["strict"], True)

    def test_openai_compatible_sends_model(self):
        e = {"name": "o", "kind": "openai", "base_url": "http://llm.local/v1", "model": "m", "api_key_env": "NOPE"}
        ChatClient(e, self.capture(self.ok({}))).complete_json("s", "u", {}, "n")
        self.assertTrue(self.req.full_url.endswith("/v1/chat/completions"))
        self.assertEqual(json.loads(self.req.data)["model"], "m")

    def test_refusal_and_http_errors(self):
        e = {"name": "o", "kind": "openai", "base_url": "http://x/v1", "model": "m"}
        refusal = {"choices": [{"message": {"content": None, "refusal": "no"}}]}
        with self.assertRaises(ModelError):
            ChatClient(e, self.capture(refusal)).complete_json("s", "u", {}, "n")
        err = urllib.error.HTTPError("u", 500, "x", {}, io.BytesIO(b""))
        with self.assertRaises(ModelError):
            ChatClient(e, self.capture(error=err)).complete_json("s", "u", {}, "n")


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        from foia_assist.server import make_handler
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Assistant(DOCS, audit=AuditLog(None))))
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def post(self, body):
        req = urllib.request.Request(self.base + "/api/process", data=json.dumps(body).encode(), method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read()), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read()), {}

    def test_process_and_headers(self):
        code, body, headers = self.post({"request": "rural broadband awards 2025", "requester_type": "media"})
        self.assertEqual(code, 200)
        self.assertTrue(body["candidates"])
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

    def test_validation(self):
        self.assertEqual(self.post({})[0], 400)
        self.assertEqual(self.post({"request": "x", "endpoint": "nope"})[0], 400)


if __name__ == "__main__":
    unittest.main()
