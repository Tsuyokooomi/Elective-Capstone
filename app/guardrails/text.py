"""Text clean-up used before the injection check.

Attackers hide the words "ignore previous instructions" with look-alike letters, zero-width
characters, spaced-out letters or leetspeak. This module turns such text back into plain words.
The result is used ONLY for checking. What gets stored and sent to the LLM is the original text."""
import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u200e\u200f\u2060\u2061\u2062\u2063\u2064\ufeff\u00ad"), None)

# Cyrillic and Greek letters that look like Latin ones
_HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ѕ": "s", "ј": "j",
    "ԁ": "d", "һ": "h", "ԛ": "q", "ѵ": "v",
    "ο": "o", "α": "a", "ε": "e", "ι": "i", "ν": "v", "ρ": "p", "τ": "t", "υ": "u", "κ": "k",
})

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})

# i g n o r e   or   i.g.n.o.r.e / i-g-n-o-r-e : four or more single characters split by one separator.
# Spaces and punctuation are handled separately so that a space between WORDS is not swallowed.
_SPACED = re.compile(r"\b(?:\w ){3,}\w\b")
_DOTTED = re.compile(r"\b(?:\w[._*-]){3,}\w\b")
_REPEATS = re.compile(r"(.)\1{2,}")   # ignoooore -> ignore (three or more in a row)


def _join_letters(match: re.Match) -> str:
    return re.sub(r"[\s._*-]", "", match.group(0))


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).translate(_HOMOGLYPHS).lower()
    text = _DOTTED.sub(_join_letters, _SPACED.sub(_join_letters, text))
    return _REPEATS.sub(r"\1", text)


def views(text: str) -> list[str]:
    """The texts to check: plain, and with leetspeak turned into letters."""
    plain = normalize(text)
    leet = plain.translate(_LEET)
    return [plain] if leet == plain else [plain, leet]
