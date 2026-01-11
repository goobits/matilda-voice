import re


def is_ssml(text: str) -> bool:
    text = text.strip()
    return text.startswith("<speak") and text.endswith("</speak>")


def strip_ssml_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)
