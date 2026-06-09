"""Versioned prompt for safe structured single-bullet rewriting."""

import json

from ai_internship_assistant.domain.models import BulletRewriteRequest

BULLET_REWRITE_PROMPT_VERSION = "resume-bullet-rewrite-v1"

BULLET_REWRITE_SYSTEM_PROMPT = """\
You are an expert technical resume bullet editor.

Rewrite exactly one resume bullet for a specific job while preserving factual accuracy.

You may only use information provided in the original bullet, candidate evidence,
safe keywords, related keywords, and optimization goal.

Rules:
- Do not invent technologies, tools, metrics, employers, dates, certifications,
  production environments, enterprise experience, security operations experience,
  leadership experience, or responsibilities.
- Do not include unsafe keywords.
- Do not include forbidden claims.
- Preserve the original accomplishment and meaning.
- Include safe keywords naturally and use related keywords only when candidate
  evidence directly supports the wording.
- Start with a strong action verb, stay concise, and obey max_length.
- If the bullet cannot be safely improved, return the original bullet.
- Return only structured data matching the supplied schema.
"""


def build_bullet_rewrite_prompt(request: BulletRewriteRequest) -> str:
    """Build a bounded prompt containing only bullet-level evidence and permissions."""

    return json.dumps(
        {
            "prompt_version": BULLET_REWRITE_PROMPT_VERSION,
            "original_bullet": request.original_bullet,
            "section_name": request.section_name,
            "parent_item_name": request.parent_item_name,
            "candidate_evidence": request.candidate_evidence,
            "target_job_title": request.target_job_title,
            "target_company": request.target_company,
            "safe_keywords": request.safe_keywords,
            "related_keywords": request.related_keywords,
            "unsafe_keywords": request.unsafe_keywords,
            "forbidden_claims": request.forbidden_claims,
            "desired_tone": request.desired_tone,
            "max_length": request.max_length,
            "optimization_goal": request.optimization_goal,
        },
        ensure_ascii=True,
        indent=2,
    )
