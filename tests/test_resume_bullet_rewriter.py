"""Tests for safe, isolated resume bullet rewriting."""

from types import SimpleNamespace

import httpx
from openai import APITimeoutError

from ai_internship_assistant.domain.models import (
    BulletRewriteRequest,
    BulletRewriteResult,
    BulletRewriteSource,
    ViolationType,
)
from ai_internship_assistant.services import (
    OpenAIResumeBulletRewriter,
    RuleBasedResumeBulletRewriter,
)


class FakeResponsesClient:
    """Fake structured-output client returning one prebuilt rewrite."""

    def __init__(
        self,
        result: BulletRewriteResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(output_parsed=self.result)


class FakeOpenAIClient:
    """Small OpenAI client test double."""

    def __init__(
        self,
        result: BulletRewriteResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.responses = FakeResponsesClient(result, error)


def _request(
    *,
    original: str = "Built a packet sniffer in Python using raw sockets.",
    evidence: list[str] | None = None,
    safe: list[str] | None = None,
    unsafe: list[str] | None = None,
    forbidden: list[str] | None = None,
    related: list[str] | None = None,
    max_length: int = 240,
) -> BulletRewriteRequest:
    return BulletRewriteRequest(
        original_bullet=original,
        section_name="Projects",
        parent_item_name="Packet Sniffer Project",
        candidate_evidence=evidence
        or ["Packet Sniffer Project used Python raw sockets to capture network packets."],
        target_job_title="SOC Analyst Intern",
        target_company="Example Security",
        safe_keywords=safe or ["Python", "networking", "packet analysis", "network traffic"],
        unsafe_keywords=unsafe or ["Splunk", "SIEM", "incident response"],
        forbidden_claims=forbidden
        or ["Used Splunk", "Monitored SIEM alerts", "Performed incident response"],
        related_keywords=related or ["packet analysis", "network traffic"],
        max_length=max_length,
        optimization_goal="Improve relevance while preserving truth.",
    )


def _provider_result(rewritten: str, explanation: str = "Improved wording.") -> BulletRewriteResult:
    return BulletRewriteResult(
        original_bullet="provider supplied original",
        rewritten_bullet=rewritten,
        changed=True,
        included_keywords=["provider supplied"],
        avoided_keywords=[],
        safety_violations=[],
        confidence_score=1.0,
        explanation=explanation,
        rewrite_source=BulletRewriteSource.OPENAI,
    )


def _rewrite(rewritten: str, request: BulletRewriteRequest | None = None) -> BulletRewriteResult:
    return OpenAIResumeBulletRewriter(
        client=FakeOpenAIClient(_provider_result(rewritten))
    ).rewrite(request or _request())


def _violation_types(result: BulletRewriteResult) -> set[ViolationType]:
    return {violation.violation_type for violation in result.safety_violations}


def test_safe_python_packet_sniffer_rewrite() -> None:
    rewritten = (
        "Developed a Python packet sniffer using raw sockets to capture and analyze "
        "network traffic, reinforcing networking and packet analysis fundamentals."
    )

    result = _rewrite(rewritten)

    assert result.rewritten_bullet == rewritten
    assert result.rewrite_source == BulletRewriteSource.OPENAI
    assert result.changed is True
    assert result.safety_violations == []


def test_unsafe_splunk_keyword_is_rejected() -> None:
    result = _rewrite("Developed a Python packet sniffer and used Splunk to analyze packets.")

    assert result.rewritten_bullet == _request().original_bullet
    assert result.rewrite_source == BulletRewriteSource.FALLBACK_ORIGINAL
    assert ViolationType.UNSAFE_KEYWORD in _violation_types(result)


def test_forbidden_siem_claim_is_rejected() -> None:
    result = _rewrite("Monitored SIEM alerts while using Python raw sockets.")

    assert ViolationType.FORBIDDEN_CLAIM in _violation_types(result)
    assert result.changed is False


def test_invented_metric_is_rejected() -> None:
    result = _rewrite("Developed a Python packet sniffer that improved accuracy by 40%.")

    assert ViolationType.INVENTED_METRIC in _violation_types(result)


def test_invented_technology_is_rejected() -> None:
    request = _request(unsafe=[], forbidden=[])
    result = _rewrite(
        "Developed a Python and Spring Boot packet sniffer using raw sockets.",
        request,
    )

    assert ViolationType.INVENTED_TECHNOLOGY in _violation_types(result)


def test_meaning_changing_rewrite_is_rejected() -> None:
    request = _request(unsafe=[], forbidden=[])
    result = _rewrite("Managed customer relationships and coordinated weekly schedules.", request)

    assert ViolationType.MEANING_CHANGED in _violation_types(result)


def test_invented_experience_scope_is_rejected() -> None:
    request = _request(unsafe=[], forbidden=[])
    result = _rewrite(
        "Developed a Python packet sniffer for production systems using raw sockets.",
        request,
    )

    assert ViolationType.INVENTED_EXPERIENCE in _violation_types(result)


def test_empty_llm_response_falls_back() -> None:
    result = OpenAIResumeBulletRewriter(client=FakeOpenAIClient(None)).rewrite(_request())

    assert result.rewrite_source in {
        BulletRewriteSource.RULE_BASED,
        BulletRewriteSource.FALLBACK_ORIGINAL,
    }
    assert any("structured BulletRewriteResult" in warning for warning in result.warnings)


def test_llm_timeout_falls_back() -> None:
    timeout = APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    result = OpenAIResumeBulletRewriter(client=FakeOpenAIClient(error=timeout)).rewrite(_request())

    assert result.rewrite_source in {
        BulletRewriteSource.RULE_BASED,
        BulletRewriteSource.FALLBACK_ORIGINAL,
    }
    assert any("LLM bullet rewrite failed" in warning for warning in result.warnings)


def test_original_preserved_when_no_safe_improvement_exists() -> None:
    request = _request(original="Built project.", evidence=[], safe=[], unsafe=[], forbidden=[])

    result = RuleBasedResumeBulletRewriter().rewrite(request)

    assert result.rewritten_bullet == "Built project."
    assert result.changed is False
    assert result.rewrite_source == BulletRewriteSource.FALLBACK_ORIGINAL


def test_safe_keywords_are_included_naturally() -> None:
    result = _rewrite(
        "Developed a Python packet sniffer using raw sockets to analyze network traffic."
    )

    assert {"Python", "network traffic"} <= set(result.included_keywords)


def test_unsafe_keywords_are_excluded() -> None:
    result = _rewrite("Developed a Python packet sniffer using raw sockets.")

    assert {"Splunk", "SIEM", "incident response"} <= set(result.avoided_keywords)


def test_related_keyword_is_used_carefully_with_evidence() -> None:
    request = _request(
        evidence=["Captured and analyzed network traffic using Python raw sockets."],
    )
    result = _rewrite(
        "Developed a Python packet sniffer using raw sockets for packet analysis "
        "of network traffic.",
        request,
    )

    assert result.rewrite_source == BulletRewriteSource.OPENAI
    assert "packet analysis" in result.included_keywords


def test_bullet_length_is_enforced() -> None:
    request = _request(max_length=80)
    result = _rewrite(
        "Developed a Python packet sniffer using raw sockets to capture and analyze "
        "network traffic while documenting extensive networking fundamentals.",
        request,
    )

    assert ViolationType.TOO_LONG in _violation_types(result)


def test_confidence_is_high_for_safe_rewrite() -> None:
    result = _rewrite(
        "Developed a Python packet sniffer using raw sockets to analyze network traffic."
    )

    assert result.confidence_score >= 0.8


def test_confidence_is_low_for_unsafe_fallback() -> None:
    result = _rewrite("Used Splunk to monitor SIEM alerts.")

    assert result.confidence_score <= 0.1


def test_nontechnical_work_bullet_rewritten_safely() -> None:
    request = _request(
        original="Helped customers resolve order issues.",
        evidence=["Assisted customers and resolved order issues."],
        safe=["communication", "customer service"],
        unsafe=["SIEM", "Splunk"],
        forbidden=["Monitored SIEM alerts"],
        related=["communication"],
    )
    result = _rewrite(
        "Resolved customer order issues through clear communication and customer service.",
        request,
    )

    assert result.rewrite_source == BulletRewriteSource.OPENAI
    assert result.safety_violations == []


def test_customer_service_bullet_not_converted_to_cybersecurity() -> None:
    request = _request(
        original="Helped customers resolve order issues.",
        evidence=["Assisted customers and resolved order issues."],
        safe=["communication"],
        unsafe=["SIEM", "incident response"],
        forbidden=["Performed incident response"],
    )
    result = _rewrite("Performed incident response for customer security issues.", request)

    assert result.rewrite_source == BulletRewriteSource.FALLBACK_ORIGINAL
    assert ViolationType.FORBIDDEN_CLAIM in _violation_types(result)


def test_existing_metric_is_preserved() -> None:
    request = _request(
        original="Resolved issues for 50 customers.",
        evidence=["Resolved issues for 50 customers."],
        safe=["customer service"],
        unsafe=[],
        forbidden=[],
    )
    result = _rewrite("Resolved service issues for 50 customers.", request)

    assert result.rewrite_source == BulletRewriteSource.OPENAI
    assert ViolationType.INVENTED_METRIC not in _violation_types(result)


def test_no_metric_is_added_when_none_exists() -> None:
    request = _request(unsafe=[], forbidden=[])
    result = _rewrite("Developed a Python packet sniffer that processed 100 systems.", request)

    assert ViolationType.INVENTED_METRIC in _violation_types(result)


def test_structured_output_arguments_and_local_fields_are_enforced() -> None:
    request = _request()
    client = FakeOpenAIClient(
        _provider_result("Developed a Python packet sniffer using raw sockets.")
    )

    result = OpenAIResumeBulletRewriter(client=client).rewrite(request)

    call = client.responses.calls[0]
    assert call["text_format"] is BulletRewriteResult
    assert call["temperature"] == 0.0
    assert result.original_bullet == request.original_bullet
    assert result.included_keywords == ["Python"]
