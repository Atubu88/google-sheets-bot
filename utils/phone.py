import re


def normalize_ua_phone(raw: str) -> str | None:
    """
    Приводит номер к формату +380XXXXXXXXX
    """
    if not raw:
        return None

    digits = re.sub(r"\D", "", raw)

    if digits.startswith("380") and len(digits) == 12:
        return f"+{digits}"

    if digits.startswith("80") and len(digits) == 11:
        return f"+3{digits}"

    if digits.startswith("0") and len(digits) == 10:
        return f"+38{digits}"

    return None
