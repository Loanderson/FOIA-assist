"""Evaluate triage, retrieval, PII pre-screen and data-handling controls.

    python -m evals.run_evals            # offline rules (no network)
    python -m evals.run_evals --json out.json

Exits 1 if a release gate fails. The leakage gate runs the full pipeline
against a PUBLIC-only endpoint with a recording fake client, so it checks what
would actually have been sent, not what the code intended to send.
"""

import argparse
import json
from pathlib import Path

from foia_assist import policy, prescreen
from foia_assist.corpus import load
from foia_assist.gateway import AuditLog, Gateway
from foia_assist.pipeline import Assistant
from foia_assist.triage import rules

HERE = Path(__file__).resolve().parent

GATES = {
    "recall_at_5": (">=", 0.90),
    "track_accuracy": (">=", 0.80),
    "clarification_accuracy": (">=", 1.00),
    "high_severity_pii_recall": (">=", 1.00),   # SSNs and dates of birth
    "pii_recall": (">=", 0.85),
    "leaked_records": ("<=", 0),
    "unblocked_violations": ("<=", 0),
}


class RecordingClient:
    """Stands in for a model endpoint and records exactly what it was sent."""

    def __init__(self):
        self.prompts = []

    def complete_json(self, system, user, schema, name):
        self.prompts.append(user)
        if name == "foia_triage":
            text = user.split("<request>\n", 1)[1].split("\n</request>", 1)[0]
            return rules(text), {"prompt_tokens": 0, "completion_tokens": 0}
        return {"responsive": "possibly", "reason": "test"}, {}


def eval_triage_and_retrieval(assistant: Assistant, requests: list[dict]) -> tuple[dict, list[dict]]:
    rows = []
    for q in requests:
        p = assistant.process(q["text"], q["requester_type"], endpoint="offline", k=5)
        got = [c["id"] for c in p["candidates"]]
        t = p["triage"]
        rows.append({
            "id": q["id"],
            "recall": (len(set(got) & set(q["responsive"])) / len(q["responsive"])) if q["responsive"] else None,
            "missed": sorted(set(q["responsive"]) - set(got)),
            "track_ok": t["track"] == q["track"],
            "programs_ok": sorted(t["programs"]) == sorted(q["programs"]),
            "clar_ok": t["needs_clarification"] == q["needs_clarification"],
            "years": (t["start_year"], t["end_year"]),
        })
    scored = [r for r in rows if r["recall"] is not None]
    return {
        "recall_at_5": sum(r["recall"] for r in scored) / len(scored),
        "track_accuracy": sum(r["track_ok"] for r in rows) / len(rows),
        "program_accuracy": sum(r["programs_ok"] for r in rows) / len(rows),
        "clarification_accuracy": sum(r["clar_ok"] for r in rows) / len(rows),
    }, rows


def eval_pii(docs, labels: dict) -> tuple[dict, list[str]]:
    by_id = {d.id: d for d in docs}
    expected = found = tp = 0
    high_exp = high_tp = 0
    notes = []
    for doc_id, items in labels.items():
        if doc_id.startswith("_"):
            continue
        flagged = [f.text for f in prescreen.screen(by_id[doc_id]) if f.exemption == "b(6)"]
        found += len(flagged)
        for item in items:
            expected += 1
            hit = any(item.lower() in f.lower() or f.lower() in item.lower() for f in flagged)
            tp += hit
            high = "-" in item and item.replace("-", "").isdigit() or "birth" in item
            if high:
                high_exp += 1
                high_tp += hit
            if not hit:
                notes.append(f"missed in {doc_id}: {item!r}")
        for f in flagged:
            if not any(i.lower() in f.lower() or f.lower() in i.lower() for i in items):
                notes.append(f"extra flag in {doc_id}: {f!r}")
    return {"pii_recall": tp / expected, "pii_precision": tp / found if found else 1.0,
            "high_severity_pii_recall": high_tp / high_exp}, notes


def eval_leakage(docs, requests) -> dict:
    """Run every request through a PUBLIC-only endpoint and inspect what was sent."""
    client = RecordingClient()
    endpoints = {"default": "public-test", "endpoints": {"public-test": {
        "name": "public-test", "kind": "openai", "authorized_level": "PUBLIC"}}}
    audit = AuditLog(None)
    a = Assistant(docs, endpoints, audit, clients={"public-test": client})
    for q in requests:
        a.process(q["text"], q["requester_type"])
    restricted = {d.id: d for d in docs if d.marking != "PUBLIC"}
    leaked = sorted({doc_id for prompt in client.prompts for doc_id in restricted
                     if f'id="{doc_id}"' in prompt or restricted[doc_id].body[:60] in prompt})

    # Direct attempt: code that tries to push CUI at the endpoint must be stopped.
    gw = Gateway(endpoints["endpoints"]["public-test"], audit, client)
    unblocked = 0
    for d in docs:
        if d.marking == "PUBLIC":
            continue
        try:
            gw.ask("TEST", "attempt", "s", d.body, {}, sources=[(d.id, d.marking)])
            unblocked += 1
        except policy.PolicyViolation:
            pass
    return {
        "leaked_records": len(leaked),
        "unblocked_violations": unblocked,
        "records_withheld_from_model": sum(r["event"] == "record_withheld_from_model" for r in audit.records),
        "blocked_attempts_logged": sum(r["event"] == "model_call_blocked" for r in audit.records),
        "model_calls": sum(r["event"] == "model_call" for r in audit.records),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    docs = load()
    requests = json.loads((HERE / "requests.json").read_text())
    labels = json.loads((HERE / "pii_labels.json").read_text())

    m1, rows = eval_triage_and_retrieval(Assistant(docs, audit=AuditLog(None)), requests)
    m2, pii_notes = eval_pii(docs, labels)
    m3 = eval_leakage(docs, requests)
    metrics = {**m1, **m2, **m3}

    print(f"\nFOIA assistant eval · {len(requests)} requests · {len(docs)} records\n")
    print("Release gates")
    failed = False
    for k, (op, target) in GATES.items():
        v = metrics[k]
        ok = v >= target if op == ">=" else v <= target
        failed |= not ok
        shown = f"{v:.1%}" if isinstance(v, float) else str(v)
        tgt = f"{target:.0%}" if isinstance(target, float) else str(target)
        print(f"  [{'PASS' if ok else 'FAIL'}] {k:<26} {shown:>7}   (target {op} {tgt})")
    print(f"\n  program_accuracy           {metrics['program_accuracy']:.1%}")
    print(f"  pii_precision              {metrics['pii_precision']:.1%}")
    print(f"  model calls in leak test   {metrics['model_calls']}  ·  records withheld {metrics['records_withheld_from_model']}"
          f"  ·  blocked attempts logged {metrics['blocked_attempts_logged']}")

    misses = [r for r in rows if r["missed"] or not r["track_ok"] or not r["clar_ok"]]
    if misses:
        print("\nTriage / retrieval misses")
        for r in misses:
            bits = []
            if r["missed"]:
                bits.append(f"missed {', '.join(r['missed'])} (years filter {r['years']})")
            if not r["track_ok"]:
                bits.append("wrong track")
            if not r["clar_ok"]:
                bits.append("wrong clarification call")
            print(f"  {r['id']}: " + "; ".join(bits))
    if pii_notes:
        print("\nPII pre-screen notes")
        for n in pii_notes:
            print(f"  {n}")

    print(f"\n{'GATES FAILED' if failed else 'ALL GATES PASSED'}\n")
    if args.json:
        Path(args.json).write_text(json.dumps({"metrics": metrics, "rows": rows, "pii_notes": pii_notes}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
