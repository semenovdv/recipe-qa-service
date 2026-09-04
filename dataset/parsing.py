"""Pure wikitext parsing functions: API page JSON -> normalized recipe fields.

No I/O and no network here (see dataset/PLAN.md §2). All rules follow
dataset/PLAN.md §4: tolerant field extraction, ambiguity becomes ``null``
(never guessed), and markup never leaks into normalized values.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

WIKI_BASE = "https://en.wikibooks.org/wiki/"

# ---------------------------------------------------------------------------
# raw accessors
# ---------------------------------------------------------------------------


def page_content(query_response: dict[str, Any], pageid: int) -> str:
    """Extract the main-slot wikitext for one page from a prop=revisions query."""
    for page in query_response["query"]["pages"]:
        if page["pageid"] == pageid:
            return page["revisions"][0]["slots"]["main"]["content"]
    raise KeyError(f"pageid {pageid} not found in query response")


# ---------------------------------------------------------------------------
# summary template ({{recipesummary | Field = value ...}})
# ---------------------------------------------------------------------------

_SUMMARY_RE = re.compile(
    r"\{\{\s*recipe[\s_-]*summary\s*\|(?P<body>.*?)\}\}", re.IGNORECASE | re.DOTALL
)
_SUMMARY_FIELD_RE = re.compile(
    r"\|\s*(?P<name>[A-Za-z _-]+?)\s*=\s*(?P<value>[^|]*)",
    # "|" also matches at string start without consuming a char, so the first
    # "Category = ..." field (which follows the template name, not a "|") is
    # captured too; DOTALL keeps multi-line values intact.
)
_SUMMARY_FIRST_FIELD_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z _-]+?)\s*=\s*(?P<value>[^|]*)", re.DOTALL
)


def _summary_fields(content: str) -> dict[str, str]:
    # Remove HTML comments first: the template may contain a commented-out
    # field on its own line ("<!--| Energy      = -->"), which would otherwise
    # swallow field separators when removed naively inside the body match.
    content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    match = _SUMMARY_RE.search(content)
    if not match:
        return {}
    # The template may contain an HTML comment with a commented-out field:
    # "<!--| Energy = -->| Image = ...". Remove comments first so the parser
    # cannot pick up placeholder fields inside them.
    body = re.sub(r"<!--.*?-->", "\n", match.group("body"), flags=re.DOTALL)
    fields: dict[str, str] = {}
    # The first field follows the template name directly ("{{recipesummary
    # | Category = ..." has its "|" consumed by _SUMMARY_RE), so it starts at
    # position 0 without a leading pipe and needs its own pattern.
    first = _SUMMARY_FIRST_FIELD_RE.match(body)
    if first:
        fields[_summary_key(first.group("name"))] = first.group("value").strip()
    for field_match in _SUMMARY_FIELD_RE.finditer(body):
        value = field_match.group("value").strip()
        # drop inline image/template remnants from values like "[[Image:x.jpg|300px]]"
        value = re.sub(r"\[\[[^]]*\]\]", "", value).strip()
        fields[_summary_key(field_match.group("name"))] = value
    return fields


def _summary_key(name: str) -> str:
    return name.strip().lower().replace(" ", "")


def parse_time_minutes(raw: str | None) -> int | None:
    """Parse a recipesummary Time value into total minutes.

    Ambiguous input (ranges, unit-less numbers, prose) yields ``None``:
    per spec §4.6 a missing/ambiguous time never satisfies a hard constraint.
    """
    if raw is None:
        return None
    text = raw.strip().lower()
    if not text:
        return None
    # treat unicode fractions as their decimal values ("1 1/2" or "1½")
    for fraction, decimal in {
        "¼": " 1/4",
        "½": " 1/2",
        "¾": " 3/4",
        "⅓": " 1/3",
        "⅔": " 2/3",
    }.items():
        text = text.replace(fraction, decimal)

    # reject ranges like "1-2 hours", "1–2 hours", "30-40 min"
    if re.search(r"\d\s*[-–—]\s*\d", text):
        return None
    # reject multi-phase totals like "30 minutes + 24 hours": the "+" marks
    # additional (e.g. resting/marinating) time, which is ambiguous for the
    # spec §4.6 hard-constraint semantics -> not a reliable total
    if "+" in text:
        return None
    if not re.search(r"\d", text):
        return None

    hours = 0.0
    minutes = 0.0
    found = False

    # Numeric phrase immediately before a unit word: "75", "1.5", "1 1/2".
    quantity_re = r"([\d.]+(?:\s+[\d.]+)?(?:\s*/\s*[\d.]+)?)\s*"

    for match in re.finditer(quantity_re + r"(hours?|hrs?|h)\b", text):
        value = _parse_quantity(match.group(1))
        if value is None:
            return None
        hours += value
        found = True

    for match in re.finditer(quantity_re + r"(?:minutes?|mins?|m)\b", text):
        value = _parse_quantity(match.group(1))
        if value is None:
            return None
        minutes += value
        found = True

    if not found:
        # a bare number without any unit is ambiguous ("Time = 45")
        return None

    total = hours * 60 + minutes
    return int(total) if total == int(total) else None


def _parse_quantity(text: str) -> float | None:
    """Parse a numeric phrase: "75", "1.5", "1 1/2" (mixed number)."""
    total = 0.0
    for token in text.split():
        try:
            if "/" in token:
                numerator, denominator = token.split("/", 1)
                denominator_value = float(denominator)
                if denominator_value == 0:
                    return None
                total += float(numerator) / denominator_value
            else:
                total += float(token)
        except ValueError:
            return None
    return total


def _summary_key(name: str) -> str:
    return name.strip().lower().replace(" ", "")


def _strip_leading_quantity(name: str) -> str:
    """Remove leading quantity/unit prefixes and trailing notes from an
    ingredient line, keeping the ingredient name (dataset/PLAN.md §4)."""
    # cut trailing preparation notes after a comma ("thinly-sliced", "about 3 small...")
    name = name.split(",")[0].strip()
    # cut trailing parenthetical notes: "(about 3 small potatoes)"
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    # drop trailing punctuation
    name = name.rstrip(". ").strip()
    # drop a leading quantity(+fraction)(+unit) token: "1½ cups",
    # "1–2 tablespoons", "about 6", "3-4 cups"; keep the remainder
    # (e.g. "thinly-sliced potatoes"). Runs before fraction normalization,
    # so unicode fractions are matched directly.
    name = re.sub(
        r"^(?:about\s+|approx(?:imately)?\s+)?"
        r"[\d.,\s–—-]*[\d½¼¾⅓⅔⅛⅜⅝⅞]"
        r"[\d½¼¾⅓⅔⅛⅜⅝⅞.,/\s–—-]*"
        r"(?:cups?|tablespoons?|tbsp|teaspoons?|tsp|grams?|g|ounces?|oz|pounds?|lbs?|ml|l)?"
        r"\s+",
        "",
        name,
        flags=re.IGNORECASE,
    )
    return name.strip()


def extract_summary(content: str) -> dict[str, Any]:
    """Extract recipesummary fields; absent fields are None, never guessed."""
    fields = _summary_fields(content)
    category = fields.get("category") or None
    servings = fields.get("servings") or None
    rating: int | None = None
    raw_rating = fields.get("rating")
    if raw_rating:
        try:
            rating = int(float(raw_rating))
        except ValueError:
            rating = None
    return {
        "category": category,
        "servings": servings,
        "time_minutes": parse_time_minutes(fields.get("time")),
        "rating": rating,
    }


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(={2,4})\s*(.+?)\s*\1\s*$", re.MULTILINE)
_INGREDIENTS_HEADING_RE = re.compile(r"ingredients?", re.IGNORECASE)
_PROCEDURE_HEADING_RE = re.compile(
    r"procedure|preparation|instructions|steps|method", re.IGNORECASE
)


def _section(content: str, heading_pattern: re.Pattern[str]) -> str:
    """Return the text under the first heading matching the pattern (its own
    level and any deeper level), up to the next heading of equal/higher level."""
    matches = list(_HEADING_RE.finditer(content))
    for index, match in enumerate(matches):
        if not heading_pattern.match(match.group(2)):
            continue
        level = len(match.group(1))
        end = len(content)
        for later in matches[index + 1 :]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        return content[match.end() : end]
    return ""


def _strip_markup(text: str) -> str:
    """Remove wikitext markup, leaving readable display text."""
    # remove templates {{...}} (possibly nested)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    # links: [[target|display]] -> display, [[target]] -> target
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]|]*)\]\]", r"\1", text)
    # bold/italic
    text = text.replace("'''", "").replace("''", "")
    # HTML comments and tags
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    # tags/refs
    text = re.sub(r"<ref[^>]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
    return text.strip()


def _bullet_lines(section_text: str) -> list[str]:
    lines = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("*", "#")) and len(stripped) > 1:
            lines.append(stripped.lstrip("*#").strip())
    return lines


def extract_ingredient_lines(content: str) -> list[str]:
    """Raw (markup-stripped) ingredient bullet lines from the Ingredients section."""
    section = _section(content, _INGREDIENTS_HEADING_RE)
    return [
        _strip_markup(line) for line in _bullet_lines(section) if _strip_markup(line)
    ]


def extract_ingredients(content: str) -> list[str]:
    """Normalized ingredient names for filtering/lookup (no quantities/markup)."""
    normalized: list[str] = []
    for line in extract_ingredient_lines(content):
        name = _strip_leading_quantity(line)
        # normalize unicode fractions that survived
        name = re.sub(r"[½¼¾⅓⅔⅛⅜⅝⅞]", "", name).strip()
        name = re.sub(r"\s+", " ", name)
        if name:
            normalized.append(name)
    return normalized


def extract_steps(content: str) -> list[str]:
    """Ordered step lines from the Procedure/Instructions section."""
    section = _section(content, _PROCEDURE_HEADING_RE)
    return [
        _strip_markup(line) for line in _bullet_lines(section) if _strip_markup(line)
    ]


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------

_CATEGORY_RE = re.compile(r"\[\[\s*Category\s*:\s*([^\]|]+)\]\]", re.IGNORECASE)


def extract_categories(content: str) -> list[str]:
    return sorted({match.group(1).strip() for match in _CATEGORY_RE.finditer(content)})


def extract_description(content: str) -> str | None:
    """First substantial paragraph before the first section heading."""
    # drop templates and category/link trails for prose extraction
    prose = re.sub(r"\{\{[^{}]*\}\}", "", content)
    prose = re.sub(r"\[\[\s*Category\s*:[^\]]+\]\]", "", prose, flags=re.IGNORECASE)
    for paragraph in prose.split("\n\n"):
        text = _strip_markup(paragraph)
        text = re.sub(r"\s+", " ", text).strip()
        # skip nav lines like "recipe | Cuisine of Ukraine | Soups"
        if len(text) >= 80 and not text.startswith("|"):
            return text
    return None


def extract_title(page: dict[str, Any]) -> str:
    return page["title"]


def canonical_url(title: str) -> str:
    """Canonical wikibooks URL: spaces -> underscores, non-ASCII percent-encoded.

    The ``Cookbook:`` namespace colon is preserved literally (it is valid in
    URLs); only the title part after it is percent-encoded.
    """
    namespace, separator, rest = title.partition(":")
    if separator:
        prefix = f"{namespace}:"
    else:
        prefix, rest = "", title
    return WIKI_BASE + prefix + quote(rest.replace(" ", "_"))


def normalize_variant_group(title: str) -> str:
    """Group near-duplicate variant pages ("X I", "X II") under one id.

    Deterministic per dataset/PLAN.md §4: trailing roman-numeral variant
    suffixes are stripped, the remaining title is lowercased.
    """
    text = title.removeprefix("Cookbook:").strip()
    text = re.sub(
        r"[\s_-]+(?:i{1,3}|iv|v|vi{1,3}|ix|x)$", "", text, flags=re.IGNORECASE
    )
    text = re.sub(r"\s*\([^)]*\)$", "", text)  # drop trailing parenthetical
    text = re.sub(r"[^\w\s/-]", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


# ---------------------------------------------------------------------------
# full page parse
# ---------------------------------------------------------------------------


def parse_wikitext_page(
    page: dict[str, Any], fetched_at: str | None = None
) -> dict[str, Any]:
    """Build a normalized recipe record from one prop=revisions page object."""
    revision = page["revisions"][0]
    content = revision["slots"]["main"]["content"]
    title = extract_title(page)
    return {
        "pageid": page["pageid"],
        "revid": revision["revid"],
        "title": title,
        "url": canonical_url(title),
        "fetched_at": fetched_at or revision.get("timestamp"),
        "categories": extract_categories(content),
        "summary": extract_summary(content),
        "ingredients_raw": extract_ingredient_lines(content),
        "ingredients": extract_ingredients(content),
        "steps": extract_steps(content),
        "description": extract_description(content),
        "variant_group": normalize_variant_group(title),
        "source_text": content,
    }
