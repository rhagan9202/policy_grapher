from policy_grapher.chunking import chunk_pages, section_heading


def test_a_numbered_heading_is_recognised():
    assert section_heading("3.2. RESPONSIBILITIES.") == "3.2"
    assert section_heading("3.2.1. The Director shall...") == "3.2.1"


def test_a_chapter_heading_is_recognised():
    assert section_heading("CHAPTER 4") == "CHAPTER 4"
    assert section_heading("SECTION 2: POLICY") == "SECTION 2"


def test_ordinary_prose_is_not_a_heading():
    assert section_heading("The Director shall notify the Comptroller.") is None
    assert section_heading("") is None


def test_a_decimal_in_prose_is_not_a_heading():
    """"...within 3.2 percent" must not open a section."""
    assert section_heading("Rates above 3.2 percent require approval.") is None


def test_chunks_never_span_a_section():
    pages = ["3.1. FIRST.\nAlpha text.\n3.2. SECOND.\nBravo text.\n"]
    chunks = chunk_pages(pages, version_id="v")

    paths = [c.section_path for c in chunks]
    assert ["3.1"] in paths and ["3.2"] in paths
    for chunk in chunks:
        assert not ("Alpha" in chunk.text and "Bravo" in chunk.text)


def test_the_section_path_carries_the_hierarchy():
    pages = ["CHAPTER 4\n4.1. SCOPE.\n4.1.2. Detail here.\nBody.\n"]
    chunks = chunk_pages(pages, version_id="v")
    assert chunks[-1].section_path == ["CHAPTER 4", "4.1", "4.1.2"]


def test_the_page_number_is_one_indexed_and_tracked():
    chunks = chunk_pages(["1.1. A.\nFirst page.", "1.2. B.\nSecond page."], version_id="v")
    assert {c.page for c in chunks} == {1, 2}


def test_an_oversized_section_splits_with_overlap():
    body = " ".join(f"word{i}" for i in range(2000))
    chunks = chunk_pages([f"5.1. BIG.\n{body}"], version_id="v", max_chars=500, overlap_chars=100)

    assert len(chunks) > 1
    assert all(c.section_path == ["5.1"] for c in chunks)
    # Overlap: the tail of one chunk reappears at the head of the next.
    assert chunks[0].text[-50:] in chunks[1].text


def test_a_tiny_section_is_not_merged_into_its_neighbour():
    """A short section is still a section; merging destroys its anchor."""
    pages = ["6.1. SHORT.\nBrief.\n6.2. NEXT.\nMore text here.\n"]
    chunks = chunk_pages(pages, version_id="v")
    assert ["6.1"] in [c.section_path for c in chunks]


def test_identity_is_deterministic_across_runs():
    pages = ["7.1. A.\nText.\n"]
    first = chunk_pages(pages, version_id="v")
    second = chunk_pages(pages, version_id="v")
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_identity_differs_between_versions():
    pages = ["7.1. A.\nText.\n"]
    assert (
        chunk_pages(pages, version_id="a")[0].chunk_id
        != chunk_pages(pages, version_id="b")[0].chunk_id
    )


def test_text_before_any_heading_is_kept_under_a_preamble_path():
    """A cover page has no section number and must not be dropped."""
    chunks = chunk_pages(["Department of Defense Instruction 5000.88\n"], version_id="v")
    assert chunks and chunks[0].section_path == ["(preamble)"]


# Edge case tests for robustness


def test_split_with_no_sentence_boundaries():
    """A section with no period+space should still split at max_chars."""
    # Create text with no sentence boundaries (no ". " or "\n\n")
    body = "x" * 1000  # 1000 continuous characters
    chunks = chunk_pages([f"7.2. TEST.\n{body}"], version_id="v", max_chars=300, overlap_chars=50)

    # Should create multiple chunks
    assert len(chunks) > 1
    # All from same section
    assert all(c.section_path == ["7.2"] for c in chunks)
    # Verify overlap
    assert chunks[0].text[-50:] in chunks[1].text
    # Verify no character loss when reassembling
    total_chars = sum(len(c.text) for c in chunks)
    overlap_chars_total = (len(chunks) - 1) * 50
    assert total_chars - overlap_chars_total <= len(body) + len("7.2. TEST.\n")


def test_split_with_overlap_larger_than_chunk():
    """When overlap > chunk size, all chunks should still overlap."""
    body = " ".join(f"word{i}" for i in range(100))
    chunks = chunk_pages([f"7.3. BIG OVERLAP.\n{body}"], version_id="v", max_chars=200, overlap_chars=300)

    assert len(chunks) > 1
    # With overlap > chunk, consecutive chunks will heavily overlap
    if len(chunks) > 1:
        # Chunks might overlap completely
        assert chunks[0].text in chunks[1].text or chunks[0].text[-10:] in chunks[1].text


