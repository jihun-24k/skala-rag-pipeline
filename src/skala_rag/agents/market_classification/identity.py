"""Name matching without guessing translations or unrelated company aliases."""

import re
import unicodedata


def _clean(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"\(\s*주\s*\)|주식회사|유한회사", " ", value)
    value = re.sub(
        r"\b(?:incorporated|incorporation|inc|corporation|corp|company|co|limited|ltd)\b\.?",
        " ", value,
    )
    return value


def normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]", "", _clean(value))


def mentions_name(text: str, name: str) -> bool:
    key = normalized_name(name)
    if not key:
        return False
    # Spaces may vary; Korean postpositions may follow the complete name.
    pattern = r"(?<![a-z0-9가-힣])" + r"\s*".join(map(re.escape, key))
    pattern += r"(?:(?![a-z0-9가-힣])|(?=(?:은|는|이|가|을|를|와|과|의|에서|에게|도|만)(?![a-z0-9가-힣])))"
    return bool(re.search(pattern, _clean(text)))
