"""Manual smoke check for the profile loader, against the real shipped directories.

This exercises the one path the unit suite deliberately never touches: Q7's
CWD-relative `root` default. Every test in `tests/test_profile.py` passes an
explicit `root` (`tmp_path`, or a `profiles/` path derived from `__file__`),
because a test that depended on the working directory would be a test of the
runner rather than of the loader. That leaves the default itself unexercised,
and the default is what a REPL or `scripts/` user gets. So: run from the repo
root, pass no root, and see what happens.

    uv run python scripts/smoke_profile.py                 # both shipped profiles
    uv run python scripts/smoke_profile.py mortgage-broker # just one
    uv run python scripts/smoke_profile.py ../x            # the rejection path

Manual on purpose -- there is no automated test for this script, the same stance
the bridge slice took for its smoke. It is a thing a human runs and reads.

Note this is NOT a check of the prompt CONTENT. Everything under `profiles/` is
DRAFT placeholder text; the owner authors the real wording before S7.
"""

from __future__ import annotations

import sys

from decana.profile.load import ProfileError, load_profile
from decana.profile.model import Profile

SHIPPED = ("mortgage-broker", "eco-consultant")
_EXCERPT = 48


def _excerpt(text: str) -> str:
    """First line of a prompt, clipped -- enough to tell three prompts apart."""
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= _EXCERPT else f"{line[:_EXCERPT]}..."


def _sms_summary(profile: Profile) -> str:
    """Each outcome that sends an SMS, with the link keys its template resolves."""
    if not profile.sms:
        return "(none)"
    return ", ".join(
        f"{outcome}[{'+'.join(sorted(template.links))}]"
        for outcome, template in sorted(profile.sms.items())
    )


def _describe(profile: Profile) -> str:
    return " | ".join(
        [
            f"name={profile.name}",
            f"display={profile.display_name}",
            f"phone={profile.phone_number}",
            f"sender={profile.sms_sender_id}",
            f"operator={profile.operator_email}",
            f"outcomes={','.join(profile.outcomes)}",
            f"sms={_sms_summary(profile)}",
            f"disclosure={_excerpt(profile.disclosure)!r}",
            f"conversation={_excerpt(profile.conversation)!r}",
            f"analysis={_excerpt(profile.analysis)!r}",
        ]
    )


def main(argv: list[str]) -> int:
    names = argv or list(SHIPPED)
    for name in names:
        try:
            # No `root`: this is the point of the script (Q7).
            profile = load_profile(name)
        except ProfileError as exc:
            print(f"REJECTED {name!r}: {exc}")
            return 1
        print(_describe(profile))

    print()
    print("VERIFY BY EYE:")
    print("  1. One line per profile above, and no traceback.")
    print("  2. Every field differs between the two profiles except the model names.")
    print("  3. Each SMS outcome lists the link keys its template actually uses.")
    print("  4. The three prompt excerpts differ from each other within a profile.")
    print("  Then re-run as: uv run python scripts/smoke_profile.py ../x")
    print("  and confirm it prints a ProfileError naming '../x' and exits 1.")
    print("  Reply DONE or FAIL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
