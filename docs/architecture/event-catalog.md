# Event catalog — initial draft

| Event | Source | Purpose | Idempotency key |
|---|---|---|---|
| `ring.event.received` | Ring | raw verified event accepted | Ring event/request id |
| `case.created` | ParcelProof | create operational case | event id |
| `case.context.ready` | ParcelProof | context assembled | case version |
| `brief.generated` | Bedrock/ParcelProof | factual brief validated | case version |
| `proposal.created` | ParcelProof | allowlisted action proposal | proposal hash |
| `approval.recorded` | Human | bind approval to proposal | approval id |
| `action.requested` | ParcelProof | begin approved action | action id |
| `action.completed` | Adapter | confirm outcome | action id |
| `case.closed` | Human/system | close case | case version |
