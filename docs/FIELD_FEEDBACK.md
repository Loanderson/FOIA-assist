# Field feedback log

What a deployment like this surfaces for Product, Engineering and Research. Each item has the evidence behind it and what would change.

| # | For | Observation | Evidence | Ask |
|---|---|---|---|---|
| F1 | Product | Agencies need to prove which content went to which endpoint, per request | `gateway.py` exists because there was no built-in way to attach handling levels to inputs and enforce them | Per-request data-classification metadata that is enforced and appears in usage logs |
| F2 | Research / Product | Date reasoning in triage is easy to get subtly wrong | Eval caught "fiscal year 2026" being treated as a record date; fixed in rules and spelled out in the model prompt | Include fiscal-year and "since X" cases in structured-extraction evals |
| F3 | Product | Pattern-based PII detection misses names | `evals/pii_labels.json`: "Laura Chen" missed; recall 87.5% | A PII/entity detection option that runs inside the authorization boundary |
| F4 | Engineering | Disconnected sites need an equivalent offline path | The `offline` endpoint covers triage and search without a model; quality gap measured by the same evals | Guidance and reference configs for on-prem / disconnected deployments |
| F5 | Product | Reviewers will ask "why did the model say this?" | Hypothesis to test in the pilot: pattern flags show the exact span (`prescreen.py`), while model notes are free text and harder to verify | Structured outputs that cite spans of the input by offset |

## Notes on method

- Every item points at a file, a metric or a test so it can be checked.
- Items are written once per pattern, not once per customer. If three agencies raise F1, it gets one row with three evidence links.
