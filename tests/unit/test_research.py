"""
Unit tests for research Pydantic schema validation.
"""
from __future__ import annotations

import pytest
from app.research.schemas import (
    ResearchResult,
    Fact,
    Claim,
    Statistic,
    DateEvent,
    Person,
    Location,
    UncertainClaim,
)


class TestResearchResult:
    def test_empty_result(self):
        r = ResearchResult(topic="test")
        assert r.facts == []
        assert r.claims == []

    def test_full_result(self):
        r = ResearchResult(
            topic="Black holes",
            summary="A summary",
            facts=[{"fact": "Black holes warp space", "confidence": 0.99}],
            claims=[{"claim": "Black holes evaporate", "source": "Hawking 1974", "confidence": 0.9}],
            statistics=[{"stat": "First image: 2019", "source": "EHT", "confidence": 1.0}],
            dates=[{"event": "First BH image", "date": "April 2019", "confidence": 1.0}],
            people=[{"name": "Stephen Hawking", "role": "Theoretical physicist"}],
            locations=[{"name": "M87", "relevance": "First photographed black hole"}],
            uncertain_claims=[{"claim": "Black holes contain universes", "note": "Speculative"}],
        )
        assert len(r.facts) == 1
        assert r.facts[0].confidence == 0.99
        assert r.people[0].name == "Stephen Hawking"

    def test_none_lists_coerced(self):
        r = ResearchResult(topic="t", facts=None, claims=None, statistics=None)
        assert r.facts == []
        assert r.claims == []
        assert r.statistics == []

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            Fact(fact="x", confidence=1.5)   # > 1.0 should fail
