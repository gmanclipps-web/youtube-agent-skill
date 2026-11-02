from pipeline import captions


def _w(word, start, end, beat):
    return {"word": word, "start": start, "end": end, "beat": beat}


def _seven_in_one_beat():
    names = ["one", "two", "three", "four", "five", "six", "seven"]
    return [_w(n, i * 0.5, i * 0.5 + 0.4, 0) for i, n in enumerate(names)]


def test_seven_words_one_beat_chunks_3_3_1():
    chunks = captions.chunk_words(_seven_in_one_beat(), max_words=3)
    assert [len(c["words"]) for c in chunks] == [3, 3, 1]
    assert chunks[0]["start"] == 0.0
    assert chunks[0]["end"] == chunks[0]["words"][-1]["end"]
    assert chunks[2]["start"] == chunks[2]["words"][0]["start"]


def test_chunks_never_mix_beats():
    words = [
        _w("a", 0.0, 0.4, 0), _w("b", 0.5, 0.9, 0),
        _w("c", 1.5, 1.9, 1), _w("d", 2.0, 2.4, 1), _w("e", 2.5, 2.9, 1),
        _w("f", 3.5, 3.9, 2),
    ]
    chunks = captions.chunk_words(words, max_words=3)
    for c in chunks:
        assert len({w["beat"] for w in c["words"]}) == 1
    assert [[w["word"] for w in c["words"]] for c in chunks] == [
        ["a", "b"], ["c", "d", "e"], ["f"]]


def test_chunk_words_empty():
    assert captions.chunk_words([]) == []


def test_active_at_midpoint_returns_word_index():
    chunks = captions.chunk_words(_seven_in_one_beat(), max_words=3)
    # word index 1 in the first chunk is "two": start 0.5, end 0.9
    chunk, idx = captions.active(chunks, 0.7)
    assert chunk is chunks[0]
    assert idx == 1


def test_active_after_last_end_returns_none():
    chunks = captions.chunk_words(_seven_in_one_beat(), max_words=3)
    assert captions.active(chunks, 99.0) == (None, -1)


def test_active_before_first_start_returns_none():
    chunks = captions.chunk_words(_seven_in_one_beat(), max_words=3)
    assert captions.active(chunks, -1.0) == (None, -1)


def test_active_in_gap_between_words_returns_minus_one():
    words = [_w("a", 0.0, 0.4, 0), _w("b", 1.0, 1.4, 0)]
    chunks = captions.chunk_words(words, max_words=3)
    chunk, idx = captions.active(chunks, 0.7)
    assert chunk is chunks[0]
    assert idx == -1


def test_caption_text_joins_words_with_spaces():
    chunks = captions.chunk_words(_seven_in_one_beat(), max_words=3)
    assert captions.caption_text(chunks) == "one two three four five six seven"


def test_caption_text_empty():
    assert captions.caption_text([]) == ""


def test_chunks_break_after_sentence_end():
    words = [_w("snacks.", 0.0, 0.4, 0), _w("Nobody", 0.5, 0.9, 0), _w("told", 1.0, 1.3, 0),
             _w("you", 1.4, 1.6, 0), _w("why?", 1.7, 2.0, 0), _w("Same", 2.1, 2.3, 0),
             _w("snack!", 2.4, 2.7, 0), _w("Wow", 2.8, 3.0, 0)]
    chunks = captions.chunk_words(words, max_words=3)
    assert [[w["word"] for w in c["words"]] for c in chunks] == [
        ["snacks."], ["Nobody", "told", "you"], ["why?"], ["Same", "snack!"], ["Wow"]]
    two = captions.chunk_words([_w("snacks.", 0, 0.4, 0), _w("Nobody", 0.5, 0.9, 0),
                                _w("told", 1.0, 1.3, 0)])
    assert [[w["word"] for w in c["words"]] for c in two] == [["snacks."], ["Nobody", "told"]]
    # closing quotes or brackets after the mark still end the sentence
    q = captions.chunk_words([_w('"Hi."', 0, 0.4, 0), _w("Bye", 0.5, 0.9, 0)])
    assert len(q) == 2


def test_sentence_ends_from_script_line():
    # edge-tts word boundaries carry no punctuation: take it from the script line
    words = [{"word": w} for w in ["Your", "100", "dollars", "lost", "a", "bag", "of", "snacks",
                                   "Nobody", "told", "you", "why"]]
    line = "Your 100 dollars lost a bag of snacks. Nobody told you why."
    ends = captions.sentence_ends(line, words)
    assert ends == [False] * 7 + [True] + [False] * 3 + [True]
    # a token split into several boundaries ("Earth's" -> "Earth", "s") ends on its last piece
    ends = captions.sentence_ends("Earth's CPI. Wow", [{"word": "Earth"}, {"word": "s"},
                                                       {"word": "CPI"}, {"word": "Wow"}])
    assert ends == [False, False, True, False]
    # unknown words never break alignment of later ones
    ends = captions.sentence_ends("Hi there. Bye.", [{"word": "Hi"}, {"word": "zz"},
                                                    {"word": "there"}, {"word": "Bye"}])
    assert ends == [False, False, True, True]


def test_chunks_break_on_flagged_sentence_end():
    words = [_w("snacks", 0.0, 0.4, 0), _w("Nobody", 0.5, 0.9, 0), _w("told", 1.0, 1.3, 0)]
    words[0]["sentence_end"] = True
    chunks = captions.chunk_words(words)
    assert [[w["word"] for w in c["words"]] for c in chunks] == [["snacks"], ["Nobody", "told"]]


def test_sentence_ends_word_spanning_tokens():
    # edge-tts may voice "100 dollars." as one boundary
    ends = captions.sentence_ends("It is 100 dollars. Wow.", [{"word": "It"}, {"word": "is"},
                                  {"word": "100 dollars"}, {"word": "Wow"}])
    assert ends == [False, False, True, True]
