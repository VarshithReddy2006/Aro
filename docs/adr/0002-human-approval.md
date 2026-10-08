# ADR 0002: Human approval

AI may summarize evidence and propose an allowlisted action, but cannot execute consequential actions directly.

Approval binds the authenticated operator, exact proposal hash, current case version, allowed action, and non-expired approval window. Execution is idempotent and auditable.
