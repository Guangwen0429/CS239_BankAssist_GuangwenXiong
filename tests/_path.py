"""Shared test helpers.

Importing this module puts ``<repo>/src`` on ``sys.path`` so the tests can
``import bankassist`` without installing anything.  It also provides a helper
that removes the optional LLM environment variables, so that the rule-based
tests behave the same on a machine where an LLM endpoint happens to be
configured.
"""

from __future__ import annotations

import os
import sys
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SRC_DIR = os.path.join(REPO_ROOT, "src")

# keep the tests from dropping __pycache__ folders into src/
sys.dont_write_bytecode = True

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

LLM_ENV_VARS = ("BANKASSIST_LLM_BASE_URL", "BANKASSIST_LLM_MODEL", "BANKASSIST_LLM_API_KEY")


def rules_only_env() -> mock._patch_dict:
    """Context manager / patcher that hides the LLM env vars (rule-based Concierge)."""
    env = {k: v for k, v in os.environ.items() if k not in LLM_ENV_VARS}
    return mock.patch.dict(os.environ, env, clear=True)


class RulesOnlyTestCase:
    """Mixin for unittest.TestCase: every test runs with the LLM switched off."""

    def setUp(self) -> None:  # noqa: D401 - unittest hook
        patcher = rules_only_env()
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()
