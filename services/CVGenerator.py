"""
CV Generator service using Typst templates.

Reads a base Typst template, customizes objective/skills/experience order
based on AI-generated CV content, and compiles to PDF.

CRITICAL: Only reorders and re-emphasizes REAL content. Never fabricates.
"""

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Dict, List

from core.config import settings
from models.JobModels import Job

logger = logging.getLogger(__name__)

# Template mapping: classification -> Typst source file
CVS_DIR = Path.home() / ".config" / "cvs"
TEMPLATES = {
    "backend": CVS_DIR / "cv_marcos_bustos_backend.typ",
    "frontend": CVS_DIR / "cv_marcos_bustos_frontend.typ",
    "backend_ai": CVS_DIR / "cv_back_ia.typ",
}

# Output directory for generated PDFs
OUTPUT_DIR = Path("/tmp/jobfinder_cvs")


def _extract_section(content: str, section_name: str) -> Optional[str]:
    """
    Extract a section's content from Typst source.
    Handles both #section[Name] and #section("Name") patterns.
    Returns the content between the section header and the next #sectionsep or #section.
    """
    # Match section header (both bracket and paren styles)
    patterns = [
        rf'#section\[{re.escape(section_name)}\](.*?)(?=#sectionsep|#section\[|#section\(|$)',
        rf'#section\("{re.escape(section_name)}"\)(.*?)(?=#sectionsep|#section\[|#section\(|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.DOTALL)
        if match:
            return match.group(1).strip()
    return None


def _extract_objetivo(content: str) -> Optional[str]:
    """Extract the Objetivo Profesional section content."""
    return _extract_section(content, "Objetivo Profesional")


def _replace_objetivo(content: str, new_objetivo: str) -> str:
    """Replace the Objetivo Profesional section content."""
    patterns = [
        (r'(#section\[Objetivo Profesional\]\s*#descript\[)(.*?)(\])', r'\1' + new_objetivo + r'\3'),
        (r'(#section\("Objetivo Profesional"\)\s*#descript\[)(.*?)(\])', r'\1' + new_objetivo + r'\3'),
    ]
    for pattern, replacement in patterns:
        new_content = re.sub(pattern, replacement, content, count=1, flags=re.DOTALL)
        if new_content != content:
            return new_content
    return content


def _extract_skills_block(content: str) -> List[str]:
    """Extract all #oneline-title-item blocks as raw strings."""
    pattern = r'(#oneline-title-item\([^)]*\)(?:\s*\([^)]*\))*)'
    return re.findall(pattern, content, re.DOTALL)


def _reorder_skills(content: str, skills_order: List[str]) -> str:
    """
    Reorder #oneline-title-item blocks based on skills_order.
    
    Strategy: Build new skill blocks by matching skills from skills_order
    to the content of each existing block. Blocks with the first skill
    in skills_order appear first.
    """
    # Extract all oneline-title-item blocks with their full text
    block_pattern = r'(#oneline-title-item\(\s*\n\s*title: "[^"]*",\s*\n\s*content: \[[^\]]*\],?\s*\))'
    blocks = re.findall(block_pattern, content, re.DOTALL)
    
    if not blocks:
        return content

    # Parse each block to extract its title and content items
    parsed_blocks = []
    for block in blocks:
        title_match = re.search(r'title:\s*"([^"]*)"', block)
        content_match = re.search(r'content:\s*\[([^\]]*)\]', block)
        title = title_match.group(1) if title_match else ""
        items_str = content_match.group(1) if content_match else ""
        items = [item.strip() for item in items_str.split(",") if item.strip()]
        parsed_blocks.append({
            "raw": block,
            "title": title,
            "items": items,
        })

    # Score each block: count how many of its items appear early in skills_order
    def block_relevance(block):
        score = 0
        for item in block["items"]:
            # Normalize for matching (lowercase, strip parens content for comparison)
            item_norm = item.lower().split("(")[0].strip()
            for i, skill in enumerate(skills_order):
                skill_norm = skill.lower().split("(")[0].strip()
                if item_norm in skill_norm or skill_norm in item_norm:
                    score += len(skills_order) - i  # Higher score for earlier skills
                    break
        return score

    # Sort blocks by relevance (highest first)
    sorted_blocks = sorted(parsed_blocks, key=block_relevance, reverse=True)

    # Replace the skills section in content
    # Find the skills section boundaries
    skills_start = content.find('#section("Habilidades")')
    if skills_start == -1:
        skills_start = content.find('#section[Habilidades]')
    
    if skills_start == -1:
        return content

    # Find where skills section ends (next #sectionsep or #section)
    after_skills = content[skills_start:]
    # Find the next sectionsep after skills
    sep_match = re.search(r'#sectionsep', after_skills[20:])  # Skip past the section header
    if sep_match:
        skills_end = skills_start + 20 + sep_match.start()
    else:
        skills_end = len(content)

    # Rebuild: keep everything before skills, then sorted blocks, then everything after
    before = content[:skills_start]
    after = content[skills_end:]

    new_skills_section = '#section("Habilidades")\n\n'
    new_skills_section += "\n\n".join(b["raw"] for b in sorted_blocks)
    new_skills_section += "\n\n"

    return before + new_skills_section + after


def _reorder_experience(content: str, experience_order: List[int]) -> str:
    """
    Reorder #job blocks in the Experiencia section based on experience_order.
    
    Indices: 0=Código del Mar, 1=Beemore, 2=Cliente US
    """
    # Find the Experiencia section
    exp_start = content.find('#section("Experiencia")')
    if exp_start == -1:
        exp_start = content.find('#section[Experiencia]')
    
    if exp_start == -1:
        return content

    # Find all #job blocks in the experience section
    # First, find the end of the experience section
    after_exp_header = content[exp_start:]
    
    # Find where experience section ends (next #sectionsep after the header)
    sep_positions = [m.start() for m in re.finditer(r'#sectionsep', after_exp_header)]
    if sep_positions:
        # First sectionsep after the header
        exp_end = exp_start + sep_positions[0]
    else:
        exp_end = len(content)

    exp_section = content[exp_start:exp_end]
    
    # Extract individual #job blocks
    # Match #job( ... ) with nested brackets
    job_blocks = []
    pos = 0
    while pos < len(exp_section):
        job_start = exp_section.find('#job(', pos)
        if job_start == -1:
            break
        
        # Find matching closing paren by counting depth
        depth = 0
        i = job_start + 5  # After '#job'
        while i < len(exp_section):
            if exp_section[i] == '(':
                depth += 1
            elif exp_section[i] == ')':
                if depth == 0:
                    job_blocks.append(exp_section[job_start:i + 1])
                    pos = i + 1
                    break
                depth -= 1
            i += 1
        else:
            # Didn't find matching paren, take rest
            job_blocks.append(exp_section[job_start:])
            break

    if len(job_blocks) < 3:
        # Not enough blocks to reorder, return as-is
        return content

    # Map experience index to company name for matching
    company_map = {
        0: "Código del Mar",
        1: "Beemore",
        2: "Cliente US",
    }

    # Match blocks to indices by checking which company name appears in each block
    index_to_block = {}
    for idx, block in enumerate(job_blocks):
        # Default mapping: blocks appear in order 0, 1, 2
        if idx < 3:
            index_to_block[idx] = block

    # Try to match by company name for more accurate mapping
    for idx, block in enumerate(job_blocks):
        for exp_idx, company in company_map.items():
            if company.lower() in block.lower():
                index_to_block[exp_idx] = block
                break

    # Build reordered blocks
    reordered = []
    for exp_idx in experience_order:
        if exp_idx in index_to_block:
            reordered.append(index_to_block[exp_idx])

    # Replace the experience section
    before = content[:exp_start]
    after = content[exp_end:]

    new_exp_section = '#section("Experiencia")\n\n'
    new_exp_section += "\n\n".join(reordered)
    new_exp_section += "\n\n"

    return before + new_exp_section + after


def generate_custom_typst(
    job: Job,
    cv_content,  # CVContent from GroqService
    classification: str,
) -> Optional[str]:
    """
    Generate a customized Typst file for a specific job.

    1. Reads the base template based on classification
    2. Replaces the objective section with the generated one
    3. Reorders skills based on skills_order
    4. Reorders experience based on experience_order
    5. Writes the custom .typ to /tmp/jobfinder_cvs/
    6. Compiles to PDF

    Returns the PDF path on success, None on failure.
    """
    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Select base template
    template = TEMPLATES.get(classification)
    if not template or not template.exists():
        logger.error(f"Template not found for classification '{classification}': {template}")
        return None

    # Read base template
    try:
        content = template.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read template {template}: {e}")
        return None

    logger.info(f"📝 Customizing CV for: {job.title} @ {job.company}")
    logger.info(f"   Base template: {template.name}")
    logger.info(f"   Profile: {classification}")

    # 1. Replace objective
    content = _replace_objetivo(content, cv_content.objetivo)
    logger.info(f"   ✅ Objective replaced")

    # 2. Reorder skills
    content = _reorder_skills(content, cv_content.skills_order)
    logger.info(f"   ✅ Skills reordered: {cv_content.skills_order[:5]}...")

    # 3. Reorder experience
    content = _reorder_experience(content, cv_content.experience_order)
    logger.info(f"   ✅ Experience reordered: {cv_content.experience_order}")

    # 4. Update document title
    safe_company = job.company.replace('"', '\\"')
    safe_title = job.title.replace('"', '\\"')
    content = re.sub(
        r'#set document\(author: "[^"]*", title: "[^"]*"\)',
        f'#set document(author: "{settings.CANDIDATE_NAME}", title: "CV {settings.CANDIDATE_NAME} — {safe_company} — {safe_title}")',
        content,
    )

    # 5. Write custom .typ file
    safe_name = f"{job.company}_{job.title}".replace(" ", "_").replace("/", "_")
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in "_-")[:80]
    custom_typ = OUTPUT_DIR / f"custom_{safe_name}.typ"
    output_pdf = OUTPUT_DIR / f"{safe_name}.pdf"

    try:
        custom_typ.write_text(content, encoding="utf-8")
        logger.info(f"   📄 Custom .typ written: {custom_typ}")
    except Exception as e:
        logger.error(f"Failed to write custom .typ: {e}")
        return None

    # 6. Compile to PDF
    try:
        result = subprocess.run(
            ["typst", "compile", str(custom_typ), str(output_pdf)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"Typst compile failed: {result.stderr}")
            return None

        if output_pdf.exists():
            logger.info(f"✅ CV generated: {output_pdf}")
            return str(output_pdf)
        else:
            logger.error(f"Typst completed but PDF not found at {output_pdf}")
            return None

    except subprocess.TimeoutExpired:
        logger.error("Typst compile timed out after 30s")
        return None
    except FileNotFoundError:
        logger.error("typst CLI not found. Install it: https://github.com/typst/typst")
        return None
    except Exception as e:
        logger.error(f"Unexpected error generating CV: {e}")
        return None


# Legacy function kept for backward compatibility
def classify_job(job: Job) -> str:
    """Classify a job into one of: backend, frontend, backend_ai."""
    text = ""
    if job.description:
        text += job.description.lower()
    if job.tags:
        text += " " + job.tags.lower()

    AI_KEYWORDS = {"ai", "machine learning", "ml", "llm", "openai", "langchain",
                   "artificial intelligence", "deep learning", "neural", "nlp",
                   "gpt", "transformer", "copilot", "gemini", "claude"}
    FRONTEND_KEYWORDS = {"react", "frontend", "ux", "ui", "css", "figma",
                         "vue", "angular", "svelte", "next.js", "nextjs",
                         "tailwind", "styled-components", "design system"}

    if any(kw in text for kw in AI_KEYWORDS):
        return "backend_ai"
    if any(kw in text for kw in FRONTEND_KEYWORDS):
        return "frontend"
    return "backend"


def generate_cv(job: Job, classification: str) -> Optional[str]:
    """
    Legacy function: Generate a CV PDF using the static template (no customization).
    Kept for backward compatibility. Prefer generate_custom_typst() for new pipeline.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    template = TEMPLATES.get(classification)
    if not template or not template.exists():
        logger.error(f"Template not found for classification '{classification}': {template}")
        return None

    safe_name = f"{job.company}_{job.title}".replace(" ", "_").replace("/", "_")
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in "_-")[:80]
    output_pdf = OUTPUT_DIR / f"{safe_name}.pdf"

    try:
        result = subprocess.run(
            ["typst", "compile", str(template), str(output_pdf)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"Typst compile failed: {result.stderr}")
            return None

        if output_pdf.exists():
            logger.info(f"CV generated (static): {output_pdf}")
            return str(output_pdf)
        else:
            logger.error(f"Typst completed but PDF not found at {output_pdf}")
            return None

    except subprocess.TimeoutExpired:
        logger.error("Typst compile timed out after 30s")
        return None
    except FileNotFoundError:
        logger.error("typst CLI not found. Install it: https://github.com/typst/typst")
        return None
    except Exception as e:
        logger.error(f"Unexpected error generating CV: {e}")
        return None
