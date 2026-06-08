"""Tests for OpenAI and hybrid structured job-description analysis."""

from types import SimpleNamespace

from ai_internship_assistant.domain.models import (
    AnalysisSource,
    EmploymentType,
    JobAnalysis,
    JobPosting,
    JobSeniority,
    JobSourceType,
    RequirementLevel,
    RoleCategory,
    SkillRequirement,
)
from ai_internship_assistant.services import (
    HybridJobDescriptionAnalyzer,
    JobDescriptionAnalysisError,
    OpenAIJobDescriptionAnalyzer,
    RuleBasedJobDescriptionAnalyzer,
)


class FakeResponsesClient:
    """Fake structured-output client that records provider calls."""

    def __init__(self, analysis: JobAnalysis | None) -> None:
        self.analysis = analysis
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.analysis)


class FakeOpenAIClient:
    """Small test double matching the OpenAI surface used by the analyzer."""

    def __init__(self, analysis: JobAnalysis | None) -> None:
        self.responses = FakeResponsesClient(analysis)


class FailingAnalyzer:
    """Analyzer test double representing timeout or provider failure."""

    def __init__(self, message: str = "request timed out") -> None:
        self.message = message

    def analyze(self, job: JobPosting) -> JobAnalysis:
        raise JobDescriptionAnalysisError(self.message)


def _job(
    *,
    title: str = "SOC Analyst Intern",
    description: str | None = (
        "Support SOC operations, analyze security logs, assist with incident response, "
        "and use SIEM tools such as Splunk. Candidates should have Python and Linux. "
        "Security+ preferred. Currently pursuing a degree in Cybersecurity."
    ),
) -> JobPosting:
    return JobPosting(
        id="job-1",
        source=JobSourceType.MOCK,
        source_name="Mock Source",
        apply_url="https://jobs.example.com/apply/1",
        title=title,
        company="Example Security Company",
        location="Raleigh, NC",
        employment_type=EmploymentType.INTERNSHIP,
        description=description,
    )


def _skill(
    name: str,
    level: RequirementLevel,
    evidence: str | None = None,
) -> SkillRequirement:
    return SkillRequirement(
        name=name,
        category="technical_skill",
        requirement_level=level,
        evidence=evidence or name,
        confidence=0.92,
    )


def _llm_analysis(job: JobPosting, **updates: object) -> JobAnalysis:
    baseline = RuleBasedJobDescriptionAnalyzer().analyze(job)
    defaults: dict[str, object] = {
        "role_category": RoleCategory.CYBERSECURITY,
        "domain_category": RoleCategory.CYBERSECURITY,
        "seniority": JobSeniority.INTERNSHIP,
        "confidence_score": 0.9,
    }
    defaults.update(updates)
    return baseline.model_copy(update=defaults)


def test_successful_llm_analysis_uses_structured_output_and_sanitizes_identity() -> None:
    job = _job()
    supplied = _llm_analysis(job).model_copy(
        update={"job_id": "invented-id", "company": "Invented Company", "raw_text_hash": "bad"}
    )
    client = FakeOpenAIClient(supplied)

    analysis = OpenAIJobDescriptionAnalyzer(client=client).analyze(job)

    assert analysis.job_id == job.id
    assert analysis.company == job.company
    assert analysis.raw_text_hash != "bad"
    assert analysis.analysis_source == AnalysisSource.LLM
    assert client.responses.calls[0]["text_format"] is JobAnalysis
    assert client.responses.calls[0]["temperature"] == 0.0


def test_llm_extracts_required_and_preferred_skills_with_evidence() -> None:
    job = _job()
    supplied = _llm_analysis(
        job,
        required_skills=[_skill("Python", RequirementLevel.REQUIRED, "should have Python")],
        preferred_skills=[
            _skill("Security+", RequirementLevel.PREFERRED, "Security+ preferred")
        ],
    )

    analysis = OpenAIJobDescriptionAnalyzer(client=FakeOpenAIClient(supplied)).analyze(job)

    assert analysis.required_skills[0].name == "Python"
    assert analysis.preferred_skills[0].name == "Security+"
    assert analysis.preferred_skills[0].evidence == "Security+ preferred"


