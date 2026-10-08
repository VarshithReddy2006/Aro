# Trust boundary — initial draft

**Untrusted/external:** Ring event payloads, external callbacks, model output, notification provider responses.

**Trusted application boundary:** authenticated operator identity, deterministic policy engine, case state machine, approval validator, action executor.

**Sensitive stores:** DynamoDB case/audit state, S3 evidence, SSM secrets/configuration.

Rule: model output never crosses directly into consequential execution. It must pass schema validation, allowlist validation, policy checks, and human approval.
