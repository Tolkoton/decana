"""Tests for the Twilio leg.

Every test's docstring opens with its behavior id from the ratified id set in
`.claude/overseer/slice/twilio-server.md`. The exit criterion is a property over
that set in both directions: every id has a passing node, and no node here fails
to trace to an id.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NoReturn

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from decana.profile.load import load_profile
from decana.profile.model import Profile
from decana.twilio.records import CallRecord
from decana.twilio.server import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def profile() -> Profile:
    return load_profile("mortgage-broker", root=REPO_ROOT / "profiles")


@pytest.fixture
def app(profile: Profile, tmp_path: Path) -> FastAPI:
    async def _never_called(_profile: Profile) -> NoReturn:
        raise AssertionError("live_factory must not run for these tests")

    async def _on_call_end(_record: CallRecord) -> None:  # pragma: no cover
        return None

    return create_app(
        profile,
        _never_called,
        _on_call_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )


def test_s6a_twiml_parses_with_the_expected_element_structure(app: FastAPI) -> None:
    """S6.a -- the TwiML parses as Response/Say + Response/Connect/Stream/Parameter.

    Parsed, not substring-matched: an f-string implementation that leaves a `&` in
    the disclosure unescaped still satisfies `"<Say>" in body` while producing a
    document Twilio cannot parse.
    """
    client = TestClient(app)

    response = client.post(
        "/voice",
        data={"CallSid": "CA-s6a", "From": "+447700900123"},
    )

    assert response.status_code == 200
    root = ET.fromstring(response.text)
    assert root.tag == "Response"
    assert root.find("Say") is not None
    stream = root.find("Connect/Stream")
    assert stream is not None
    assert stream.find("Parameter") is not None
