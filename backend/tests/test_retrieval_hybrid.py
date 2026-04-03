from core.retrieval import _lexical_overlap_score


def test_lexical_overlap_score_basic() -> None:
    assert _lexical_overlap_score("alpha beta gamma", "alpha beta delta") > 0.4
    assert _lexical_overlap_score("", "hello") == 0.0
