"""Tests for the self-evolving PatternRepository."""
import pytest
from daemon.patterns import PatternRepository, Pattern, PatternStatus


@pytest.fixture
def repo():
    return PatternRepository()


@pytest.mark.asyncio
async def test_observe_new_pattern(repo):
    """First observation creates a candidate pattern with base confidence."""
    pattern = await repo.observe(
        pattern_text="auth.py always uses bcrypt for password hashing",
        project="proj-a",
        agent_id="agent-1",
        kind="PATTERN",
    )
    assert pattern.id
    assert pattern.status == PatternStatus.CANDIDATE
    assert pattern.confidence == 0.3  # base confidence for first sighting
    assert pattern.observation_count == 1


@pytest.mark.asyncio
async def test_repeated_observation_increases_confidence(repo):
    """Same pattern observed multiple times boosts confidence."""
    await repo.observe(
        pattern_text="auth.py always uses bcrypt for password hashing",
        project="proj-a",
        agent_id="agent-1",
    )
    pattern = await repo.observe(
        pattern_text="auth.py always uses bcrypt for password hashing",
        project="proj-a",
        agent_id="agent-2",  # different agent
    )
    assert pattern.confidence > 0.3  # increased
    assert pattern.observation_count == 2
    assert pattern.status == PatternStatus.CANDIDATE  # still candidate


@pytest.mark.asyncio
async def test_cross_project_observation_fast_tracks(repo):
    """Same pattern seen in multiple projects fast-tracks to VERIFIED."""
    await repo.observe("auth.py uses bcrypt", "proj-a", "agent-1")
    await repo.observe("auth.py uses bcrypt", "proj-b", "agent-2")

    # After 2 projects, should be verified
    pattern = await repo.observe("auth.py uses bcrypt", "proj-c", "agent-3")
    assert pattern.status == PatternStatus.VERIFIED
    assert pattern.confidence >= 0.7


@pytest.mark.asyncio
async def test_established_pattern_after_enough_observations(repo):
    """Many observations across projects elevates to ESTABLISHED."""
    for i in range(10):
        await repo.observe(
            "singleton config pattern",
            f"proj-{i % 3}",
            f"agent-{i}",
        )

    patterns = await repo.list_patterns(status=PatternStatus.ESTABLISHED)
    assert len(patterns) >= 1


@pytest.mark.asyncio
async def test_pattern_normalization_is_whitespace_insensitive(repo):
    """Patterns are normalized (whitespace-collapsed, lowercased) for matching."""
    p1 = await repo.observe("  auth.py uses bcrypt  ", "proj-a", "agent-1")
    p2 = await repo.observe("auth.py uses bcrypt", "proj-a", "agent-2")
    assert p1.id == p2.id  # same pattern
    assert p2.observation_count == 2


@pytest.mark.asyncio
async def test_deprecate_pattern(repo):
    """Patterns can be marked as deprecated."""
    pattern = await repo.observe("old pattern", "proj-a", "agent-1")
    await repo.deprecate(pattern.id, reason="No longer relevant")
    p = await repo.get_pattern(pattern.id)
    assert p.status == PatternStatus.DEPRECATED
    assert "No longer relevant" in p.deprecation_reason


@pytest.mark.asyncio
async def test_list_patterns_by_project(repo):
    """Patterns can be filtered by project."""
    await repo.observe("p1", "proj-a", "agent-1")
    await repo.observe("p2", "proj-b", "agent-1")

    proj_a = await repo.list_patterns(project="proj-a")
    assert len(proj_a) >= 1
    assert all("proj-a" in p.projects for p in proj_a)


@pytest.mark.asyncio
async def test_top_patterns_sorted_by_confidence(repo):
    """Top patterns are sorted by confidence descending."""
    await repo.observe("rare pattern", "proj-a", "agent-1")  # conf ~0.3
    for _ in range(5):
        await repo.observe("common pattern", "proj-x", f"agent-{_}")

    top = await repo.top_patterns(limit=3)
    assert top[0].pattern_text == "common pattern"
    assert top[0].confidence > top[-1].confidence


@pytest.mark.asyncio
async def test_cross_project_patterns(repo):
    """Cross-project patterns can be queried specifically."""
    await repo.observe("x", "proj-a", "agent-1")
    await repo.observe("x", "proj-b", "agent-1")
    await repo.observe("y", "proj-a", "agent-1")

    cross = await repo.cross_project_patterns()
    assert len(cross) == 1
    assert cross[0].pattern_text == "x"


@pytest.mark.asyncio
async def test_observing_a_deprecated_pattern_does_not_resurrect_it():
    """Re-observing a deprecated pattern must keep it deprecated."""
    repo = PatternRepository()
    p = await repo.observe("use dependency injection", "p1", "a1")
    await repo.deprecate(p.id, reason="superseded")
    # same normalised text, observed again → must STAY deprecated
    again = await repo.observe("Use dependency injection.", "p2", "a2")
    assert again.id == p.id
    assert again.status == PatternStatus.DEPRECATED


@pytest.mark.asyncio
async def test_cross_project_dedup_counts_one_pattern_two_projects():
    """Cross-project dedup via normalisation counts distinct projects correctly."""
    repo = PatternRepository()
    await repo.observe("retry with backoff", "p1", "a1")
    await repo.observe("  Retry   with backoff  ", "p2", "a2")  # same after normalise
    cross = await repo.cross_project_patterns()
    assert len(cross) == 1
    assert cross[0].projects == {"p1", "p2"}
