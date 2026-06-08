# Project Context

## Product Summary

AI Internship Application Assistant helps users discover suitable internships and entry-level roles, analyze job descriptions, and generate tailored resume versions while preserving factual accuracy.

## Architectural Intent

The project uses a modular `src` layout with clear boundaries:

- Domain models represent resumes, jobs, extracted ATS signals, scores, generated resume versions, and application history.
- Service modules will orchestrate parsing, job discovery, analysis, scoring, optimization, and document generation.
- Storage modules will isolate database concerns from business workflows.
- Configuration is centralized and typed.

## Candidate Profile Architecture

`CandidateProfile` is the normalized representation intended for most future
downstream modules. The rules-based `CandidateProfileGenerator` consumes a
`Resume` and `ValidationReport`, organizes existing skills, classifies domains
and experience level from explicit evidence, recommends evidence-supported
target role categories, and produces a confidence score.

The generator may classify evidence but must never add factual claims. Its
current limitations are intentional: domain and role maps are deterministic,
finite, and designed to be replaced or extended behind the `ProfileGenerator`
boundary without changing downstream consumers.

## Job Search Query Architecture

`JobSearchQueryGenerator` converts a `CandidateProfile` and optional
`JobSearchPreferences` into a deduplicated `JobSearchQuerySet`. Queries are
organized into high, medium, and low priority tiers according to primary and
secondary domain alignment. User preferences refine locations, remote or hybrid
modes, employment types, desired roles, and exclusions without discarding
candidate-profile evidence.

The generator is deterministic and source-agnostic. It does not search the
internet. Future Greenhouse, Lever, company-career-page, and other integrations
can consume `JobSearchQuery` objects directly without analyzing the candidate
profile themselves.

## Job Source Architecture

Every future provider integration implements the `JobSource` interface and
returns standardized `JobPosting` objects. Provider-specific payloads remain
available in `raw_data`, while normalized title, company, location, employment
type, work arrangement, canonical URL, and fingerprint fields provide one
consistent contract for downstream ranking, ATS analysis, and deduplication.

`JobSearchService` runs a `JobSearchQuerySet` across configured sources. Expected
provider failures become structured `JobSourceError` records, allowing results
from successful sources to remain available. Unexpected programming errors are
not silently swallowed.

`MockJobSource` returns realistic fake postings for tests and local development.
It must not be treated as a production provider and performs no HTTP requests.

## Greenhouse Integration

`GreenhouseJobSource` implements `JobSource` using Greenhouse's public Job Board
API list-jobs endpoint with `content=true`. A `GreenhouseCompanyConfig` defines
each editable company board by its public `board_token`. The adapter filters
jobs deterministically, normalizes matches into `JobPosting`, preserves the raw
Greenhouse payload, and records board-level failures without discarding results
from successful boards.

The integration uses no private APIs, authentication bypasses, cookies, login
pages, application automation, or rate-limit avoidance. The adapter treats
Greenhouse `updated_at` as the best available public date approximation for
`posted_date`; downstream modules should not assume it is the original posting
date. Tests use `httpx.MockTransport` and fixtures under
`tests/fixtures/greenhouse/`, so the test suite makes no live network calls.

## Lever Integration

`LeverJobSource` implements `JobSource` using Lever's public Postings API in
JSON mode. A `LeverCompanyConfig` identifies each editable public site by its
`company_slug`, matching the public URL pattern
`jobs.lever.co/{company_slug}`. The adapter defensively maps Lever posting
fields, categories, list sections, salary ranges, workplace type, and creation
timestamps into the standardized `JobPosting` contract while preserving the
raw posting payload.

Greenhouse returns a board response containing a `jobs` list, while Lever
returns the postings list directly and provides richer structured categories
and list sections. Both sources share deterministic role, location, seniority,
employment-type, and work-arrangement helpers.

The Lever integration uses published public data only. It does not use private
APIs, user cookies, logged-in pages, application POST endpoints, browser
automation, or rate-limit avoidance. Tests use `httpx.MockTransport` and
fixtures under `tests/fixtures/lever/`, so no live network calls occur.

## Job Normalization And Deduplication

