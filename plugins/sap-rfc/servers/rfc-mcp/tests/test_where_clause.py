from where_clause import chunk_where


def test_short_clause_one_chunk():
    assert chunk_where("MANDT EQ '100'") == ["MANDT EQ '100'"]


def test_long_clause_wrapped_at_72():
    text = "A" * 100
    chunks = chunk_where(text)
    assert all(len(c) <= 72 for c in chunks)
    assert "".join(chunks) == text


def test_empty_returns_empty_list():
    assert chunk_where("") == []
