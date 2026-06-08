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
