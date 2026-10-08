# Application services

- ingestion_service.py — HMAC verification, replay protection, validation, dedupe, normalization
- case_service.py — case creation, context assembly, state transitions
- brief_service.py — bounded Bedrock request + strict response validation
- approval_service.py — proposal hash binding, expiry, authorization, version checks
- action_service.py — allowlisted idempotent execution + audit records
- evidence_service.py — S3 evidence bundle creation and hashing
