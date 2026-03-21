"""
talker.py — CrinkleDen (CDN)

Baby talk / age-regression / littlespace speech transformer.
100% local, zero external dependencies — no AI, no network.

Analysed from the original babytalk.exe (Python 3.13 / tkinter):
  - Original only did: w→ww, d→dd, sh→Sh, (r,l,R,L,th,Th,s,S) → mapped, +' ~~~'
  - This version is a complete rewrite with 6 distinct modes, 200+ rules,
    sentence starters, emotional interjections, and context-aware transforms.

Usage:
    from talker import transform, available_modes
    result = transform("I really need to go to the bathroom.", mode="little")
    modes  = available_modes()   # list of (key, label, description) tuples
"""

from __future__ import annotations
import random, re
from typing import Callable


# ══════════════════════════════════════════════════════════════════════════════
# Core substitution tables
# ══════════════════════════════════════════════════════════════════════════════

# Phoneme substitutions applied at character level (case-insensitive, order matters)
_PHONEME_LITTLE = [
    # Consonant softening
    ("thr",  "fwr"),
    ("tr",   "tw"),
    ("dr",   "dw"),
    ("str",  "stw"),
    ("spr",  "spw"),
    ("cr",   "kw"),
    ("gr",   "gw"),
    ("br",   "bw"),
    ("fr",   "fw"),
    ("pr",   "pw"),
    ("gl",   "gw"),
    ("bl",   "bw"),
    ("fl",   "fw"),
    ("pl",   "pw"),
    ("cl",   "kw"),
    ("sl",   "sw"),
    ("th",   "d"),
    ("tion", "shun"),
    ("le",   "ol"),
    # r → w  (only after a consonant, not at word start)
    ("r",    "w"),
    ("l",    "w"),
    # s → sh in some positions (handled in word-level rules)
]

_PHONEME_TINY = [
    *_PHONEME_LITTLE,
    ("s",    "sh"),
    ("ce",   "she"),
    ("ci",   "shi"),
    ("ck",   "kk"),
    ("x",    "ks"),
    ("qu",   "kw"),
]

_PHONEME_LISP = [
    ("th",  "f"),
    ("the", "fe"),
    ("s",   "th"),
    ("z",   "th"),
    ("sh",  "thh"),
    ("ce",  "the"),
]

