"""Extract readable SEC HTML, excluding scripts and hidden inline XBRL."""
from html.parser import HTMLParser
import re


class FilingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[tuple[str, bool]] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        hidden = bool(self.stack and self.stack[-1][1]) or tag in {"script", "style", "ix:hidden", "head"} or "hidden" in attrs or bool(re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", attrs.get("style", ""), re.I))
        if tag not in {"br", "hr", "img", "meta", "link", "input", "wbr", "area", "base", "embed", "param", "source", "track", "col"}:
            self.stack.append((tag, hidden))
        if not hidden and tag in {"p", "div", "tr", "br", "li", "h1", "h2", "h3", "td"}:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not self.stack or not self.stack[-1][1]:
            self.parts.append(data)


def html_text(content: bytes) -> str:
    parser = FilingParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    return "\n".join(line for row in "".join(parser.parts).splitlines() if (line := " ".join(row.split())))


def filing_excerpt(text: str, query: str = "") -> str:
    """Allocate space across sections so late revenue tables are not truncated."""
    terms = [query] if query.strip() else [
        "products and services performance", "net sales by category",
        "segment operating performance", "segment", "business", "risk factors",
        "management’s discussion", "management's discussion", "cash flows",
    ]
    groups = []
    for term in terms:
        matches = list(re.finditer(re.escape(term), text, re.I))
        if matches:
            groups.append(matches[-3:])
    if not groups:
        return text[:30000]
    budget = 27000 // len(groups)
    excerpts = [text[:2000]]
    for matches in groups:
        width = budget // len(matches)
        for match in matches:
            start = max(0, match.start() - min(300, width // 5))
            excerpts.append(f"[字符位置 {start}]\n" + text[start:start + width])
    return "\n\n".join(excerpts)[:30000]
