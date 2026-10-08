# Aro API

Planned runtime: AWS API Gateway + Lambda, with a shared application/domain layer for HTTP and MCP.

Endpoints: `POST /webhooks/ring`, `GET /api/cases`, `GET /api/cases/{id}`, `POST /api/cases/{id}/brief`, `POST /api/cases/{id}/approve`, `POST /api/cases/{id}/reject`, `POST /api/cases/{id}/execute`, `GET /api/cases/{id}/timeline`, `GET /api/cases/{id}/evidence`, `POST /api/cases/{id}/close`, `GET /health`.

Keep adapters thin; business rules live in application services/policies.