# Word-level substitutions (full word matches, applied before phoneme rules)
_WORD_SUBS_LITTLE: dict[str, str | list[str]] = {
    # Pronouns / forms of address
    "i":           "i",
    "me":          "me",
    "my":          "my",
    "you":         "you",
    "your":        "youw",
    "we":          "we",
    "us":          "us",
    # Verbs
    "want":        "wan",
    "wanted":      "wanned",
    "love":        "wuv",
    "loves":       "wuvs",
    "loved":       "wuved",
    "like":        "wike",
    "likes":       "wikes",
    "feel":        "feew",
    "feels":       "feews",
    "need":        "nee",
    "needs":       "needs",
    "have":        "hab",
    "has":         "haz",
    "was":         "waz",
    "were":        "wew",
    "is":          "iz",
    "are":         "awe",
    "go":          "goo",
    "going":       "gowin",
    "come":        ["come", "comed", "cuuuume"],
    "try":         "twy",
    "take":        "tate",
    "give":        "gib",
    "do":          "doo",
    "did":         "did",
    "know":        "kno",
    "think":       "fink",
    "thought":     "fawt",
    "say":         "shay",
    "said":        "shed",
    "tell":        "teww",
    "told":        "towld",
    "see":         "shee",
    "saw":         "shaw",
    "hear":        "heaw",
    "look":        "wook",
    "looked":      "wookd",
    "make":        "makie",
    "made":        "maded",
    "help":        "hewp",
    "helps":       "hewps",
    "please":      "pwease",
    "stop":        "shtop",
    "start":       "shtart",
    "hold":        "howld",
    "put":         "pwut",
    "sit":         "shwit",
    "sleep":       "shweep",
    "cry":         "cwy",
    "cried":       "cwied",
    "hug":         "huggies",
    "hugged":      "huggled",
    "cuddle":      "cuddow",
    "cuddles":     "cuddows",
    "snuggle":     "snuggles",
    "play":        "pway",
    "played":      "pwayed",
    "playing":     "pwaying",
    "drink":       "dwink",
    "drinks":      "dwinks",
    "eat":         "nom",
    "eating":      "nomming",
    "ate":         "nommed",
    "wear":        "weaw",
    "wearing":     "weawing",
    "change":      "chanjie",
    "changed":     "chanjieed",
    # Nouns — general
    "bathroom":    "potty",
    "toilet":      "potty",
    "restroom":    "potty",
    "bed":         "beddie",
    "bedroom":     "beddie-room",
    "house":       "housie",
    "home":        "homie",
    "car":         "vroom",
    "phone":       "phonies",
    "computer":    "puter",
    "food":        "nummies",
    "drink":       "dwinkies",
    "water":       "wawer",
    "milk":        "miwkies",
    "juice":       "juicies",
    "cookie":      "cooties",
    "cookies":     "cooties",
    "candy":       "nummies",
    "toy":         "towy",
    "toys":        "towies",
    "friend":      "fwiend",
    "friends":     "fwiends",
    "baby":        "baby",
    "babies":      "babies",
    "mommy":       "mommy",
    "daddy":       "daddy",
    "mommy":       "mommy",
    "mama":        "mama",
    "dada":        "dada",
    "little":      "wittle",
    "littles":     "wittles",
    "big":         "biggies",
    "small":       "smaww",
    "happy":       "happies",
    "sad":         ["saddie", "saddie-waddies"],
    "angry":       "owwie-angry",
    "tired":       "sweeepy",
    "hungry":      "tummy-grumbly",
    "scared":      "scareded",
    "safe":        "safies",
    "comfortable": "comfies",
    "uncomfortable": "icky-uncomfy",
    "good":        "goody",
    "bad":         "meanie",
    "nice":        "nicies",
    "cute":        "cootie-patootie",
    "pretty":      "purdy",
    "beautiful":   "bewootiful",
    "right":       "wight",
    "left":        "weft",
    "yes":         ["yes!", "yesh!", "yesh yesh!"],
    "yeah":        ["yeah~", "yeahhh", "yesh~"],
    "no":          ["noooo", "nope nope", "nu-uh"],
    "not":         "not",
    "very":        "vewy",
    "really":      "weawwy",
    "so":          "shoooo",
    "too":         "tooooo",
    "okay":        ["otay!", "okie dokie!", "okayyy"],
    "ok":          "otay",
    "sorry":       "sowwy",
    "thank":       "fank",
    "thanks":      "fanks",
    "hello":       ["hewwo~", "hewwoooo~", "hii~"],
    "hi":          ["hii~", "hewwo~"],
    "hey":         "heyy~",
    "bye":         ["bai bai~", "byebye~"],
    "goodbye":     "bai bai~",
    "please":      "pwease",
    "now":         "now",
    "here":        "hewe",
    "there":       "dewe",
    "that":        "dat",
    "this":        "dis",
    "it":          "it",
    "just":        "jusht",
    "only":        "onwy",
    "always":      "awways",
    "never":       "nevew",
    "maybe":       "maybie",
    "much":        "muchies",
    "more":        "mowe",
    "less":        "wess",
    "many":        "manymanies",
    "every":       "evewwy",
    "all":         "aww",
    "some":        "shome",
    "any":         "anies",
    "because":     "cuz",
    "but":         "bwut",
    "and":         "adn",
    "or":          "ow",
    "if":          "if",
    "when":        "wen",
    "where":       "whewe",
    "how":         "howww",
    "why":         "whyyy",
    "what":        "wat",
    "who":         "woo",
    "can":         "can",
    "could":       "cowd",
    "would":       "wowd",
    "should":      "showd",
    "will":        "wiww",
    "today":       "today~",
    "tomorrow":    "mowwow",
    "yesterday":   "yestewday",
    "time":        "timmie",
    "day":         "dayzie",
    "night":       "nighties",
    "morning":     "mownin",
    "afternoon":   "aftewnoon",
    "evening":     "ebenin",
    # ABDL-specific
    "diaper":      "diapie",
    "diapers":     "diapies",
    "padding":     "paddie",
    "padded":      "padded",
    "onesie":      "onesie~",
    "onesies":     "onesies~",
    "paci":        "paci~",
    "pacifier":    "paci~",
    "bottle":      "baba",
    "bottles":     "babas",
    "sippy":       "sippy~",
    "stuffed":     "stuffie",
    "stuffie":     "stuffie~",
    "plushie":     "pwushie~",
    "blanket":     "bwankies",
    "blankets":    "bwankies",
    "pillow":      "pillowy",
    "crib":        "cribbie",
    "nursery":     "nursewwy",
    "wet":         "wetties",
    "mess":        "messies",
    "potty":       "potty~",
    "pee":         "tinkle",
    "poop":        "stinkies",
    "stinky":      "stinkies",
    "smell":       "smewwy",
    "smells":      "smewwies",
    "accident":    "uh-oh",
    "accidents":   "uh-ohs",
    "nap":         "nappie",
    "naps":        "nappies",
    "sleep":       "sweepies",
    "sleepy":      "shweepy",
    "tired":       "tiiiired",
    "snuggle":     "snuggies",
    "cuddle":      "cuddlies",
}

