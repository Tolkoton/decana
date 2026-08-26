# Build progress

One entry per completed slice, newest first. Planning artifacts live in
`.claude/overseer/slice/`; this file is the short version — what shipped, what
surprised us, and what the next slice inherits.

## Slice S1 — profile-loader (DONE 2026-08-26)

Feature `vertical-profile-bridge`, slice S1. Contract:
`.claude/overseer/slice/profile-loader.md`.

- **Modules:** `src/decana/profile/model.py` (~111 LOC — `Profile`, `SmsTemplate`),
  `src/decana/profile/load.py` (~466 LOC — `load_profile`, `ProfileError`, `SCHEMA`).
  Data: `profiles/mortgage-broker/`, `profiles/eco-consultant/`, each `profile.toml`
  plus three DRAFT-marked prompt files.
- **Tests:** `tests/test_profile.py`, 89 nodes, all green. Integration-only —
  every one goes through `load_profile` against a directory on disk; no bare-helper
  tests. Node ids diff clean against the artifact's ratified list in both
  directions (no missing row, no unratified extra). Suite total 155.
- **Smoke:** `scripts/smoke_profile.py` — passed, owner reported DONE 2026-08-26.
  Both shipped profiles load with no `root` argument from the repo root (the one
  path the unit tests deliberately never take, Q7), and `../x` is rejected with a
  `ProfileError` naming the argument, exit 1.
- **Checks:** `ruff check`, `ruff format --check`, `mypy --strict` clean.

### Surprises

- **The DRAFT marker was a latent production defect, not a cosmetic one.**
  Q11 and P5 required every prompt file to *open* with
  `<!-- DRAFT — owner to review before S7 -->`, while the S3 contract feeds
  `profile.disclosure` verbatim into TwiML `<Say>`. The marker would have been
  read aloud to the caller — and because P5 pinned it, it would have outlived the
  draft text it was written for and reached real client calls. Escalated rather
  than patched (it amends ratified text and adds exit-criterion ids); owner chose
  to strip the comment at load. Recorded as Q15, risk as W-2.
- **Two assertions were only proven by breaking the code on purpose.** Seam 4
  (V1/V4) and the strip rule (W7/W8) both passed on arrival, which is not the
  same as being right. Mutation-checked: the aliasing bug leaves 73 of 75 tests
  green and is caught only by V1 and V4; an unanchored strip pattern is caught
  only by W8; a *greedy* strip pattern survived the entire suite until W7's
  fixture was given a second comment to protect. All restores diff-verified
  byte-identical.
- **A mutation run that appears to prove something can prove nothing.** The first
  Seam-5 attempt was shell-escaped wrong, the guard `assert` failed, and the
  suite ran against unmutated code showing a meaningless pass. Worth re-reading
  any mutation result for evidence the mutation actually landed.
- The planning artifact's "no toolchain on PATH" blocker was stale — the project
  runs through `uv run`, where 3.13.15 / ruff / mypy / pytest are all present.

### Open for the next slice

- **S3 owns the consequence of Q15.** `profile.disclosure` is now guaranteed free
  of a leading HTML comment, so the TwiML `<Say>` body is safe to interpolate
  directly. Nothing else needs to re-check it.
- **The prompt text is DRAFT.** The tracer may run on it; S7 step 7a may not. The
  owner authors the real wording before S7 — the `<!-- DRAFT -->` markers stay on
  disk (P5) and no longer reach the caller or the model.
- **Deferred, with triggers** (full list in the artifact): error aggregation — a
  second *real* vertical, or a non-developer editing profiles; `profile.toml`
  schema versioning — the first backward-incompatible field change after a
  profile is in production; per-outcome email templates and per-profile model
  parameters — a real vertical needing one.
- **W-1 still stands:** Q7's `profiles_root` default assumes an editable install.
  If S6's Dockerfile installs non-editable, set `DECANA_PROFILES_ROOT` explicitly
  and record it in `docs/deploy.md`.
