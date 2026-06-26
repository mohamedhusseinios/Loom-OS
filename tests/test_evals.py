"""Tests for the EvalEngine."""
import pytest
from daemon.evals import EvalEngine, Score


@pytest.fixture
def engine():
    return EvalEngine()


@pytest.mark.asyncio
async def test_evaluate_no_hardcoded_secrets_pass(engine):
    """Clean code passes the no_hardcoded_secrets check."""
    case = await engine.evaluate(
        project="proj",
        agent_id="a1",
        criterion="no_hardcoded_secrets",
        expected="No hardcoded secrets",
        actual="const config = loadEnvVars();",
    )
    assert case.score == Score.PASS


@pytest.mark.asyncio
async def test_evaluate_no_hardcoded_secrets_warn(engine):
    """Code with hardcoded secrets gets a warning."""
    case = await engine.evaluate(
        project="proj",
        agent_id="a1",
        criterion="no_hardcoded_secrets",
        expected="No hardcoded secrets",
        actual='password = "admin123"',
    )
    assert case.score == Score.WARN
    assert "password" in case.details


@pytest.mark.asyncio
async def test_evaluate_no_todos_pass(engine):
    """Clean code without TODOs passes."""
    case = await engine.evaluate(
        project="proj",
        agent_id="a1",
        criterion="no_todos",
        expected="No TODOs",
        actual="def foo(): return 42",
    )
    assert case.score == Score.PASS


@pytest.mark.asyncio
async def test_evaluate_no_todos_warn(engine):
    """Code with TODO markers gets a warning."""
    case = await engine.evaluate(
        project="proj",
        agent_id="a1",
        criterion="no_todos",
        expected="No TODOs",
        actual="# TODO: refactor this later",
    )
    assert case.score == Score.WARN


@pytest.mark.asyncio
async def test_evaluate_structured_output_pass(engine):
    """Output with FOUND/PATTERN/DECISION passes structured check."""
    case = await engine.evaluate(
        project="proj",
        agent_id="a1",
        criterion="structured_output",
        expected="Structured findings",
        actual="FOUND: a bug\nPATTERN: a pattern",
    )
    assert case.score == Score.PASS


@pytest.mark.asyncio
async def test_evaluate_unknown_criterion_returns_pass(engine):
    """Unknown criterion returns PASS with low confidence."""
    case = await engine.evaluate(
        project="proj",
        agent_id="a1",
        criterion="some_future_check",
        expected="anything",
        actual="anything",
    )
    assert case.score == Score.PASS
    assert case.confidence < 0.5


@pytest.mark.asyncio
async def test_get_results_filtered_by_project(engine):
    """Eval results can be filtered by project."""
    await engine.evaluate("proj-a", "a1", "no_todos", "x", "clean")
    await engine.evaluate("proj-b", "a1", "no_todos", "x", "clean")

    results = await engine.get_results(project="proj-a")
    assert len(results) == 1
    assert results[0].project == "proj-a"


@pytest.mark.asyncio
async def test_get_pass_rate(engine):
    """Pass rate is computed correctly."""
    # Fail
    await engine.evaluate("proj", "a1", "no_hardcoded_secrets", "x", 'password = "x"')
    # Warn
    await engine.evaluate("proj", "a1", "no_hardcoded_secrets", "x", 'password = "x"')
    # Pass
    await engine.evaluate("proj", "a1", "no_todos", "x", "clean")

    rate = await engine.get_pass_rate(project="proj")
    assert rate["total"] == 3
    assert rate["pass"] == 1
    assert rate["warn"] == 2
    assert rate["fail"] == 0
    assert rate["pass_rate"] == round(1 / 3, 3)
