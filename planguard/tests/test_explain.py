"""The Claude call is tested with a fake client: no network, no API key, no cost."""

from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from planguard.context import build_context
from planguard.explain import FALLBACK_BETA, MODEL, explain
from planguard.rules import evaluate, overall_level

GOOD = {
    "summary": "Routes the shared VPC through a NAT gateway that has no way out.",
    "blast_radius": ["CI runners lose internet access"],
    "rollback": ["Point the default route back at the internet gateway"],
    "reviewer_checklist": ["Confirm where the NAT gateway should live"],
}


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.kwargs = response, error, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def fake_client(response=None, error=None):
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(response, error)))


def response(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=900, output_tokens=400),
    )


@pytest.fixture
def context(load_plan):
    plan = load_plan("05-nat-shared-vpc")
    findings = evaluate(plan)
    return build_context(plan, findings, overall_level(plan, findings))


def test_valid_explanation_is_parsed(context):
    client = fake_client(response(json.dumps(GOOD)))
    result = explain(context, "feat(network): add a NAT gateway", client=client)
    assert result.explanation is not None and result.note is None
    assert result.explanation.blast_radius == GOOD["blast_radius"]
    assert result.usage == {"input_tokens": 900, "output_tokens": 400}


def test_request_shape(context):
    client = fake_client(response(json.dumps(GOOD)))
    explain(context, "feat(network): add a NAT gateway", client=client)
    kwargs = client.beta.messages.kwargs
    assert kwargs["model"] == MODEL
    assert kwargs["fallbacks"] == "default" and kwargs["betas"] == [FALLBACK_BETA]
    assert kwargs["output_config"]["effort"] == "medium"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    prompt = kwargs["messages"][0]["content"]
    assert "<author_intent>feat(network): add a NAT gateway</author_intent>" in prompt
    assert "default-route-change" in prompt  # the rules' findings are part of the context


def test_account_ids_never_reach_the_api(context):
    context["changes"][0]["changed"]["leak"] = "arn:aws:iam::987654321098:role/x 555555555555"
    client = fake_client(response(json.dumps(GOOD)))
    explain(context, "", client=client, account_ids=("555555555555",))
    prompt = client.beta.messages.kwargs["messages"][0]["content"]
    assert "987654321098" not in prompt and "555555555555" not in prompt


def test_refusal_degrades_to_a_note(context):
    result = explain(context, "", client=fake_client(response("", stop_reason="refusal")))
    assert result.explanation is None and "declined" in result.note


def test_unexpected_format_degrades_to_a_note(context):
    result = explain(context, "", client=fake_client(response('{"summary": "missing fields"}')))
    assert result.explanation is None and "unexpected format" in result.note


def test_api_errors_degrade_to_a_note(context):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    errors = [
        anthropic.APIConnectionError(request=request),
        anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=request), body=None),
    ]
    for error in errors:
        result = explain(context, "", client=fake_client(error=error))
        assert result.explanation is None and result.note


def test_without_credentials_it_never_calls_the_api(context, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_FEDERATION_RULE_ID", raising=False)
    result = explain(context, "")
    assert result.explanation is None and "offline" in result.note
