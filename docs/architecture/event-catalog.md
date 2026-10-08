# Event catalog — initial draft

| Event | Source | Purpose | Idempotency key |
|---|---|---|---|
| `ring.event.received` | Ring | raw verified event accepted | Ring event/request id |
| `case.created` | Aro | create operational case | event id |
| `case.context.ready` | Aro | context assembled | case version |
| `brief.generated` | Bedrock/Aro | factual brief validated | case version |
| `proposal.created` | Aro | allowlisted action proposal | proposal hash |
| `approval.recorded` | Human | bind approval to proposal | approval id |
| `action.requested` | Aro | begin approved action | action id |
| `action.completed` | Adapter | confirm outcome | action id |
| `case.closed` | Human/system | close case | case version |
