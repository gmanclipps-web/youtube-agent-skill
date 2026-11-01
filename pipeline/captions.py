"""Group word timings into on-screen caption chunks and look up what is active."""


def _chunk(words: list[dict]) -> dict:
    return {"words": words, "start": words[0]["start"], "end": words[-1]["end"]}


def chunk_words(words: list[dict], max_words: int = 3) -> list[dict]:
    """Split word timings into chunks of at most max_words. A chunk never
    spans two beats, so a caption never sits across a scene cut."""
    chunks: list[dict] = []
    run: list[dict] = []
    for w in words:
        if run and (w["beat"] != run[0]["beat"] or len(run) == max_words):
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
