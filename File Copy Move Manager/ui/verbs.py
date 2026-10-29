"""Verb forms for the two modes, kept in one place.

Building the past tense by gluing a "d" onto the verb gives "Copyd" — the verbs
are irregular ("Copy" -> "Copied", "Move" -> "Moved"), so spell them out.
"""


def mode_verbs(mode: str) -> tuple:
    """Return (infinitive, past tense): ("Copy", "Copied") or ("Move", "Moved")."""
    return ("Move", "Moved") if mode == "move" else ("Copy", "Copied")
