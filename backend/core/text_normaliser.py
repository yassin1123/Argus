import re


def normalise_query(query: str) -> str:
    query = query.strip()
    query = re.sub(r"\s+", " ", query)
    query = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", query)
    if len(query) < 10:
        raise ValueError("Query too short to process meaningfully")
    if len(query) > 10000:
        raise ValueError("Query exceeds maximum length of 10000 characters")
    return query
