import re


MIN_SPLIT_LETTERS = 5

SPLIT_PHRASE_MAP = {
    "HOWTOREAD": "HOW TO READ",
    "FIRSTLINESTRUCTURE": "FIRST LINE STRUCTURE",
    "ORGANISATIONCHARTS": "ORGANISATION CHARTS",
    "ORGANIZATIONCHARTS": "ORGANIZATION CHARTS",
}

SPLIT_RUN_PATTERN = re.compile(r"\b[A-Za-z](?:\s+[A-Za-z])+\b")


def normalize_pdf_text(text: str) -> str:
    if not text:
        return ""

    def replace_split_run(match: re.Match) -> str:
        raw_match = match.group(0)
        letters = [character for character in raw_match if character.isalpha()]
        if len(letters) < MIN_SPLIT_LETTERS:
            return raw_match
        joined = "".join(letters)
        return SPLIT_PHRASE_MAP.get(joined.upper(), joined)

    return SPLIT_RUN_PATTERN.sub(replace_split_run, text)
