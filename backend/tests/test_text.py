from shiftnet_backend.discovery.text import default_forms, forms_pattern, occurrences

words = lambda s: len(s.split())  # noqa: E731


def test_default_forms():
    assert default_forms("cloud") == ["cloud", "clouds"]
    assert default_forms("bus") == ["bus", "buses"]
    assert default_forms("spy") == ["spy", "spies"]
    assert default_forms("day") == ["day", "days"]
    assert default_forms("hot dog") == ["hot dog", "hot dogs"]


def test_pattern_is_whole_word_and_case_insensitive():
    p = forms_pattern(["cloud", "clouds", "hot dog"])
    assert p.search("Clouds gathered")
    assert p.search("a hot\n dog stand")
    assert not p.search("cloudy skies")
    assert not p.search("a cloud-based app")  # hyphenated compounds are a different word
    assert not p.search("overclouds")


def test_occurrence_keeps_punctuation_and_span():
    text = "Menu. Clouds\n\nThe dark clouds, heavy with rain, rolled in over the hills that morning."
    (o,) = occurrences(text, forms_pattern(["cloud", "clouds"]), words, max_tokens=64)
    assert o.context == "The dark clouds, heavy with rain, rolled in over the hills that morning."
    assert o.context[o.start : o.end] == "clouds"


def test_long_sentence_is_trimmed_around_the_target():
    left = " ".join(f"l{i}" for i in range(40))
    right = " ".join(f"r{i}" for i in range(10))
    text = f"{left} cloud {right}."
    (o,) = occurrences(text, forms_pattern(["cloud"]), words, max_tokens=20)
    assert words(o.context) + 2 <= 20
    assert o.context[o.start : o.end] == "cloud"
    left_words, right_words = o.context[: o.start].split(), o.context[o.end :].split()
    assert abs(len(left_words) - len(right_words)) <= 1  # the target stays centred
    assert left_words[-1] == "l39" and right_words[0] == "r0"


def test_short_and_repeated_sentences_are_skipped():
    p = forms_pattern(["cloud"])
    text = "Cloud storage. We keep every file in the cloud now. We keep every file in the cloud now."
    found = list(occurrences(text, p, words, max_tokens=64))
    assert [o.context for o in found] == ["We keep every file in the cloud now."]


def test_max_per_doc():
    text = " ".join(f"Sentence {i} talks about the cloud at some length today." for i in range(5))
    assert len(list(occurrences(text, forms_pattern(["cloud"]), words, 64, max_per_doc=2))) == 2


def test_crawl_date_fallbacks():
    from datetime import date

    from shiftnet_backend.discovery.corpus import crawl_date

    assert crawl_date({"date": "2024-02-20T10:00:00Z"}) == date(2024, 2, 20)
    warc = "s3://commoncrawl/crawl-data/CC-MAIN-2013-20/segments/1/warc/CC-MAIN-20130516092621-00000-ip.warc.gz"
    assert crawl_date({"file_path": warc, "dump": "CC-MAIN-2013-20"}) == date(2013, 5, 16)
    assert crawl_date({}, "CC-MAIN-2013-20") == date(2013, 5, 13)  # Monday of week 20
    assert crawl_date({}) is None
