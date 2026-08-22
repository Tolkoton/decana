# Overseer escalations log

Records every PRODUCT_DECISION / BLOCKER_CLASSIFICATION / DESIGN_FORK /
ADR_RATIFICATION escalation and the human's resolution. Used in the
2-week audit to tune escalation thresholds.

## Entry format

```
## <ISO timestamp UTC> — <category> — <slice slug>
- Question: <text>
- Options offered: <list>
- Recommendation: <overseer's pick + one-line rationale>
- Human chose: <final decision>
- Latency to decision: <minutes/hours>
- Notes: <if human changed mind, if recommendation was wrong, etc.>
```

## Audit signal interpretation (re-read at the 2-week mark)

- **Human waved through immediately, picked recommendation as-is** → next
  time, this class of question can likely be handled without escalation.
  Propose change in audit.md.
- **Human reversed the recommendation** → overseer is over-confident on
  this class. Tune the check prompt; consider weakening the recommendation
  language.
- **Human deliberated long, chose other** → correct escalation, healthy
  use of human time.

---

(no entries yet)
