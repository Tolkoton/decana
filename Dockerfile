# S6 deliverable. Runs the `decana` script entry with PORT honoured (Edge S3 -> S6).
#
# WHY uv, and why a two-stage build: the lockfile is the dependency contract this
# repo validates against, so the image installs from `uv.lock` rather than
# re-resolving. The builder stage carries the toolchain; the runtime stage does
# not, which keeps the shipped image to the interpreter plus site-packages.
#
# WHY DECANA_PROFILES_ROOT is set explicitly here: `Settings.profiles_root`
# defaults to `<repo root>/profiles` resolved from `decana.__file__`, which
# assumes an EDITABLE install. This image is not editable, so the default would
# point inside site-packages and `load_profile` would not find the directory.
# profile-loader W-1 and the S3 entry both flagged this; setting it in the image
# means the deploy command does not have to remember.

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, in their own layer: they change far less often than source,
# so an edit to src/ does not re-install numpy and soxr.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

# README.md is project metadata (`readme = "README.md"` in pyproject.toml), so the
# build backend opens it when it builds the `decana` package in the next step.
# Without it the first Cloud Build died: "failed to open file `/app/README.md`".
# `.dockerignore` re-includes it for the same reason.
COPY src/ ./src/
COPY README.md ./
RUN uv sync --locked --no-dev


FROM python:3.13-slim AS runtime

# Non-root: nothing here needs to write outside DECANA_ARTIFACT_DIR.
RUN useradd --create-home --uid 10001 decana

WORKDIR /app

COPY --from=builder --chown=decana:decana /app/.venv /app/.venv
COPY --chown=decana:decana src/ ./src/
COPY --chown=decana:decana profiles/ ./profiles/

# Two directories, deliberately: `calls` is where dispatch writes three files
# per call and is a Cloud Storage FUSE mount in production; `timing` takes the
# per-chunk `{call_sid}.jsonl` appends and MUST stay on local disk (see
# `Settings.timing_dir`). Both absolute and writable by the non-root user.
RUN mkdir -p /app/artifacts/calls /app/artifacts/timing \
    && chown -R decana:decana /app/artifacts

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DECANA_PROFILES_ROOT=/app/profiles \
    DECANA_ARTIFACT_DIR=/app/artifacts/calls \
    DECANA_TIMING_DIR=/app/artifacts/timing

USER decana

# Cloud Run injects PORT; `Settings.port` reads it and defaults to 8080. No flag
# needed here, and none should be added -- a hardcoded port would ignore PORT.
EXPOSE 8080

CMD ["decana"]