def test_llm_detects_cybersecurity_internship() -> None:
    job = _job()
    supplied = _llm_analysis(
        job,
        role_category=RoleCategory.CYBERSECURITY,
        domain_category=RoleCategory.CYBERSECURITY,
        seniority=JobSeniority.INTERNSHIP,
        internship_indicators=["Intern", "Cybersecurity Intern"],
    )

    analysis = OpenAIJobDescriptionAnalyzer(client=FakeOpenAIClient(supplied)).analyze(job)

    assert analysis.role_category == RoleCategory.CYBERSECURITY
    assert analysis.seniority == JobSeniority.INTERNSHIP


def test_llm_detects_senior_role_and_clearance() -> None:
    job = _job(
        title="Senior Security Architect",
        description="Requires 8+ years of experience and active security clearance.",
    )
    supplied = _llm_analysis(
        job,
        seniority=JobSeniority.SENIOR,
        seniority_indicators=["Senior", "Architect", "8+ years"],
        disqualifying_requirements=[
            "8+ years of experience required",
            "active security clearance required",
        ],
    )

    analysis = OpenAIJobDescriptionAnalyzer(client=FakeOpenAIClient(supplied)).analyze(job)

    assert analysis.seniority == JobSeniority.SENIOR
    assert "active security clearance required" in analysis.disqualifying_requirements


def test_llm_detects_education_and_experience_requirements() -> None:
    job = _job(description="Requires 2 years experience and a bachelor's degree.")
    supplied = _llm_analysis(
        job,
        experience_requirements=["2 years experience"],
        education_requirements=["bachelor's degree"],
    )

    analysis = OpenAIJobDescriptionAnalyzer(client=FakeOpenAIClient(supplied)).analyze(job)

    assert analysis.experience_requirements == ["2 years experience"]
    assert analysis.education_requirements == ["bachelor's degree"]


def test_malformed_llm_response_falls_back_to_rule_analysis() -> None:
    job = _job()
    hybrid = HybridJobDescriptionAnalyzer(
        llm_analyzer=OpenAIJobDescriptionAnalyzer(client=FakeOpenAIClient(None))
    )

    analysis = hybrid.analyze(job)

    assert analysis.analysis_source == AnalysisSource.RULE_BASED
    assert any("rule-based fallback" in warning for warning in analysis.warnings)


def test_missing_api_key_falls_back(monkeypatch: object) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    analysis = HybridJobDescriptionAnalyzer(
        llm_analyzer=OpenAIJobDescriptionAnalyzer()
    ).analyze(_job())

    assert analysis.analysis_source == AnalysisSource.RULE_BASED
    assert any("OPENAI_API_KEY" in warning for warning in analysis.warnings)


def test_llm_timeout_falls_back() -> None:
    analysis = HybridJobDescriptionAnalyzer(llm_analyzer=FailingAnalyzer()).analyze(_job())

    assert analysis.analysis_source == AnalysisSource.RULE_BASED
    assert any("timed out" in warning for warning in analysis.warnings)


def test_hybrid_merges_rule_and_llm_keywords() -> None:
    job = _job()
    supplied = _llm_analysis(job, ats_keywords=["SOC Analyst Intern", "security operations"])

    analysis = HybridJobDescriptionAnalyzer(
        llm_analyzer=OpenAIJobDescriptionAnalyzer(client=FakeOpenAIClient(supplied))
    ).analyze(job)

    assert analysis.analysis_source == AnalysisSource.HYBRID
    assert "security operations" in analysis.ats_keywords
    assert "Splunk" in analysis.ats_keywords


def test_hybrid_removes_duplicate_skills_and_prefers_llm_section_interpretation() -> None:
    job = _job(description="Python preferred. Python supports the team.")
    supplied = _llm_analysis(
        job,
        required_skills=[],
        preferred_skills=[
            _skill("Python", RequirementLevel.PREFERRED),
            _skill("python", RequirementLevel.PREFERRED),
        ],
    )

    analysis = HybridJobDescriptionAnalyzer(
        llm_analyzer=OpenAIJobDescriptionAnalyzer(client=FakeOpenAIClient(supplied))
    ).analyze(job)

    names = [skill.name.casefold() for skill in analysis.preferred_skills]
    assert names.count("python") == 1
    assert not any(skill.name.casefold() == "python" for skill in analysis.required_skills)