_WORD_SUBS_TINY = {
    **_WORD_SUBS_LITTLE,
    # Extra softening for tiny baby mode
    "the":    "da",
    "a":      "a",
    "and":    "an",
    "is":     "iz",
    "in":     "in",
    "on":     "awn",
    "at":     "at",
    "to":     "toooo",
    "of":     "of",
    "it":     "itz",
    "good":   "goo goo",
    "bad":    "boo boo",
    "big":    "biiiig",
    "want":   "wan wan",
    "yes":    ["ga ga!", "goo goo!", "baba!"],
    "no":     ["boo boo!", "waaaah!", "nononono!"],
}

_WORD_SUBS_SWEET = {
    # Sweet/soft mode — more grown-up but still soft
    "love":       "wuv",
    "really":     "really~",
    "very":       "sooo",
    "please":     "pleeease",
    "thank":      "thank~",
    "thanks":     "thanks~",
    "sorry":      "sowwy",
    "hello":      "hiiii~",
    "hi":         "hii~",
    "bye":        "byeee~",
    "goodbye":    "byebye~",
    "okay":       "okayyy~",
    "yes":        "yesss~",
    "no":         "noooo~",
    "cute":       "cute~",
    "happy":      "happy~",
    "sad":        "sad~",
    "need":       "neeed~",
    "want":       "waant~",
    "sleep":      "sleepyyy~",
    "tired":      "tiiired~",
    "diaper":     "diapie~",
    "diapers":    "diapies~",
    "little":     "wittle~",
    "baby":       "babyyyy~",
    "snuggle":    "snuggle~",
    "cuddle":     "cuddle~",
    "safe":       "safe~",
}

_WORD_SUBS_UWUSPEAK = {
    **_WORD_SUBS_LITTLE,
    # UwU / OwO substitutions
    "the":    "teh",
    "have":   "hab",
    "love":   "wuv",
    "with":   "wif",
    "your":   "youw",
    "you":    "chu",
    "this":   "dis",
    "that":   "dat",
    "what":   "wut",
    "want":   "wan",
    "just":   "jus",
    "people": "peopow",
    "like":   "wike",
    "super":  "suuuper",
    "really": "weawy",
    "very":   "vewy",
    "cute":   "kUTE",
    "yes":    ["yesh!", "yes uwu", "uwu"],
    "no":     ["nuuu!", "nwoo", "owo no"],
    "hello":  ["hewwoo uwu", "h-hewwo OwO"],
    "okay":   "otay uwu",
    "please": "pwease uwu",
}

