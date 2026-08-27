"""Tests for the Twilio leg.

Every test's docstring opens with its behavior id from the ratified id set in
`.claude/overseer/slice/twilio-server.md`. The exit criterion is a property over
that set in both directions: every id has a passing node, and no node here fails
to trace to an id.
"""

import xml.etree.ElementTree as ET
from dataclasses import replace
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


def test_s6b_say_carries_the_disclosure_and_stream_points_at_media(
    app: FastAPI, profile: Profile
) -> None:
    """S6.b -- Say's text equals the disclosure exactly; Stream/@url is {public_wss_url}/media.

    Equality, not containment: a truncated or wrapped disclosure still "contains"
    the compliance wording while changing what the caller hears, and the whole
    point of the non-generative disclosure is that it is spoken verbatim.
    """
    client = TestClient(app)

    response = client.post(
        "/voice", data={"CallSid": "CA-s6b", "From": "+447700900123"}
    )

    root = ET.fromstring(response.text)
    say = root.find("Say")
    assert say is not None
    assert say.text == profile.disclosure

    stream = root.find("Connect/Stream")
    assert stream is not None
    assert stream.get("url") == "wss://example.test/media"

    parameter = stream.find("Parameter")
    assert parameter is not None
    assert parameter.get("name") == "caller"
    assert parameter.get("value") == "+447700900123"


def test_s6c_hostile_disclosure_and_caller_still_produce_parsable_twiml(
    tmp_path: Path, profile: Profile
) -> None:
    """S6.c -- a disclosure and From containing &, <, > and quotes still parse, and round-trip.

    This is the test an f-string implementation fails. `"<Say>" in body` passes for
    a document with a raw `&` in it; `ET.fromstring` does not, and neither does an
    equality check on the round-tripped text.
    """
    hostile_disclosure = 'Smith & Co <adviser> says "hello" — 100% sure'
    hostile_caller = '+44 "x" & <y>'
    hostile_profile = replace(profile, disclosure=hostile_disclosure)

    async def _never_called(_profile: Profile) -> NoReturn:
        raise AssertionError("live_factory must not run for these tests")

    async def _on_call_end(_record: CallRecord) -> None:  # pragma: no cover
        return None

    app = create_app(
        hostile_profile,
        _never_called,
        _on_call_end,
        public_wss_url="wss://example.test",
        artifact_dir=tmp_path,
    )
    client = TestClient(app)

    response = client.post("/voice", data={"CallSid": "CA-s6c", "From": hostile_caller})

    root = ET.fromstring(response.text)
    say = root.find("Say")
    assert say is not None
    assert say.text == hostile_disclosure

    parameter = root.find("Connect/Stream/Parameter")
    assert parameter is not None
    assert parameter.get("value") == hostile_caller