def test_long_evidence_snippet_is_bounded() -> None:
    job = _job()
    supplied = _llm_analysis(
        job,
        required_skills=[_skill("Python", RequirementLevel.REQUIRED, "x" * 500)],
    )

    analysis = OpenAIJobDescriptionAnalyzer(client=FakeOpenAIClient(supplied)).analyze(job)

    assert len(analysis.required_skills[0].evidence) == 300


def test_unsupported_llm_skill_is_discarded() -> None:
    job = _job(description="Use Python to support the team.")
    supplied = _llm_analysis(
        job,
        required_skills=[
            _skill("Python", RequirementLevel.REQUIRED),
            _skill("Kubernetes", RequirementLevel.REQUIRED, "Kubernetes required"),
        ],
    )

    analysis = OpenAIJobDescriptionAnalyzer(client=FakeOpenAIClient(supplied)).analyze(job)

    assert [skill.name for skill in analysis.required_skills] == ["Python"]
    assert "unsupported LLM skill requirements were discarded" in analysis.warnings


def test_punctuation_heavy_skills_remain_distinct() -> None:
    job = _job(description="Experience with C, C#, and C++ is required.")
    supplied = _llm_analysis(
        job,
        required_skills=[
            _skill("C", RequirementLevel.REQUIRED),
            _skill("C#", RequirementLevel.REQUIRED),
            _skill("C++", RequirementLevel.REQUIRED),
        ],
    )

    analysis = HybridJobDescriptionAnalyzer(
        llm_analyzer=OpenAIJobDescriptionAnalyzer(client=FakeOpenAIClient(supplied))
    ).analyze(job)

    assert {skill.name for skill in analysis.required_skills} == {"C", "C#", "C++"}


def test_empty_description_hybrid_falls_back_gracefully() -> None:
    analysis = HybridJobDescriptionAnalyzer(
        llm_analyzer=OpenAIJobDescriptionAnalyzer(client=FakeOpenAIClient(None))
    ).analyze(_job(title="Student Intern", description=None))

    assert analysis.analysis_source == AnalysisSource.RULE_BASED
    assert "empty description" in analysis.warnings
    assert any("rule-based fallback" in warning for warning in analysis.warnings)


def test_prompt_contains_job_fields_and_no_candidate_data() -> None:
    job = _job()
    client = FakeOpenAIClient(_llm_analysis(job))

    OpenAIJobDescriptionAnalyzer(client=client).analyze(job)

    prompt = str(client.responses.calls[0]["input"])
    assert job.title in prompt
    assert job.company in prompt
    assert str(job.apply_url) in prompt
    assert "candidate_name" not in prompt
    assert "resume" not in prompt.casefold()


def test_truncated_prompt_adds_warning() -> None:
    job = _job(description="Python " * 1_000)
    supplied = _llm_analysis(job)

    analysis = OpenAIJobDescriptionAnalyzer(
        client=FakeOpenAIClient(supplied),
        max_input_length=1_000,
    ).analyze(job)

    assert "LLM analysis input was truncated" in analysis.warnings


def test_hybrid_confidence_reflects_disagreement() -> None:
    job = _job()
    supplied = _llm_analysis(
        job,
        role_category=RoleCategory.DATA,
        domain_category=RoleCategory.DATA,
        seniority=JobSeniority.SENIOR,
        confidence_score=1.0,
    )

    analysis = HybridJobDescriptionAnalyzer(
        llm_analyzer=OpenAIJobDescriptionAnalyzer(client=FakeOpenAIClient(supplied))
    ).analyze(job)

    assert analysis.confidence_score < 0.8


def test_rule_analyzer_sets_analysis_source_and_seniority() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(_job())

    assert analysis.analysis_source == AnalysisSource.RULE_BASED
    assert analysis.seniority == JobSeniority.INTERNSHIP