# Sentence-final additions by mode
_ENDINGS: dict[str, list[str]] = {
    "little":  ["~", " :(", " :3", " uwu", "!", "~", "~"],
    "tiny":    [" waaah~", " ugu", " :c", " :(", "~", "!"],
    "sweet":   ["~", "~", " ♡", " :3", "~"],
    "uwu":     [" uwu", " OwO", " UwU", " >w<", " ^w^", " :3", " uwu~"],
    "lisped":  [".", ".", "!", "?", "."],
    "babble":  [" beh beh", " ga ga", " baba~", " wawa~", "~"],
}

# Random sentence starters / interjections inserted occasionally
_STARTERS: dict[str, list[str]] = {
    "little": [
        "hehe, ", "ohhh, ", "ummmm... ", "heehee~ ", "tee hee~ ",
        "*blushes* ", "*fidgets* ", "*giggles* ", "oopsies~ ",
    ],
    "tiny": [
        "waaah! ", "bweh! ", "goo goo~ ", "baba~ ",
        "*cries* ", "*blows raspberries* ", "*claps hands* ",
    ],
    "sweet": [
        "awww~ ", "heehee~ ", "ohhh~ ", "*blushes* ", "sooo... ",
    ],
    "uwu": [
        "OwO ", "UwU ", "h-hewwo! ", "*nuzzles* ", "senpai~ ",
        "OwO wuts dis? ", "*blushes intensely* ",
    ],
    "lisped": [],
    "babble": [
        "buh buh buh! ", "gaga! ", "mamamama~ ", "yabadaba~ ",
    ],
}

# Mid-sentence interjections inserted at random
_INTERJECTIONS: dict[str, list[str]] = {
    "little": ["hehe", "teehee", "uwu", "~~", "*giggle*"],
    "tiny":   ["wah", "goo", "buh buh", "*wibble*"],
    "sweet":  ["~", "heehee", "*smile*"],
    "uwu":    ["uwu", "OwO", ">w<", "*squishes*"],
    "lisped": [],
    "babble": ["buh", "gah", "muh"],
}


# ══════════════════════════════════════════════════════════════════════════════
# Core engine
# ══════════════════════════════════════════════════════════════════════════════

def _apply_word_subs(word: str, table: dict[str, "str | list[str]"]) -> str:
    """Apply word-level substitution, preserving leading/trailing punctuation."""
    # Split off leading/trailing punctuation
    m = re.match(r'^([^a-zA-Z]*)([a-zA-Z\'-]*)([^a-zA-Z]*)$', word)
    if not m:
        return word
    pre, core, post = m.group(1), m.group(2), m.group(3)
    if not core:
        return word

    key = core.lower()
    replacement = table.get(key)
    if replacement is None:
        return word

    if isinstance(replacement, list):
        replacement = random.choice(replacement)

    # Preserve capitalisation: all-caps → all-caps, Title → Title, else lower
    if core.isupper():
        replacement = replacement.upper()
    elif core[0].isupper():
        replacement = replacement[0].upper() + replacement[1:]

    return pre + replacement + post


def _apply_phonemes(text: str, rules: list[tuple[str, str]]) -> str:
    """Apply phoneme substitution rules to text (case-insensitive, preserves case)."""
    result = []
    i = 0
    lower = text.lower()
    while i < len(text):
        replaced = False
        for pattern, sub in rules:
            pl = len(pattern)
            if lower[i:i+pl] == pattern.lower():
                # Preserve capitalisation of first letter
                if text[i].isupper():
                    result.append(sub[0].upper() + sub[1:])
                else:
                    result.append(sub)
                i += pl
                replaced = True
                break
        if not replaced:
            result.append(text[i])
            i += 1
    return ''.join(result)