`JobNormalizationService` creates a separate `NormalizedJobPosting` and never
mutates the original provider posting. Normalization covers common title
variants, a deliberately small company alias map, locations, remote variants,
tracking-free URLs, description whitespace, and deterministic fingerprints.

`JobDeduplicationService` is intentionally conservative. Identical normalized
apply or source URLs are strong duplicate evidence. Text-based merging requires
the same normalized company, highly similar title tokens, and the same known
location. Unknown-location similarities below the merge threshold remain
separate and generate warnings.

Every `JobDeduplicationGroup` preserves a canonical job plus all original
duplicate jobs and sources. Canonical selection favors completeness rather than
provider preference alone. This allows future embedding similarity,
LLM-assisted review, larger alias databases, and user-confirmed duplicate
decisions without changing downstream clean-job consumers.

## Job Fit Ranking

`JobFitScoringService` consumes `CandidateProfile` and clean `JobPosting`
objects. It produces independent `JobFitScore` objects and a deterministic
`RankedJobResultSet`; neither input is mutated. Component weights and flag
penalties are centralized in `JobFitScoringConfig`.

The current rule-based engine scores role, skills, domain, experience level,
employment type, location, certifications, and keywords. It records matched
and missing evidence, disqualifying flags, warnings, and concise explanations.
Ranking sorts by overall score, recommendation level, role relevance, posting
date, company, title, and stable job ID.

Known limitations are deliberate: keyword maps are finite, nearby-location
logic is limited to exact or same-state matching, and deterministic token
matching cannot understand all semantic role relationships. Future embedding,
LLM job-analysis, and ATS components can replace or augment individual scores
without changing downstream ranking consumers.

## Job Description Analysis

`RuleBasedJobDescriptionAnalyzer` is the first implementation of the
`JobDescriptionAnalyzer` protocol. It consumes standardized `JobPosting`
objects and returns immutable-by-convention, strongly typed `JobAnalysis`
results without mutating source postings or making network calls.

The analyzer combines normalized posting fields with selected textual provider
fields, cleans HTML and duplicate lines, and applies centralized term catalogs,
section-aware requirement classification, and conservative regular-expression
checks. Extracted `SkillRequirement` entries preserve evidence and distinguish
required, preferred, nice-to-have, and unknown context. Ambiguous requirements
remain unknown.

The rule-based implementation is explainable and suitable for tests, but its
catalogs and section heuristics are intentionally finite. Future OpenAI and
hybrid analyzers may augment semantic extraction behind the same protocol.
Downstream ATS scoring, skill-gap analysis, and resume optimization should
consume `JobAnalysis` rather than provider-specific raw text.

`OpenAIJobDescriptionAnalyzer` now provides that structured provider-backed
implementation using the versioned `job-description-analysis-v1` prompt. Its
privacy boundary accepts only `JobPosting` fields and never candidate profiles
or resume data. Provider responses are schema-validated, evidence snippets are
bounded, and locally trusted identity and hash fields replace provider-supplied
values.

`HybridJobDescriptionAnalyzer` always creates rule-based analysis first. It
prefers validated LLM section interpretation, retains exact deterministic
keyword matches, deduplicates merged fields, and lowers confidence when role,
domain, or seniority classifications disagree. Any expected LLM failure returns
the rule-based result with a warning instead of interrupting the job pipeline.
Analysis provenance is recorded as `RULE_BASED`, `LLM`, or `HYBRID`.

LLM analysis is opt-in because it adds latency, cost, and provider privacy
considerations. Typed settings control model, temperature, timeout, maximum
input length, and feature flags. The API key is read from `OPENAI_API_KEY` and
must not be committed.

## Phase 1 Scope

This scaffold includes:

- package structure
- project metadata
- dependency declarations
- typed Pydantic domain models
- placeholder modules with future responsibilities documented
- test package skeleton

This scaffold intentionally excludes:

- resume parsing logic
- job scraping logic
- LLM prompts
- FastAPI routes
- optimization logic
- ATS scoring algorithms
- database schema migrations

## AI Safety Constraint

The system must preserve truthfulness. Any future optimization component must be constrained to facts present in the user's source resume or explicitly supplied by the user. It may improve presentation but must not create new factual claims.
