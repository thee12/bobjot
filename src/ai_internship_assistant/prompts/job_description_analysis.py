"""Versioned prompts for structured LLM job-description analysis."""

import json

from ai_internship_assistant.domain.models import JobPosting

JOB_DESCRIPTION_ANALYSIS_PROMPT_VERSION = "job-description-analysis-v1"

JOB_DESCRIPTION_ANALYSIS_SYSTEM_PROMPT = """\
You are an expert job description analyst for an AI internship application assistant.

Extract structured information only from the provided job posting.

Rules:
- Do not invent skills, certifications, requirements, responsibilities, or facts.
- Do not assume details that are missing from the posting.
- Use UNKNOWN enum values, null values, or empty lists when unclear.
- Separate required skills from preferred and nice-to-have skills.
- Preserve exact terminology from the job posting whenever possible.
- Preserve short evidence snippets for each extracted skill requirement.
- Identify ATS-relevant keywords and exclude generic filler language.
- Identify role category, domain category, seniority, internship relevance, and
  possible disqualifying requirements from the posting only.
- Return only structured data matching the supplied schema.
"""


def build_job_description_analysis_prompt(job: JobPosting, *, max_length: int) -> str:
    """Build a bounded job-only user prompt without candidate or resume data."""

    payload = {
        "prompt_version": JOB_DESCRIPTION_ANALYSIS_PROMPT_VERSION,
        "instruction": "Analyze only the provided job posting.",
        "job_title": job.title,
        "company": job.company,
        "location": job.location,
        "employment_type": job.employment_type.value,
        "work_arrangement": job.work_arrangement.value,
        "description": job.description,
        "responsibilities": job.responsibilities,
        "requirements": job.requirements,
        "preferred_qualifications": job.preferred_qualifications,
        "source_name": job.source_name,
        "apply_url": str(job.apply_url) if job.apply_url else None,
    }
    prompt = json.dumps(payload, ensure_ascii=True, indent=2)
    if len(prompt) <= max_length:
        return prompt
    return f"{prompt[:max_length]}\n[INPUT TRUNCATED AT {max_length} CHARACTERS]"
