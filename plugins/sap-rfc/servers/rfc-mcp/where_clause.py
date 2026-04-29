import textwrap


def chunk_where(text: str) -> list[str]:
    """
    Split a WHERE clause into chunks of max 72 characters.

    Args:
        text: WHERE clause string to chunk

    Returns:
        List of chunks, each max 72 chars. Empty list if input is empty.
    """
    if not text:
        return []
    return textwrap.wrap(text, 72, drop_whitespace=False, break_on_hyphens=False)