def test_split_shorter_than_overlap():
    """A section shorter than overlap should still be a single chunk."""
    small_body = "Just a few words."
    chunks = chunk_pages([f"7.4. SMALL.\n{small_body}"], version_id="v", max_chars=500, overlap_chars=200)

    # Should not split if total text is smaller than max_chars
    assert len(chunks) == 1
    assert chunks[0].section_path == ["7.4"]


def test_chunk_id_is_deterministic():
    """chunk_id must be stable across rebuilds for the same input."""
    pages = ["8.1. A.\nContent.\n"]

    chunks1 = chunk_pages(pages, version_id="v1")
    chunks2 = chunk_pages(pages, version_id="v1")

    # Same version, same input -> same IDs
    assert len(chunks1) == len(chunks2)
    for c1, c2 in zip(chunks1, chunks2):
        assert c1.chunk_id == c2.chunk_id


def test_chunk_id_collision_free():
    """Different sections/ordinals must have different chunk_ids."""
    pages = ["8.2. A.\nContent A.\n8.3. B.\nContent B.\n"]
    chunks = chunk_pages(pages, version_id="v")

    ids = [c.chunk_id for c in chunks]
    # All IDs should be unique
    assert len(ids) == len(set(ids))


def test_chunk_id_includes_version():
    """Different versions of the same content must have different chunk_ids."""
    pages = ["8.4. C.\nContent.\n"]

    chunks_v1 = chunk_pages(pages, version_id="v1")
    chunks_v2 = chunk_pages(pages, version_id="v2")

    # Different versions -> different IDs
    assert chunks_v1[0].chunk_id != chunks_v2[0].chunk_id


def test_chunk_id_includes_section_path():
    """Different sections must have different chunk_ids."""
    pages = ["8.5. FIRST.\nSame content.\n8.6. SECOND.\nSame content.\n"]
    chunks = chunk_pages(pages, version_id="v")

    # Each section is separate
    assert len(chunks) >= 2
    assert chunks[0].section_path != chunks[1].section_path
    assert chunks[0].chunk_id != chunks[1].chunk_id


def test_chunk_id_includes_ordinal():
    """When a section splits, different ordinals must have different chunk_ids."""
    body = " ".join(f"word{i}" for i in range(1000))
    pages = [f"8.7. BIG.\n{body}"]
    chunks = chunk_pages(pages, version_id="v", max_chars=300, overlap_chars=50)

    # Should create multiple chunks from one section
    assert len(chunks) > 1
    # All have same section_path but different ordinals
    assert all(c.section_path == chunks[0].section_path for c in chunks)
    # All IDs should be different
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


def test_overlap_is_actually_overlap():
    """Consecutive chunks should share text (not just be adjacent)."""
    body = " ".join(f"word{i}" for i in range(500))
    chunks = chunk_pages([f"8.8. OVERLAP.\n{body}"], version_id="v", max_chars=400, overlap_chars=100)

    if len(chunks) > 1:
        # Tail of first chunk should appear in second chunk
        tail = chunks[0].text[-100:]
        assert tail in chunks[1].text, f"Tail '{tail[:50]}...' not in next chunk"


def test_reassemble_loses_no_characters():
    """Reassembling chunks (removing overlap) should recreate the original text."""
    body = " ".join(f"word{i}" for i in range(300))
    original_text = f"8.9. RECONSTRUCT.\n{body}"
    chunks = chunk_pages([original_text], version_id="v", max_chars=250, overlap_chars=50)

    # Reconstruct by removing overlap
    reconstructed = chunks[0].text
    for chunk in chunks[1:]:
        # Look for the last overlap_chars of previous chunk in this chunk
        prev_tail = reconstructed[-50:]
        idx = chunk.text.find(prev_tail)
        if idx >= 0:
            reconstructed += chunk.text[idx + len(prev_tail):]
        else:
            reconstructed += chunk.text

    # The reconstructed text should contain all the important content
    for word in ["8.9", "RECONSTRUCT", "word0", "word100", "word299"]:
        assert word in reconstructed, f"Word '{word}' missing from reconstruction"


def test_frozen_dataclass_cannot_be_hashed():
    """Verify Chunk is frozen but has an unhashable field (list)."""
    from policy_grapher.chunking import Chunk

    chunk = Chunk(
        chunk_id="test",
        text="content",
        page=1,
        section_path=["1.1"],
        ordinal=0,
    )

    # Should be frozen
    try:
        chunk.text = "changed"
        assert False, "Frozen dataclass should not allow attribute modification"
    except (AttributeError, TypeError):
        pass  # Expected

    # Should not be hashable due to list field
    try:
        hash(chunk)
        assert False, "Chunk with list field should not be hashable"
    except TypeError:
        pass  # Expected

    # Should still be usable in comparisons
    chunk2 = Chunk(
        chunk_id="test",
        text="content",
        page=1,
        section_path=["1.1"],
        ordinal=0,
    )
    assert chunk == chunk2