def _uwuify_word(word: str) -> str:
    """Apply UwU-specific character-level transforms."""
    # ny → nyw  ·  n before vowel → ny
    word = re.sub(r'n([aeiou])', r'ny\1', word, flags=re.IGNORECASE)
    # Stutter: occasionally repeat first syllable
    if len(word) >= 3 and word[0].isalpha() and random.random() < 0.07:
        word = f"{word[0]}-{word}"
    return word


def _stutter_word(word: str) -> str:
    """Add a stutter to the beginning of a word."""
    m = re.match(r'^([^a-zA-Z]*)([a-zA-Z])', word)
    if m and random.random() < 0.12:
        return f"{m.group(1)}{m.group(2)}-{word[len(m.group(1)):]}"
    return word


def _stretch_word(word: str, mode: str) -> str:
    """Randomly stretch vowels in emotional words."""
    if mode in ("little", "sweet", "uwu") and len(word) > 3 and random.random() < 0.15:
        vowels = "aeiou"
        # Find last vowel and stretch it
        for i in range(len(word)-1, 0, -1):
            if word[i].lower() in vowels:
                stretch = random.randint(2, 4)
                return word[:i+1] + word[i] * stretch + word[i+1:]
    return word


def _process_sentence(sentence: str, mode: str) -> str:
    """Transform a single sentence according to mode."""
    if not sentence.strip():
        return sentence

    # Select tables for mode
    if mode == "tiny":
        word_table   = _WORD_SUBS_TINY
        phoneme_rules = _PHONEME_TINY
    elif mode == "sweet":
        word_table   = _WORD_SUBS_SWEET
        phoneme_rules = []   # sweet mode doesn't do heavy phoneme changes
    elif mode == "uwu":
        word_table   = _WORD_SUBS_UWUSPEAK
        phoneme_rules = _PHONEME_LITTLE
    elif mode == "lisped":
        word_table   = {}
        phoneme_rules = _PHONEME_LISP
    elif mode == "babble":
        # Babble mode just converts everything to baby sounds
        return _babblify(sentence)
    else:  # "little" (default)
        word_table   = _WORD_SUBS_LITTLE
        phoneme_rules = _PHONEME_LITTLE

    # Tokenize preserving whitespace and punctuation
    tokens = re.split(r'(\s+)', sentence)
    result = []
    for token in tokens:
        if not token.strip():
            result.append(token)
            continue

        # Apply word substitution first
        new_token = _apply_word_subs(token, word_table)

        # If word wasn't substituted, apply phoneme rules
        if new_token == token and phoneme_rules:
            new_token = _apply_phonemes(token, phoneme_rules)

        # UwU-specific transforms
        if mode == "uwu":
            new_token = _uwuify_word(new_token)

        # Occasional stutter in tiny/little mode
        if mode in ("tiny", "little") and new_token == token:
            new_token = _stutter_word(new_token)

        # Occasional vowel stretching
        new_token = _stretch_word(new_token, mode)

        result.append(new_token)

    return ''.join(result)


def _babblify(text: str) -> str:
    """Convert text to baby babble sounds."""
    babble_words = [
        "buh", "gah", "muh", "wah", "da", "ba", "ma", "ga",
        "baba", "mama", "dada", "wawa", "gaga", "nana",
        "bababa", "mamama", "dadada", "wawawa",
    ]
    words = text.split()
    result = []
    for w in words:
        if w.strip():
            result.append(random.choice(babble_words))
        else:
            result.append(w)
    return ' '.join(result) + " buh buh~"


def _should_add_starter(sentence: str, mode: str) -> bool:
    """Add a starter interjection to ~20% of sentences."""
    return (bool(sentence.strip()) and
            mode in _STARTERS and
            bool(_STARTERS[mode]) and
            random.random() < 0.20)


