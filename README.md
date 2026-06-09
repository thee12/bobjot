# AI Internship Application Assistant

AI Internship Application Assistant is an AI-assisted resume tailoring and job discovery platform for internships and entry-level roles.

The Phase 1 scaffold defines the project architecture only. It does not implement scraping, LLM prompts, API endpoints, resume optimization, or generation logic.

## Goals

- Accept a user's master resume in PDF or DOCX format.
- Parse resumes into structured data.
- Match user qualifications and preferences to internships and entry-level jobs.
- Analyze job descriptions for ATS keywords, skills, technologies, certifications, and action verbs.
- Generate tailored resume versions without inventing experience, credentials, projects, tools, dates, metrics, or achievements.
- Score ATS compatibility.
- Store application history and generated resume versions.

## Non-Negotiable AI Rules

The optimizer must never fabricate:

- jobs
- certifications
- projects
- technologies
- employers
- dates
- years of experience
- metrics or achievements

It may only reorder, rewrite, emphasize, align keywords, and improve readability using facts already present in the source resume.

## Project Layout

```text
src/ai_internship_assistant/
  config/              Runtime settings and environment configuration.
  domain/models/       Core Pydantic models shared across the system.
  services/            Future service-layer modules for parsing, analysis, scoring, and generation.
  storage/             Future database and repository abstractions.
tests/                 Test suite skeleton.
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## Quality Checks

```bash
pytest
ruff check .
mypy src
```

## Current Status

The current extraction pipeline supports:

```text
Resume PDF/DOCX
  -> extract_text()
  -> raw text
  -> OpenAIResumeParser.parse()
  -> Resume(...)
  -> ResumeValidator.validate()
  -> ValidationReport(...)
  -> CandidateProfileGenerator.generate()
  -> CandidateProfile(...)
  -> JobSearchQueryGenerator.generate()
  -> JobSearchQuerySet(...)
  -> JobSearchService.search_all()
  -> JobSearchResultSet(...)
  -> standardized JobPosting objects
  -> RuleBasedJobDescriptionAnalyzer.analyze()
  -> JobAnalysis(...)
  -> optional OpenAIJobDescriptionAnalyzer / HybridJobDescriptionAnalyzer
  -> SkillGapAnalyzer.analyze(CandidateProfile, JobAnalysis)
  -> SkillGapReport(...)
  -> ATSMatchScoringService.score(Resume, CandidateProfile, JobAnalysis, SkillGapReport)
  -> ATSMatchReport(...)
```

The parser performs extraction only. It does not optimize, rewrite, score, or
tailor resumes.

The candidate profile is the normalized downstream contract for future job
discovery, ranking, ATS scoring, skill-gap analysis, and optimization modules.
The current generator is deterministic and rules-based. It may classify
existing evidence into domains and likely target roles, but it never invents
skills, credentials, projects, technologies, education, or work history.

The job search query generator creates prioritized, role-oriented searches from
the candidate profile and optional location, remote, employment-type, and role
preferences. It performs no web searches. Future job-source integrations will
consume the structured `JobSearchQuery` objects.

The job source layer defines a provider-neutral `JobSource` interface. Future
Greenhouse, Lever, and company career-page integrations will normalize their
provider responses into the same `JobPosting` model. The included
`MockJobSource` is development-only and performs no network calls.

### Greenhouse Source

`GreenhouseJobSource` is the first real provider adapter. It uses only the
public, unauthenticated Greenhouse Job Board GET endpoint and never submits
applications or accesses private recruiting data.

Add boards by constructing `GreenhouseCompanyConfig` entries with:

- `company_name`: display name stored on normalized postings
- `board_token`: public token from `boards.greenhouse.io/{board_token}`
- `base_url`: optional public board URL
- `enabled`: whether the board should be searched
- `tags`: editable metadata for future filtering

The checked-in seed configuration is a disabled placeholder. Requests use a
clear user agent, timeout, optional delay between company boards, and no
automatic rate-limit bypass. Unit tests use mocked HTTP responses only.

### Lever Source

`LeverJobSource` uses only Lever's public published-postings GET endpoint:
`https://api.lever.co/v0/postings/{company_slug}?mode=json`. It never accesses
private postings, submits applications, or uses authentication credentials.

Add sites by constructing `LeverCompanyConfig` entries with:

- `company_name`: display name stored on normalized postings
- `company_slug`: public site name from `jobs.lever.co/{company_slug}`
- `base_url`: optional public Lever job-site URL
- `enabled`: whether the site should be searched
- `tags`: editable metadata for future filtering

Lever exposes a JSON list directly, while Greenhouse wraps jobs in a board
response object. Both adapters use shared deterministic matching and normalize
their provider-specific fields into `JobPosting`. Lever list sections are
classified into responsibilities, requirements, and preferred qualifications
when headings make that classification clear. Unit tests use mocked HTTP
responses only.

### Job Normalization And Deduplication

`JobNormalizationService` creates non-mutating normalized views of provider
postings. It standardizes common title variants, a small expandable company
alias set, locations, remote labels, tracking parameters, and description
formatting. Stable fingerprints use normalized company, title, and location.

`JobDeduplicationService` merges only high-confidence duplicates:

- identical normalized apply URL: `1.0`
- identical normalized source URL: `0.95`
- same normalized company, highly similar title, and same location: `0.85`

Possible duplicates below the automatic merge threshold remain separate and
produce warnings. Canonical selection prefers the posting with the most
complete description, followed by apply URL availability, direct ATS source,
posted date, and structured fields. Duplicate groups retain every original job
for traceability.

`JobSearchService(..., normalize=True, deduplicate=True)` enables the clean-job
pipeline. Both options default to `False` to preserve existing raw-result
behavior.

### Job Fit Ranking

`JobFitScoringService` deterministically scores clean jobs against a
`CandidateProfile`. It produces separate component scores, matched and missing
skills, matched certifications and keywords, disqualifying flags, warnings,
and a human-readable explanation.

Default component weights are centralized in `JobFitScoringConfig`:

- role match: 25%
- skill match: 25%
- domain match: 15%
- experience level: 15%
- employment type: 10%
- certification match: 5%
- location match: 3%
- keyword match: 2%

Recommendation levels are `STRONG_MATCH` (90+), `GOOD_MATCH` (75+),
`POSSIBLE_MATCH` (60+), `WEAK_MATCH` (40+), and `NOT_RECOMMENDED` (below 40).
Flags such as senior-level role, clearance, advanced degree, years-of-
experience, unrelated domain, and location mismatch reduce scores but do not
automatically remove jobs.

Scoring is rule-based and explainable. It currently relies on finite,
configurable keyword maps and deterministic token matching. Future embedding or
LLM components can augment individual score components without replacing the
ranking result contract.

### Job Description Analysis

`RuleBasedJobDescriptionAnalyzer` converts a standardized `JobPosting` into a
provider-independent `JobAnalysis`. It cleans HTML and repeated lines, preserves
source wording for responsibilities and qualifications, and extracts explicit
skills, tools, languages, frameworks, cloud platforms, cybersecurity terms,
certifications, soft skills, education, experience, internship signals,
seniority signals, and possible disqualifying requirements.

Phase 4A is intentionally deterministic and makes no LLM or external API calls.
Each required or preferred skill includes its source evidence and confidence.
Unclear evidence remains `UNKNOWN`; the analyzer prefers a missing field over an
invented or over-inferred requirement. Results include a text hash, confidence
score, and warnings for sparse, senior-level, unclear, or unusually long
postings.

The structured output is the future input contract for ATS resume/job matching,
skill-gap analysis, and factual resume optimization. Rule dictionaries and
section heuristics are finite and cannot understand every job-posting format.
Future `OpenAIJobDescriptionAnalyzer` and hybrid implementations can implement
the same `JobDescriptionAnalyzer` protocol without changing downstream modules.

### LLM And Hybrid Job Analysis

`OpenAIJobDescriptionAnalyzer` uses OpenAI structured outputs to return the same
validated `JobAnalysis` contract as the deterministic analyzer. It can interpret
messy sections and vague wording, but its prompt strictly requires extraction
from the supplied posting only. Locally controlled job identity, normalized
title, text hash, provenance, and bounded evidence snippets are enforced after
the provider response is validated.

`HybridJobDescriptionAnalyzer` runs rule-based analysis first, then merges a
validated LLM result conservatively:

- LLM section interpretation is preferred for required versus preferred skills.
- Exact rule-based keywords are retained when the LLM misses them.
- ATS keywords and evidence-backed fields are deduplicated.
- Confidence is reduced when role, domain, or seniority classifications disagree.
- Missing keys, timeouts, provider failures, malformed responses, and empty
  descriptions return the rule-based result with a warning.

