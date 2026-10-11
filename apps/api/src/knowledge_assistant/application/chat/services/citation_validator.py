import re
from dataclasses import dataclass

_SOURCE_ID_PATTERN = re.compile(r"S[1-9]\d*")
_BRACKETED_TOKEN_PATTERN = re.compile(r"\[([^\]\n]{1,40})\]")
_SOURCE_LIKE_PATTERN = re.compile(
    r"^(?:s(?=\d|\s|[-_:#]|$)|source\b)",
    re.IGNORECASE,
)
_BARE_SOURCE_ID_PATTERN = re.compile(
    r"(?<![\w[])s[\s:_-]*\d+\b",
    re.IGNORECASE,
)
_UNCLOSED_SOURCE_PATTERN = re.compile(
    r"\[\s*(?:s(?=\d|\s|[-_:#]|$)|source\b)[^\]\n]*(?:\n|$)",
    re.IGNORECASE,
)
_LIST_ITEM_PATTERN = re.compile(
    r"^\s*(?:[-*+] |\d+[.)]\s+)",
)
_WORD_PATTERN = re.compile(r"\b[\w'-]+\b", re.UNICODE)

_CONVERSATIONAL_PATTERNS = (
    re.compile(
        r"^(?:hello|hi|hey|good (?:morning|afternoon|evening))"
        r"[!,. ]*(?:(?:how|what) can i help(?: you)?(?: with)?)?[?!. ]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:γεια|καλημέρα|καλησπέρα)[!,. ]*"
        r"(?:πώς μπορώ να βοηθήσω(?: σας)?;?)?[?!. ]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:could|would|can) you (?:clarify|provide|share|specify)\b[^.]*[?. ]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:please )?(?:clarify|provide more detail)\b[^.]*[?. ]*$",
        re.IGNORECASE,
    ),
)
_INSUFFICIENT_EVIDENCE_PATTERNS = tuple(
    re.compile(rf"^(?:{phrase})\b", re.IGNORECASE)
    for phrase in (
        "the available documents do not provide",
        "the available sources do not provide",
        "there is not enough information",
        "there is insufficient information",
        "i cannot answer from the available",
        "i can't answer from the available",
        "δεν βρέθηκαν σχετικές πληροφορίες",
        "δεν υπάρχουν αρκετές πληροφορίες",
        "οι διαθέσιμες πηγές δεν",
        "τα διαθέσιμα έγγραφα δεν",
    )
)
_CONTRAST_PATTERN = re.compile(
    r"\b(?:but|however|yet|although|nevertheless|αλλά|ωστόσο)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CitationValidationResult:
    is_valid: bool
    cited_source_ids: tuple[str, ...]
    failures: tuple[str, ...]


def validate_generated_answer(
    *,
    answer_markdown: str,
    used_source_ids: tuple[str, ...],
    available_source_ids: frozenset[str],
) -> CitationValidationResult:
    cited_source_ids, malformed_citation = _extract_citations(answer_markdown)
    failures: list[str] = []

    if not answer_markdown.strip():
        failures.append("Provide a non-empty answer.")

    if malformed_citation:
        failures.append("Use citations only in the exact form [S1].")

    unknown_citations = set(cited_source_ids) - available_source_ids
    malformed_used_ids = any(
        _SOURCE_ID_PATTERN.fullmatch(source_id) is None
        for source_id in used_source_ids
    )
    unknown_used_ids = set(used_source_ids) - available_source_ids

    if unknown_citations or malformed_used_ids or unknown_used_ids:
        failures.append(
            "Use only source identifiers from the supplied source list."
        )

    if len(set(used_source_ids)) != len(used_source_ids):
        failures.append("List each used source identifier only once.")

    if set(cited_source_ids) != set(used_source_ids):
        failures.append(
            "Make used_source_ids exactly match the sources cited in the answer."
        )

    factual_units = _factual_units(answer_markdown)
    units_without_valid_citations = [
        unit
        for unit in factual_units
        if not (
            set(_extract_citations(unit)[0])
            & available_source_ids
        )
    ]

    if units_without_valid_citations:
        failures.append(
            "Add a supplied source citation to every factual paragraph or list item."
        )

    if not factual_units and cited_source_ids:
        failures.append(
            "Do not cite sources in a greeting, clarification, or insufficient-evidence response."
        )

    unique_citations = tuple(dict.fromkeys(cited_source_ids))
    unique_failures = tuple(dict.fromkeys(failures))

    return CitationValidationResult(
        is_valid=not unique_failures,
        cited_source_ids=unique_citations,
        failures=unique_failures,
    )


def _extract_citations(markdown: str) -> tuple[tuple[str, ...], bool]:
    citations: list[str] = []
    malformed = False

    for match in _BRACKETED_TOKEN_PATTERN.finditer(markdown):
        token = match.group(1).strip()
        is_source_id = _SOURCE_ID_PATTERN.fullmatch(token) is not None
        suffix = markdown[match.end() :]
        is_markdown_link = suffix.startswith("(")

        if is_source_id and not is_markdown_link:
            citations.append(token)
            continue

        if is_source_id or _SOURCE_LIKE_PATTERN.match(token):
            malformed = True

    if _BARE_SOURCE_ID_PATTERN.search(markdown):
        malformed = True

    if _UNCLOSED_SOURCE_PATTERN.search(markdown):
        malformed = True

    return tuple(citations), malformed


def _factual_units(markdown: str) -> tuple[str, ...]:
    units: list[str] = []

    for paragraph in re.split(r"\n\s*\n", markdown):
        cleaned_paragraph = paragraph.strip()

        if not cleaned_paragraph:
            continue

        candidates = _split_paragraph_units(cleaned_paragraph)

        for candidate in candidates:
            if _is_meaningful_factual_unit(candidate):
                units.append(candidate)

    return tuple(units)


def _split_paragraph_units(paragraph: str) -> tuple[str, ...]:
    candidates: list[str] = []
    prose_lines: list[str] = []

    def flush_prose() -> None:
        if prose_lines:
            candidates.append("\n".join(prose_lines))
            prose_lines.clear()

    for line in paragraph.splitlines():
        if line.strip().startswith("#"):
            flush_prose()
            candidates.append(line)
        elif _LIST_ITEM_PATTERN.match(line):
            flush_prose()
            candidates.append(line)
        else:
            prose_lines.append(line)

    flush_prose()
    return tuple(candidates)


def _is_meaningful_factual_unit(unit: str) -> bool:
    stripped = unit.strip()

    if not stripped:
        return False

    without_citations = _BRACKETED_TOKEN_PATTERN.sub("", stripped)
    plain_text = re.sub(r"^[#]+\s*", "", without_citations)
    plain_text = re.sub(r"[`*_~>]", "", plain_text).strip()
    normalized = " ".join(plain_text.casefold().split())

    if not normalized:
        return False

    is_insufficient_statement = any(
        pattern.match(normalized)
        for pattern in _INSUFFICIENT_EVIDENCE_PATTERNS
    ) and _CONTRAST_PATTERN.search(normalized) is None

    if is_insufficient_statement:
        return False

    words = _WORD_PATTERN.findall(plain_text)

    if len(words) <= 12 and any(
        pattern.fullmatch(plain_text)
        for pattern in _CONVERSATIONAL_PATTERNS
    ):
        return False

    if plain_text.endswith(":") and len(words) <= 3:
        return False

    return len(words) >= 4 or any(character.isdigit() for character in plain_text)
