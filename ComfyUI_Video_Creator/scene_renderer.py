"""Pure {{tag}} substitution + pasted-reply parsing (no Qt). Copied from Document Update Placeholder/renderer.py."""
import re

TAG_RE = re.compile(r"\{\{\s*([A-Za-z0-9_-]+)\s*\}\}")


def find_tags(body: str) -> list[str]:
    """Unique tag names in the order they first appear in the body."""
    seen: dict[str, None] = {}
    for m in TAG_RE.finditer(body):
        seen.setdefault(m.group(1), None)
    return list(seen)


def render(body: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """Replace every {{tag}} with values[tag].

    Tags with no value (missing or empty) are left untouched and returned in
    the second element so the UI can warn. Replacement is a single pass, so a
    snippet that itself contains {{...}} is never expanded again.
    """
    missing: dict[str, None] = {}

    def sub(m: re.Match) -> str:
        name = m.group(1)
        text = values.get(name, "")
        if not text:
            missing.setdefault(name, None)
            return m.group(0)
        return text

    return TAG_RE.sub(sub, body), list(missing)


# ---------- importing a pasted AI reply as named snippets ----------

# "1. Title", "**2. Title**", "### 3. Title", "Option 4: Title", "Scenario 5 - Title" ...
HEADER_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*{1,2}|_{1,2})?\s*"
    r"(?:(?:option|scenario|version|variation|prompt|idea|scene)\s*)?"
    r"(\d{1,3})\s*[.):\-–]\s*(.+?)\s*$",
    re.I,
)
RULE_RE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")      # --- / *** / ___ separator lines
MAX_TITLE = 80


def _clean_title(t: str) -> str:
    return t.strip().strip("*_ ").rstrip(":").strip("*_ ").strip()


def _clean_body(lines: list[str]) -> str:
    return "\n".join(l.rstrip() for l in lines if not RULE_RE.match(l)).strip()


def parse_scenarios(text: str) -> list[dict]:
    """Split a pasted AI reply into [{"name", "text"}, ...].

    A title line is a numbered line ("1. Luxury Retreat", "**2. ...**", "Option 3: ...") that is
    short, doesn't end like a sentence, and continues the 1,2,3... sequence - so numbered points
    inside a scenario's own text are left alone. Anything before the first title (an intro line)
    is dropped. With no titles at all, the whole text comes back as one unnamed snippet.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    heads: list[tuple[int, str]] = []
    expect = None
    for i, line in enumerate(lines):
        m = HEADER_RE.match(line)
        if not m:
            continue
        title = _clean_title(m.group(2))
        if not title or len(title) > MAX_TITLE or title[-1] in ".!?":
            continue
        n = int(m.group(1))
        if expect is not None and n != expect:
            continue
        heads.append((i, title))
        expect = n + 1
    if not heads:
        body = _clean_body(lines)
        return [{"name": "", "text": body}] if body else []
    out = []
    for k, (i, title) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        body = _clean_body(lines[i + 1:end])
        if body:
            out.append({"name": title, "text": body})
    return out
