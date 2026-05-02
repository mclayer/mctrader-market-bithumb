"""Repo policy lint test — ADR-008 D5 enforcement (no secret-related imports/literals).

Source tree must NOT use ``os.getenv`` / ``os.environ`` / ``Authorization`` / 1Password helpers.
"""

from __future__ import annotations

from pathlib import Path

SRC_ROOT = Path(__file__).parent.parent / "src" / "mctrader_market_bithumb"

FORBIDDEN_LITERALS = (
    "os.getenv",
    "os.environ",
    "Authorization",  # CRITICAL: forbidden in source — only the policy guard whitelists it
    "Api-Key",
    "Api-Sign",
    "from onepassword",
    "import onepassword",
    "1password",
    "X-BITHUMB-Api-Key",
    "X-BITHUMB-Api-Sign",
)

# Allowlisted files: must contain literal references inside string/list (guard implementation).
ALLOWLIST = {
    "exceptions.py": (),
    "client.py": ("Authorization", "Api-Key", "Api-Sign", "X-BITHUMB-Api-Key", "X-BITHUMB-Api-Sign"),
    "__init__.py": (),
}


def test_no_forbidden_imports_or_literals_in_source() -> None:
    violations: list[str] = []
    for source_file in SRC_ROOT.rglob("*.py"):
        text = source_file.read_text(encoding="utf-8")
        allowed = ALLOWLIST.get(source_file.name, ())
        for literal in FORBIDDEN_LITERALS:
            if literal in text and literal not in allowed:
                violations.append(f"{source_file.relative_to(SRC_ROOT)}: forbidden literal {literal!r}")
    assert not violations, "\n".join(violations)


def test_no_1password_dependency() -> None:
    pyproject = (SRC_ROOT.parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert "onepassword" not in pyproject.lower()
    assert '"op"' not in pyproject
    assert '"cryptography"' not in pyproject
