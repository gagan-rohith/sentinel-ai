from types import SimpleNamespace
from typing import Any

import anthropic
import pytest

from agents.llm import AnthropicLLM, run_step
from agents.schemas import SearchPlan
from core.exceptions import LLMUnavailableError
from tests.agent.conftest import ScriptedLLM

HEURISTIC = SearchPlan(queries=["from heuristic"])
MODEL_OUTPUT = SearchPlan(queries=["from model"])


async def test_no_llm_uses_heuristic() -> None:
    result, call = await run_step(
        "retrieval", None, SearchPlan, "sys", lambda: "prompt", lambda: HEURISTIC
    )
    assert result is HEURISTIC
    assert call.mode == "heuristic"
    assert call.model is None
    assert call.input_tokens == 0


async def test_llm_output_and_usage_recorded() -> None:
    llm = ScriptedLLM(SearchPlan=[MODEL_OUTPUT])
    result, call = await run_step(
        "retrieval", llm, SearchPlan, "sys", lambda: "prompt", lambda: HEURISTIC
    )
    assert result is MODEL_OUTPUT
    assert (call.mode, call.model, call.input_tokens, call.output_tokens) == (
        "llm",
        "scripted-test-model",
        100,
        20,
    )


async def test_llm_failure_falls_back_and_is_labelled() -> None:
    result, call = await run_step(
        "retrieval", ScriptedLLM(), SearchPlan, "sys", lambda: "prompt", lambda: HEURISTIC
    )
    assert result is HEURISTIC
    assert call.mode == "fallback"
    assert call.error == "SearchPlan not scripted"


class _FakeMessages:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    async def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.response


def _llm_returning(response: Any, effort: Any = None) -> AnthropicLLM:
    llm = AnthropicLLM("claude-sonnet-5-5", api_key="test", effort=effort)
    llm._client = SimpleNamespace(messages=_FakeMessages(response))  # type: ignore[assignment]
    return llm


_OK = SimpleNamespace(
    stop_reason="end_turn",
    parsed_output=MODEL_OUTPUT,
    usage=SimpleNamespace(input_tokens=1, output_tokens=1),
)


async def test_effort_is_sent_when_configured() -> None:
    llm = _llm_returning(_OK, effort="low")
    await llm.generate(SearchPlan, "sys", "prompt")
    sent = llm._client.messages.kwargs  # type: ignore[attr-defined]
    assert sent["output_config"] == {"effort": "low"}
    assert sent["output_format"] is SearchPlan


async def test_effort_is_omitted_by_default() -> None:
    llm = _llm_returning(_OK)
    await llm.generate(SearchPlan, "sys", "prompt")
    assert llm._client.messages.kwargs["output_config"] is anthropic.omit  # type: ignore[attr-defined]


async def test_anthropic_llm_returns_parsed_output_and_usage() -> None:
    response = SimpleNamespace(
        stop_reason="end_turn",
        parsed_output=MODEL_OUTPUT,
        usage=SimpleNamespace(input_tokens=321, output_tokens=45),
    )
    result, usage = await _llm_returning(response).generate(SearchPlan, "sys", "prompt")
    assert result == MODEL_OUTPUT
    assert (usage.input_tokens, usage.output_tokens) == (321, 45)


@pytest.mark.parametrize(
    ("stop_reason", "parsed", "message"),
    [("refusal", None, "declined"), ("max_tokens", None, "no SearchPlan")],
)
async def test_anthropic_llm_rejects_unusable_responses(
    stop_reason: str, parsed: Any, message: str
) -> None:
    response = SimpleNamespace(
        stop_reason=stop_reason,
        parsed_output=parsed,
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    with pytest.raises(LLMUnavailableError, match=message):
        await _llm_returning(response).generate(SearchPlan, "sys", "prompt")
