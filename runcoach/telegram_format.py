"""Telegram-HTML-aware text splitting.

Telegram's Bot API has a 4096-character per-message hard limit and a strict
HTML parser. A naive split that lands inside a tag — or breaks a `<b>...</b>`
across two chunks — gets rejected with `BadRequest`. The bridge falls back to
plain text in that case, which loses formatting on the offending chunk.

`smart_split` here splits at natural boundaries (paragraph > line > sentence)
while tracking the open-tag stack: it never breaks inside a `<...>`, and when
a tag spans the chosen boundary it closes the tag at the end of the current
chunk and reopens it (with original attributes preserved) at the start of
the next. The result: every chunk is independently valid Telegram HTML.

Used by `tools/telegram_bridge.py`. Tests live in `tests/test_telegram_format.py`.
"""

import re

# Telegram's per-message limit is 4096; leave headroom for the bot's chunking
# index and any minor expansion from tag close/reopen pairs inserted across
# chunk boundaries.
MAX_TG_LEN = 4000

# Telegram-supported HTML tags (per their Bot API). Anything else we ignore for
# tag-balancing purposes — splitting won't try to close <em> because Telegram
# never accepts it in the first place.
_HTML_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*)>")
_TELEGRAM_HTML_TAGS = {"b", "strong", "i", "em", "u", "s", "code", "pre", "a", "tg-spoiler"}


def _open_tags_at(text: str) -> list[tuple[str, str]]:
    """Return tags still open at the end of `text`, as [(name, attr_str)] in
    opening order. Tracks only Telegram-supported HTML tags. Mismatched
    closing tags are ignored rather than erroring (mirrors Telegram's lenient
    parser; lets smart_split degrade gracefully on malformed input)."""
    stack: list[tuple[str, str]] = []
    for m in _HTML_TAG_RE.finditer(text):
        slash, name, attrs = m.group(1), m.group(2).lower(), m.group(3) or ""
        if name not in _TELEGRAM_HTML_TAGS:
            continue
        if slash == "/":
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    del stack[i]
                    break
        else:
            stack.append((name, attrs))
    return stack


def _split_is_inside_tag(text: str, idx: int) -> bool:
    """True if `idx` falls between a '<' and its matching '>' — splitting here
    would land mid-tag and produce malformed HTML."""
    lt = text.rfind("<", 0, idx)
    if lt == -1:
        return False
    gt = text.find(">", lt)
    return gt >= idx


def smart_split(text: str, max_len: int = MAX_TG_LEN) -> list[str]:
    """Split text into chunks <= max_len, preferring breaks at natural boundaries
    (paragraph > line > sentence > hard cut). HTML-tag-aware: never breaks
    inside a tag, and if a tag (e.g. <b>, <pre>, <a href="...">) spans a chunk
    boundary, closes it at the end of the current chunk and reopens it at the
    start of the next so each chunk is independently valid HTML."""
    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > max_len:
        window = remaining[:max_len]
        candidates = [
            (window.rfind("\n\n"), 2),    # paragraph break
            (window.rfind("\n"), 1),       # line break
            (window.rfind(". "), 2),       # sentence end
            (window.rfind("! "), 2),
            (window.rfind("? "), 2),
            (window.rfind(".\n"), 2),
            (window.rfind("!\n"), 2),
            (window.rfind("?\n"), 2),
        ]
        # Latest break above the half-mark that isn't inside an HTML tag.
        viable = [
            (idx, skip) for idx, skip in candidates
            if idx >= max_len // 2 and not _split_is_inside_tag(window, idx)
        ]
        if viable:
            idx, skip = max(viable, key=lambda x: x[0])
            chunk = remaining[:idx + (1 if skip == 2 and remaining[idx] in ".!?" else 0)]
            rest = remaining[idx + skip:].lstrip()
        else:
            # No natural break — hard-cut, but back off if the cut lands inside a tag.
            cut = max_len
            while cut > max_len // 2 and _split_is_inside_tag(window, cut):
                cut -= 1
            chunk = remaining[:cut]
            rest = remaining[cut:].lstrip()

        # Close any tags still open at the chunk break, then reopen them at the
        # start of the next chunk so each chunk is independently valid HTML.
        opens = _open_tags_at(chunk)
        if opens:
            close_str = "".join(f"</{name}>" for name, _ in reversed(opens))
            reopen_str = "".join(f"<{name}{attrs}>" for name, attrs in opens)
            chunk = chunk.rstrip() + close_str
            rest = reopen_str + rest

        chunks.append(chunk)
        remaining = rest
    if remaining:
        chunks.append(remaining)
    return chunks
