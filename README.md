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