Structured outputs are required because downstream ATS scoring, skill-gap
analysis, and resume optimization need a stable typed contract. Only job
posting data is sent to this analyzer; it does not receive resumes or personal
candidate information.

Configuration is environment-driven:

```text
OPENAI_API_KEY=
AI_INTERNSHIP_ASSISTANT_JOB_ANALYSIS_MODEL=gpt-4.1-mini
AI_INTERNSHIP_ASSISTANT_JOB_ANALYSIS_TEMPERATURE=0.0
AI_INTERNSHIP_ASSISTANT_JOB_ANALYSIS_TIMEOUT_SECONDS=30
AI_INTERNSHIP_ASSISTANT_JOB_ANALYSIS_MAX_INPUT_LENGTH=30000
AI_INTERNSHIP_ASSISTANT_ENABLE_LLM_ANALYSIS=false
AI_INTERNSHIP_ASSISTANT_ENABLE_HYBRID_ANALYSIS=false
```

LLM and hybrid analysis are disabled by default for safe local development.
Every LLM call has cost and latency, and structured extraction can still
misclassify ambiguous language. Hybrid fallback and explicit analysis
provenance make those limitations visible to downstream modules.

### Skill Gap Analysis

`SkillGapAnalyzer` deterministically compares a factual `CandidateProfile`
against a structured `JobAnalysis`. It returns an independent `SkillGapReport`
containing direct matches, missing required and preferred skills, certification
gaps, possible disqualifying concerns, learning recommendations, and safe
resume-emphasis opportunities. It makes no LLM or external API calls and does
not mutate either input.

Matching strength is intentionally explicit:

- `EXACT`: candidate and job terminology match case-insensitively.
- `NORMALIZED`: a centralized alias map proves equivalence, such as `Python3`
  to `Python`, `AWS` to `Amazon Web Services`, or `CompTIA Security+` to
  `Security+`.
- `RELATED`: a conservative relationship exists, but it is not a direct claim.
  Related evidence creates an emphasis opportunity only.
- `NONE`: reserved for consumers that need to represent no match.

Every missing skill has `safe_to_add_to_resume=false`. Related skills are also
not safe direct claims. For example, Wireshark may support careful emphasis
around packet analysis, but the system must not claim packet-analysis
experience unless that evidence exists in the candidate profile. Certification
recommendations likewise tell the candidate to learn about or pursue a
credential, never to add an unearned credential.

The report is the safety contract for future resume optimization: direct and
normalized matches identify existing facts that may be emphasized; related
opportunities explain cautious wording; gaps identify terms that must not be
claimed. Current matching uses finite alias and relationship dictionaries and
cannot understand every semantic relationship.

### Estimated ATS Match Scoring

`ATSMatchScoringService` estimates how well the candidate's current factual
resume and profile align with one structured job description. It produces an
explainable `ATSMatchReport` with component scores, keyword coverage,
required/preferred skill coverage, certification coverage, role, experience,
education alignment, resume-section scores, concern penalties, optimization
priority, and safety-aware guidance.

This is an internal deterministic heuristic, not a guarantee of success in any
real applicant tracking system. Proprietary ATS products use different,
undisclosed ranking and filtering behavior.

Default component weights are centralized in `ATSMatchScoringConfig`:

- required skill coverage: 30%
- ATS keyword coverage: 25%
- role alignment: 15%
- preferred skill coverage: 10%
- certification coverage: 7.5%
- experience-level alignment: 7.5%
- education alignment: 5%

Concern penalties are applied after weighted scoring. Estimated recommendation
levels are `EXCELLENT_MATCH` (90+), `STRONG_MATCH` (80+), `GOOD_MATCH` (70+),
`POSSIBLE_MATCH` (60+), `WEAK_MATCH` (40+), and `NOT_RECOMMENDED` (below 40).
Optimization priority separately estimates whether factual tailoring is likely
to be useful.

The ATS report respects the skill-gap safety contract. Missing skills with
`safe_to_add_to_resume=false` remain missing and guidance explicitly says not
to add them without actual evidence. Section-level opportunities may suggest
where existing facts could be emphasized, but this phase does not rewrite the
resume.

Job fit ranking and ATS match scoring answer different questions:

- Job fit ranking: should the candidate consider this job?
- Estimated ATS match scoring: how well does the current resume align with this
  job description?
