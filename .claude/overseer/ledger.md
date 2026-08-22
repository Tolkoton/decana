# Overseer ledger — append-only

Append one entry per overseer invocation. Newest at the top below this
header. Older entries below.

## Entry format

```
## <ISO timestamp UTC> — <slice slug> — <verdict>
- Trigger: <which check #N, or "none">
- Evidence: <transcript turn N / SHA abc1234 / file:line>
- Action: <one-line description>
- Category: strategy | recovery | optimization | none
```

Categories follow Trajectory-Informed Memory Generation (arXiv 2603.10600):
- **strategy** — developer pattern that worked, worth recording
- **recovery** — developer near-miss with successful course-correction
- **optimization** — inefficient pattern worth flagging next time
- **none** — routine entry, no pattern of note
