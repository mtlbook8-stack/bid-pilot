"""Tests for domain model behavior + camelCase serialization contract."""

from datetime import UTC, datetime

from src.core.enums import BidStatus, TradeCategory
from src.core.models.bid import AgentResult, IngestedBid
from src.core.models.job import JobSummary
from src.core.models.prompt import PromptTemplate


def _make_bid(**overrides) -> IngestedBid:
    base = dict(
        id="b1", message_id="m1", linked_account_id="a1", sender_email="v@x.com",
        email_subject="Quote", received_at=datetime.now(UTC),
        attachment_filename="q.pdf", blob_path="a1/m1/q.pdf",
    )
    base.update(overrides)
    return IngestedBid(**base)


def test_deterministic_bid_id_is_stable() -> None:
    a = IngestedBid.make_id("msg-1", "file.pdf")
    b = IngestedBid.make_id("msg-1", "file.pdf")
    c = IngestedBid.make_id("msg-1", "other.pdf")
    assert a == b
    assert a != c


def test_partition_key_fields_serialize_camelcase() -> None:
    bid = _make_bid(matched_project_id="proj-9", matched_job_id="job-2")
    doc = bid.model_dump(mode="json", by_alias=True)
    # These camelCase keys must match the Cosmos container schema/queries.
    assert doc["matchedProjectId"] == "proj-9"
    assert doc["matchedJobId"] == "job-2"
    assert "matched_project_id" not in doc


def test_models_accept_both_casings() -> None:
    job_camel = JobSummary.model_validate(
        {"id": "j", "projectId": "p", "tradeCategory": "HVAC", "jobName": "x"}
    )
    job_snake = JobSummary.model_validate(
        {"id": "j", "project_id": "p", "trade_category": "HVAC", "job_name": "x"}
    )
    assert job_camel.project_id == job_snake.project_id == "p"


def test_needs_review_flags_low_confidence() -> None:
    bid = _make_bid()
    bid.record_agent_result(AgentResult(agent_name="QuoteValidator", confidence=0.95))
    assert bid.needs_review is False
    bid.record_agent_result(AgentResult(agent_name="JobCategorizer", confidence=0.4))
    assert bid.needs_review is True


def test_advance_to_updates_status_and_timestamp() -> None:
    bid = _make_bid()
    before = bid.updated_at
    bid.advance_to(BidStatus.VALIDATED)
    assert bid.status is BidStatus.VALIDATED
    assert bid.updated_at >= before


def test_job_add_bid_dedupes() -> None:
    job = JobSummary(id="j", project_id="p", trade_category=TradeCategory.HVAC, job_name="x")
    job.add_bid("b1")
    job.add_bid("b1")
    job.add_bid("b2")
    assert job.bid_ids == ["b1", "b2"]
    assert job.bid_count == 2


def test_prompt_seed_roundtrip_keeps_modelconfig_alias() -> None:
    doc = {
        "id": "QuoteValidator-v1", "agentName": "QuoteValidator", "version": 1,
        "isActive": True,
        "modelConfig": {"modelName": "claude-sonnet-4-6", "maxTokens": 500,
                        "temperature": 0.1, "fallbackModel": "claude-sonnet-4-5"},
        "systemPromptTemplate": "sys {learned_rules}", "userMessageTemplate": "user",
    }
    prompt = PromptTemplate.model_validate(doc)
    assert prompt.model_config_.model_name == "claude-sonnet-4-6"
    out = prompt.model_dump(mode="json", by_alias=True)
    assert "modelConfig" in out and out["agentName"] == "QuoteValidator"
