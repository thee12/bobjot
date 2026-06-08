# Project Context

## Product Summary

AI Internship Application Assistant helps users discover suitable internships and entry-level roles, analyze job descriptions, and generate tailored resume versions while preserving factual accuracy.

## Architectural Intent

The project uses a modular `src` layout with clear boundaries:

- Domain models represent resumes, jobs, extracted ATS signals, scores, generated resume versions, and application history.
- Service modules will orchestrate parsing, job discovery, analysis, scoring, optimization, and document generation.
- Storage modules will isolate database concerns from business workflows.
- Configuration is centralized and typed.

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