def _should_add_interjection(mode: str) -> bool:
    return mode in _INTERJECTIONS and bool(_INTERJECTIONS[mode]) and random.random() < 0.08


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def transform(text: str, mode: str = "little",
              add_endings: bool = True,
              add_starters: bool = True,
              seed: int | None = None) -> str:
    """
    Transform text into baby talk / littlespace speech.

    Parameters
    ----------
    text         : input text (any length)
    mode         : one of 'little', 'tiny', 'sweet', 'uwu', 'lisped', 'babble'
    add_endings  : append mode-specific endings to sentences
    add_starters : occasionally prepend interjections to sentences
    seed         : set for deterministic output (useful for tests)

    Returns
    -------
    str : transformed text
    """
    if seed is not None:
        random.seed(seed)

    if not text or not text.strip():
        return text

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    output_sentences = []

    for sentence in sentences:
        if not sentence.strip():
            continue

        transformed = _process_sentence(sentence, mode)

        # Occasionally insert a mid-sentence interjection
        if add_starters and _should_add_interjection(mode):
            words = transformed.split(' ', 2)
            if len(words) >= 2:
                interj = random.choice(_INTERJECTIONS[mode])
                transformed = f"{words[0]} {interj} {' '.join(words[1:])}"

        # Add ending flourish
        if add_endings and mode in _ENDINGS:
            # Remove existing sentence-final punctuation before adding ours
            transformed = transformed.rstrip()
            existing_punct = ""
            while transformed and transformed[-1] in '.!?':
                existing_punct = transformed[-1] + existing_punct
                transformed = transformed[:-1]
            ending = random.choice(_ENDINGS[mode])
            # Keep ! if original had it, but add mode ending too
            if "!" in existing_punct and ending not in ("!", "!"):
                transformed = transformed + "!" + ending
            elif existing_punct:
                transformed = transformed + existing_punct + ending
            else:
                transformed = transformed + ending

        # Prepend starter to some sentences
        if add_starters and _should_add_starter(sentence, mode):
            starter = random.choice(_STARTERS[mode])
            transformed = starter + transformed

        output_sentences.append(transformed)

    result = "  ".join(output_sentences)
    # When endings suppressed, also strip ~ that leaked in from word substitutions
    if not add_endings:
        result = re.sub(r'~+', '', result).strip()
    return result


def available_modes() -> list[tuple[str, str, str]]:
    """
    Return list of (key, emoji_label, description) for all available modes.
    Used by the UI to populate the mode selector.
    """
    return [
        ("little",  "🍼 Little Space",   "Soft toddler speech — w for r/l, word babying, tilde endings"),
        ("tiny",    "👶 Tiny Baby",       "Very heavy baby talk — near-incomprehensible, max cuteness"),
        ("sweet",   "🌸 Sweet & Soft",    "Gentle softening — light touch, stays mostly legible"),
        ("uwu",     "🐾 UwU / OwO",       "Furry/weeb-adjacent soft speech — uwu, OwO, nyas"),
        ("lisped",  "😛 Lisped",          "Lisp simulation — s→th, z→th, minimal other changes"),
        ("babble",  "🐣 Baby Babble",     "Full babble — replaces words with buh bah gah sounds"),
    ]


def mode_info(key: str) -> dict:
    """Return info dict for a single mode."""
    for k, label, desc in available_modes():
        if k == key:
            return {"key": k, "label": label, "description": desc}
    return {}


# ── Demo / quick test ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    test = (
        "I really love wearing diapers. They make me feel safe and comfortable. "
        "I need to go to the bathroom. Can you please give me a hug? "
        "I am very happy right now and I do not want to stop playing."
    )
    print("ORIGINAL:")
    print(test)
    for mode_key, label, _ in available_modes():
        print(f"\n{label.upper()} ({mode_key}):")
        print(transform(test, mode=mode_key, seed=42))
