"""Prompt-injection scanning for untrusted tool output and memory candidates.

The pattern library is Hermes' ``threat_patterns`` (see ``threat_patterns.py``) plus Chinese phrasings.
"""

from atlas.safety.threat_patterns import (  # noqa: F401  (re-exported)
    INVISIBLE_CHARS, MAX_SCAN_CHARS, first_threat_message, scan_for_threats,
)
