"""Trivia screening. Blocked words are read from data/safety/*.txt, never written here; owner-list entries are made up."""
import pytest

from bamboozled.services.safety import DATA, Screen, tokens, _load

HARMLESS = [
    "What is the first class of a train called?", "Which student passes the exam with the best score?",
    "A cucumber is mostly made of what?", "What does a nutritionist mean by a diet?", "Which English county is Essex?",
    "Who assassinated Julius Caesar in the Senate?", "Which Kerala city is Thiruvananthapuram's neighbour?",
    "Kochi, Alappuzha and Kasaragod are all in which state?", "Which river flows through Kozhikode?",
    "What is the capital of Wayanad district?", "Who wrote the Odyssey?", "Which hill station is Munnar near?",
    "Scunthorpe is a town in which country?", "What is a grassland pass called in the mountains?",
    "Which assassin features in Greek tragedy?", "The Battle of Hastings was in which year?",
    "How many bones are in the human body?", "Which planet has the most moons?", "Who painted the Mona Lisa?",
    "Mississippi has how many letters s?", "What is 7 x 8?", "Which compass bearing is the opposite of north?",
    "Who was the Roman goddess of love?", "What is a cocktail made of?", "Which bassoon is a woodwind?",
    "A shiitake is what kind of organism?", "Which Greek hero killed the Minotaur?",
    "Who was the god of the dead in Egyptian myth?",
    "Which assistant coach won the trophy?", "What is the dessert tiramisu made from?",
    "Which city hosts the Sussex county ground?",
    "Which Vedic hymn collection is the oldest?", "മലയാളം കേരളത്തിന്റെ ഔദ്യോഗിക ഭാഷയാണ്", "കൊച്ചി ഒരു തുറമുഖ നഗരമാണ്",
]


@pytest.fixture(scope="module")
def screen():
    return Screen()


@pytest.mark.parametrize("text", HARMLESS)
def test_harmless_text_passes_in_both_modes(screen, text):
    assert screen.is_clean(text) and screen.is_clean(text, strictness="strict")


def _forms(entry: str):
    letters = list(entry.replace(" ", ""))
    inverse = {"o": "0", "i": "1", "e": "3", "a": "4", "s": "5", "t": "7"}
    yield "plain", entry
    yield "spaced", " ".join(letters)
    yield "dotted", ".".join(letters)
    yield "leet", "".join(inverse.get(c, c) for c in entry)
    yield "in a sentence", f"Which of these is {entry} really?"
    yield "stretched", f"{entry[0] * 4}{entry[1:]}" if len(entry) > 4 else entry
    yield "fullwidth", entry.upper().translate({c: c + 0xFEE0 for c in range(0x21, 0x7F)})


ALWAYS = [" ".join(t) for t in _load(DATA / "always.txt")]


def test_the_always_list_is_loaded():
    assert len(ALWAYS) >= 50


@pytest.mark.parametrize("entry", ALWAYS)
def test_every_always_term_is_rejected_in_every_form(screen, entry):
    for name, text in _forms(entry):
        assert not screen.is_clean(text), f"{name} form got through"


def test_contextual_terms_only_in_strict_mode(screen):
    ctx = [" ".join(t) for t in _load(DATA / "contextual.txt")]
    assert ctx
    for term in ctx:
        text = f"In history, what does {term} mean?"
        assert screen.is_clean(text, strictness="standard")
        assert not screen.is_clean(text, strictness="strict")


def test_every_part_of_a_question_is_screened(screen):
    bad = ALWAYS[0]
    assert not screen.is_clean("fine question", "fine answer", bad)


def test_owner_blocklist_and_allowlist(tmp_path):
    (tmp_path / "blocklist.txt").write_text("# header\nzorbo\nമണ്ടൻ പൊട്ടൻ\nflib flob\n", encoding="utf-8")
    (tmp_path / "allowlist.txt").write_text("zorbo\n", encoding="utf-8")
    s = Screen(directory=tmp_path)
    assert not s.is_clean("what a മണ്ടൻ പൊട്ടൻ idea")                  # Malayalam script entry, with its vowel signs
    assert not s.is_clean("This is FLIB, flob!")
    assert s.is_clean("zorbo is allowed")                               # allowlisted word
    assert s.is_clean("കൊച്ചി ഒരു നഗരമാണ്")                              # harmless Malayalam
    assert s.is_clean("flib alone is fine")


def test_malayalam_vowel_signs_do_not_split_words():
    assert tokens("കൊച്ചി നഗരം") == ["കൊച്ചി", "നഗരം"]


def test_a_missing_directory_means_nothing_is_blocked(tmp_path):
    assert Screen(directory=tmp_path).is_clean("anything at all")
