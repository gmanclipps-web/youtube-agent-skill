"""Group word timings into on-screen caption chunks and look up what is active."""
import re


def _chunk(words: list[dict]) -> dict:
    return {"words": words, "start": words[0]["start"], "end": words[-1]["end"]}


_SENTENCE_END = re.compile(r"[.!?][\"'\u2019\u201d)\]]*$")


def ends_sentence(word: str) -> bool:
    """True for a word ending in . ! or ? (closing quotes/brackets allowed after)."""
    return bool(_SENTENCE_END.search(word))


def _norm(s: str) -> str:
    return re.sub(r"[^\w]", "", s.lower())


def sentence_ends(line: str, words: list[dict]) -> list[bool]:
    """For each word timing (in order), whether it closes a sentence of ``line``.

    TTS word boundaries carry no punctuation, so each word is matched to the
    script token it comes from (a token may span several boundaries, e.g.
    "Earth's" -> "Earth", "s"); the last piece of a token that ends in . ! or ?
    ends a sentence. Words that match no nearby token are never ends."""
    tokens = [(_norm(t), ends_sentence(t)) for t in line.split()]
    tokens = [t for t in tokens if t[0]]
    out = []
    j, rest = 0, tokens[0][0] if tokens else ""
    for w in words:
        wn = _norm(str(w.get("word", "")))
        hit = False
        if wn and j < len(tokens):
            if not rest.startswith(wn):          # resync on one of the next tokens
                for k in range(j + 1, min(j + 4, len(tokens))):
                    if tokens[k][0].startswith(wn):
                        j, rest = k, tokens[k][0]
                        break
            while wn and j < len(tokens) and wn.startswith(rest):   # spans whole tokens
                wn = wn[len(rest):]
                hit = tokens[j][1]
                j += 1
                rest = tokens[j][0] if j < len(tokens) else ""
            if wn and rest.startswith(wn):
                rest = rest[len(wn):]
                hit = False
                if not rest:
                    hit = tokens[j][1]
                    j += 1
                    rest = tokens[j][0] if j < len(tokens) else ""
        out.append(hit)
    return out


def chunk_words(words: list[dict], max_words: int = 3) -> list[dict]:
    """Split word timings into chunks of at most max_words. A chunk never
    spans two beats (so a caption never sits across a scene cut) and never
    runs past a sentence end (a word ending in . ! or ?, or flagged
    ``sentence_end`` by the voice)."""
    chunks: list[dict] = []
    run: list[dict] = []
    for w in words:
        if run and (w["beat"] != run[0]["beat"] or len(run) == max_words
                    or run[-1].get("sentence_end") or ends_sentence(run[-1]["word"])):
            chunks.append(_chunk(run))
            run = []
        run.append(w)
    if run:
        chunks.append(_chunk(run))
    return chunks


def active(chunks: list[dict], t: float) -> tuple[dict | None, int]:
    """Return the chunk shown at time t and the index of the word being
    spoken within it, or -1 when t falls in a gap between its words.
    Returns (None, -1) when no chunk covers t."""
    found = None
    for chunk in chunks:
        if chunk["start"] <= t <= chunk["end"]:
            for i, w in enumerate(chunk["words"]):
                if w["start"] <= t < w["end"]:
                    return chunk, i
            found = found or chunk
    return (found, -1) if found is not None else (None, -1)


def caption_text(chunks: list[dict]) -> str:
    """All caption words in order, space-joined."""
    return " ".join(w["word"] for c in chunks for w in c["words"])
