import json
import logging
import instructor
from groq import Groq
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Optional
from core.config import settings
from models.JobModels import Job
from services.AnalysisRetry import (
    TransientAnalysisError,
    compute_backoff,
    extract_retry_after,
    extract_status_code,
    is_transient_exception,
)
from services.EnglishPolicy import ENGLISH_LEVELS, EnglishLevelLiteral, normalize_level


# --- Candidate Profile (REAL data — never fabricated) ---
CANDIDATE_PROFILE = {
    "name": settings.CANDIDATE_NAME,
    "email": settings.CANDIDATE_EMAIL,
    "location": settings.CANDIDATE_LOCATION,
    "portfolio": "https://markbus-ai.github.io",
    "linkedin": "https://www.linkedin.com/in/marcos-bustos-7327962ab/",
    "github": "https://github.com/markbus-ai",
    "experience": [
        {
            "company": "Beemore / Appi.ar",
            "role": "Freelance Backend & Mobile Developer",
            "period": "2026 - Actualidad",
            "location": "Remoto / Mar del Plata, ARG",
            "highlights": [
                "Desarrollo full-stack de AppiarWeb: plataforma de gestión apícola en producción con React 19, TypeScript, Firebase (Auth, Firestore, Storage, Functions), MUI y TanStack Query.",
                "Integración con Leaflet para mapas interactivos, Recharts para métricas en tiempo real, y Cloudinary para gestión multimedia.",
                "Arquitectura offline-first para zonas rurales sin conectividad estable. Desarrollo mobile con Flutter.",
                "Refactorización de código legacy, optimización de performance y hardening de seguridad.",
                "Gestión de usuarios con roles, i18n completo y sistema de semáforo para estado sanitario de colmenas.",
            ],
            "skills_used": ["React 19", "TypeScript", "Firebase", "MUI", "TanStack Query", "Leaflet", "Recharts", "Flutter", "Cloudinary", "Vite"],
        },
        {
            "company": "Bicicletería Amigorena",
            "role": "Backend Developer Freelance",
            "period": "2024 - Actualidad",
            "location": "Mar del Plata, ARG",
            "highlights": [
                "Bot automatizado de atención al cliente con +5,000 mensajes/mes procesados, 94.7% de efectividad y 99.5% de consultas resueltas.",
                "Atención 24/7 garantizada con detección de intenciones, cola de mensajes inteligente y soporte para fallos de conexión.",
                "Mantenimiento continuo, reconexión automática con lógica exponencial de reintentos y mejoras sobre el sistema en producción.",
            ],
            "skills_used": ["Python", "Playwright", "Asyncio", "OpenAI API"],
        },
        {
            "company": "BlackFire E-Commerce",
            "role": "Full-Stack Developer",
            "period": "2024 - 2025",
            "location": "Remoto",
            "highlights": [
                "Plataforma e-commerce completa en producción con backend en FastAPI y frontend en React.",
                "Pagos en línea con Mercado Pago mediante preferencias de pago y webhooks de confirmación, con manejo de doble cuenta para mayoristas.",
                "Catálogo jerárquico de categorías y productos, panel de administración dinámico, carrito de compras persistente y procesamiento de pedidos.",
                "Empaquetado y orquestado completamente con Docker y Docker Compose.",
            ],
            "skills_used": ["Python", "FastAPI", "React", "PostgreSQL", "Docker", "Mercado Pago"],
        },
        {
            "company": "Cliente US (Fintech)",
            "role": "Desarrollador Backend (Contractor)",
            "period": "2024 - 2025",
            "location": "Remoto",
            "highlights": [
                "Web scrapers asincrónicos con Python para extracción automatizada de datos a escala.",
                "Procesamiento concurrente de +39 productos desde 6 plataformas distintas en simultáneo.",
                "Reportes automatizados y dashboards para monitoreo de datos y toma de decisiones.",
            ],
            "skills_used": ["Python", "Asyncio", "Playwright", "Dashboards"],
        },
        {
            "company": "Beemore Landing",
            "role": "Frontend Developer",
            "period": "2025",
            "location": "Remoto",
            "highlights": [
                "Landing page en producción en beemore.com.ar con i18n completo (es/en/it) y presencia internacional.",
                "Secciones de servicios, feed de Instagram integrado, formulario de contacto y showcase del dashboard Appi.AR.",
                "SEO, GEO y Core Web Vitals optimizados con output estático.",
            ],
            "skills_used": ["Astro", "TypeScript", "CSS", "SEO", "i18n"],
        },
        {
            "company": "MozoPlus",
            "role": "Backend Developer",
            "period": "2024",
            "location": "Mar del Plata, ARG",
            "highlights": [
                "Sistema de gestión de pedidos en tiempo real con sincronización instantánea de comandas entre mozos y cocina.",
                "Backend asincrónico escalable con FastAPI, WebSockets y PostgreSQL para alta demanda concurrente.",
                "Diseño mobile con Flutter para interfaz de mozos.",
            ],
            "skills_used": ["FastAPI", "WebSockets", "PostgreSQL", "Flutter"],
        },
        {
            "company": "Coaching Emocional",
            "role": "Full-Stack Developer",
            "period": "2024",
            "location": "Remoto",
            "highlights": [
                "Diseño y desarrollo de landing page optimizada para conversión.",
                "Despliegue en VPS Linux con reverse proxy Nginx y Cloudflare.",
            ],
            "skills_used": ["React", "Linux", "Nginx", "Cloudflare", "VPS"],
        },
    ],
    "skills": {
        "backend_core": ["Python (Asyncio)", "FastAPI", "Flask", "PostgreSQL", "MariaDB", "SQLite", "SQL", "Bash"],
        "frontend": ["React 19", "TypeScript", "JavaScript (ES6+)", "MUI", "TanStack Query", "HTML", "CSS", "Vite"],
        "mobile": ["Flutter"],
        "firebase_baas": ["Firebase (Auth, Firestore, Storage, Functions)", "Cloudinary"],
        "ai_ia": ["OpenAI API", "LangChain", "Playwright", "n8n"],
        "devops": ["Docker", "Docker Compose", "Git", "GitHub Actions", "Linux (SysAdmin)", "Nginx", "Cloudflare", "VPS"],
        "data_viz": ["Leaflet", "Recharts"],
        "other": ["Astro", "Mercado Pago", "i18n", "SEO", "XPath"],
        "systems_c": ["C", "Tesseract OCR", "libcurl", "libarchive", "Linux CLI", "Hyprland", "Wayland", "Sway WM"],
        "testing": ["pytest", "Debugging"],
        "languages": ["Español (Nativo)", "Inglés Técnico"],
    },
    "education": [
        {"institution": "ISFT 204", "degree": "Tecnicatura Superior en Desarrollo de Software", "period": "2024 - En curso"},
        {"institution": "CFP 403", "degree": "Especialización Backend, Bases de Datos y Testing", "period": "2023 - 2026"},
    ],
    "projects": [
        {
            "name": "AppiarWeb / Beemore",
            "description": "Plataforma integral de gestión apícola en producción con React 19, TypeScript, Firebase, MUI, TanStack Query, Leaflet y offline-first.",
            "url": "https://beemore.com.ar/login",
            "tech": ["React 19", "TypeScript", "Firebase", "MUI", "TanStack Query", "Leaflet", "Recharts", "Vite"],
        },
        {
            "name": "Beemore Landing",
            "description": "Landing page multilingüe (es/en/it) con Astro, SEO optimizado y Core Web Vitals.",
            "url": "https://beemore.com.ar/",
            "tech": ["Astro", "TypeScript", "i18n", "SEO"],
        },
        {
            "name": "BlackFire E-Commerce",
            "description": "E-commerce completo en producción con FastAPI, React, Mercado Pago, Docker y PostgreSQL.",
            "url": "https://blackfire.com.ar/",
            "tech": ["Python", "FastAPI", "React", "Docker", "PostgreSQL", "Mercado Pago"],
        },
        {
            "name": "MozoPlus",
            "description": "Sistema de pedidos en tiempo real con FastAPI, WebSockets, PostgreSQL y Flutter.",
            "url": "",
            "tech": ["FastAPI", "WebSockets", "PostgreSQL", "Flutter"],
        },
        {
            "name": "whatsapp-bot",
            "description": "Bot automatizado de WhatsApp para gestión comercial. +5000 msgs/mes, 94.7% efectividad.",
            "url": "",
            "tech": ["Python", "Playwright", "Asyncio"],
        },
        {
            "name": "WhatsPlay",
            "description": "Librería Open Source para automatizar WhatsApp Web via Playwright.",
            "url": "https://github.com/markbus-ai/whatsplay",
            "tech": ["Python", "Playwright", "XPath"],
        },
        {
            "name": "mutils",
            "description": "Colección de micro-utilidades CLI en C para Linux (OCR, port slayer, nuke, smart extract).",
            "url": "https://github.com/markbus-ai/mutils",
            "tech": ["C", "Tesseract OCR", "Linux CLI", "libcurl", "libarchive"],
        },
        {
            "name": "qrgen",
            "description": "Generador de códigos QR personalizable con React + FastAPI + Python.",
            "url": "https://markbus-ai.github.io/qrgen",
            "tech": ["React", "Vite", "FastAPI", "Python", "Mantine"],
        },
    ],
    "open_source": [
        {
            "name": "WhatsPlay",
            "description": "Librería de automatización WhatsApp Web (Playwright + Python). Selectores XPath resilientes, persistencia de sesión 24/7 en Linux.",
            "url": "https://github.com/markbus-ai/whatsplay",
        },
        {
            "name": "mutils",
            "description": "Micro-utilidades CLI en C para Linux. OCR con Tesseract, port slayer, nuke, smart extract.",
            "url": "https://github.com/markbus-ai/mutils",
        },
    ],
}

# Compact scoring profile derived verbatim from CANDIDATE_PROFILE.
# It is sent once per job analysis, so it only keeps what is needed to judge
# technical fit: identity, location, skills, role summaries, languages, education.
SCORING_PROFILE = {
    "name": CANDIDATE_PROFILE["name"],
    "location": CANDIDATE_PROFILE["location"],
    "skills": CANDIDATE_PROFILE["skills"],
    "experience": [
        {
            "company": entry["company"],
            "role": entry["role"],
            "period": entry["period"],
            "skills_used": entry["skills_used"],
        }
        for entry in CANDIDATE_PROFILE["experience"]
    ],
    "languages": CANDIDATE_PROFILE["skills"]["languages"],
    "education": CANDIDATE_PROFILE["education"],
}


# Both the response schema and the prompt derive their vocabulary from
# services.EnglishPolicy.ENGLISH_LEVELS, the single source of truth. Rendering
# it here keeps the model from ever being told a level the gate does not know.
_QUOTED_ENGLISH_LEVELS = ", ".join(f"'{level}'" for level in ENGLISH_LEVELS)

# Ordered to match ENGLISH_LEVELS (ascending difficulty) so the meaning of each
# level stays attached to the right key.
_ENGLISH_LEVEL_MEANINGS = (
    "no English needed (listing is fully in Spanish/Portuguese or states no language requirement)",
    "only reading simple English docs or occasional English terms",
    "can read/write technical English and join occasional English meetings",
    "day-to-day spoken English, meetings with English-speaking clients or teams, "
    "or an explicit 'fluent English required'",
)
_ENGLISH_REQUIRED_DESCRIPTION = (
    "English level the listing requires, judged ONLY from the listing text. One of "
    + "; ".join(
        f"'{level}' = {meaning}"
        for level, meaning in zip(ENGLISH_LEVELS, _ENGLISH_LEVEL_MEANINGS)
    )
    + ". Use null when the listing is silent or the level cannot be judged. "
    "Default to 'intermediate' when the listing says nothing about English; never "
    "guess 'fluent' without evidence."
)

# Rule 11 of the analysis system prompt. The default sentence is load-bearing:
# without it the model guesses 'fluent' more often, which the gate then withholds.
ENGLISH_LEVEL_PROMPT = (
    "11. ENGLISH LEVEL: Judge 'english_required' from the listing text only, using the "
    f"closed vocabulary {_QUOTED_ENGLISH_LEVELS}. Use 'fluent' only with "
    "explicit evidence such as meetings with English-speaking clients/teams, "
    "'fluent English required', or the whole listing being in English. 'English is a plus' "
    "is at most 'intermediate'. When the listing says nothing about English, default to "
    "'intermediate' rather than guessing 'fluent'. Quote the justifying text in "
    "'english_evidence', or leave it empty when the listing says nothing."
)


class JobAudit(BaseModel):
    """AI-generated audit of job-candidate fit."""

    match_score: int = Field(
        description=(
            "Technical overlap score from 0 to 100 between the candidate's real stack and the "
            "job's required stack. It is NOT a recommendation or interest score. If the candidate "
            "profile is missing or empty, return 0."
        )
    )
    is_suitable: bool = Field(
        description=(
            "True only when the job's required stack genuinely overlaps the candidate's real skills "
            "AND the candidate lacks no hard requirement (e.g. foreign residence, mandatory "
            "seniority, mandatory language). It is NOT a discretionary flag and must be false when "
            "the profile is missing or empty. It never overrides match_score."
        )
    )
    missing_skills: List[str] = Field(description="Technologies or requirements the job asks for that the candidate lacks")
    seniority_mismatch: bool = Field(description="True if the job requires significantly more experience than the profile shows")
    short_verdict: str = Field(description="Objective technical justification, max 15 words")
    recommended_profile: str = Field(description="Which CV profile to use: 'backend', 'frontend', or 'backend_ai'")
    key_requirements: List[str] = Field(description="Top 3-5 technical requirements extracted from the job listing")
    work_mode: str = Field(
        default="unknown",
        description="One of: 'remote', 'hybrid', 'onsite', 'unknown'. Infer from the listing text.",
    )
    job_country: str = Field(
        default="",
        description="Country named by the listing, or empty string when none is stated.",
    )
    job_city: str = Field(
        default="",
        description="City named by the listing, or empty string when none is stated.",
    )
    requires_residence_in: str = Field(
        default="",
        description=(
            "Country or region name the listing explicitly requires the candidate to reside in. "
            "Must be a plain country/region name only, never free prose. Empty string when none."
        ),
    )
    english_required: Optional[EnglishLevelLiteral] = Field(
        default=None,
        description=_ENGLISH_REQUIRED_DESCRIPTION,
    )
    english_evidence: str = Field(
        default="",
        description=(
            "Short quote from the listing that justifies english_required "
            "(e.g. 'fluent English required', 'English is a plus'). Empty string when the "
            "listing says nothing about English."
        ),
    )

    @field_validator("english_required", mode="before")
    @classmethod
    def _coerce_english_required(cls, value: object) -> Optional[str]:
        """
        Map anything outside the closed vocabulary to ``None``.

        The model is asked for a fixed vocabulary, but a non-compliant answer
        ('C1', 'fluent English', a stray number) must neither crash the analysis
        nor slip past the gate. Normalizing to ``None`` keeps the failure closed
        and auditable: ``english_allowed(None, ...)`` withholds the row.
        """
        normalized = normalize_level(value)
        return None if normalized is None else normalized.value


class CVContent(BaseModel):
    """Structured CV content generated by AI for a specific job."""

    objetivo: str = Field(description="Custom objective paragraph in Spanish, 2-3 sentences, mapped to real skills")
    skills_order: List[str] = Field(description="Skills reordered by relevance to the job, from most to least relevant")
    experience_order: List[int] = Field(description="Indices of experience entries reordered: 0=Código del Mar, 1=Beemore, 2=Cliente US")
    experience_emphasis: Dict[int, str] = Field(
        description="For each experience index, which aspects to emphasize (e.g., 'Focus on FastAPI/WebSockets')"
    )


class AIService:
    def __init__(self, api_key: str = settings.GROQ_API_KEY, model: str = settings.GROQ_MODEL, sleep=None):
        # Support key rotation: GROQ_API_KEYS (comma-separated) or single GROQ_API_KEY
        self._keys = []
        if settings.GROQ_API_KEYS:
            self._keys = [k.strip() for k in settings.GROQ_API_KEYS.split(",") if k.strip()]
        elif api_key:
            self._keys = [api_key]
        
        self._key_index = 0
        self.model = model
        self.client = self._make_client()
        
        # Rate limit tracking per key: {key_index: [timestamps]}
        import time
        self._time = time
        self._sleep = sleep if sleep is not None else time.sleep
        self._request_times: Dict[int, list] = {i: [] for i in range(len(self._keys))}
        self._MIN_DELAY = 0.5  # Min seconds between requests per key
        self._MAX_RPM_PER_KEY = 28  # Stay under 30 RPM limit

    def _make_client(self):
        key = self._keys[self._key_index % len(self._keys)]
        return instructor.from_groq(Groq(api_key=key), mode=instructor.Mode.JSON)

    def _rotate_key(self):
        """Rotate to next API key with cooldown tracking."""
        if len(self._keys) > 1:
            # Clean old timestamps (older than 60s)
            now = self._time.time()
            for idx in self._request_times:
                self._request_times[idx] = [t for t in self._request_times[idx] if now - t < 60]
            
            # Find key with fewest recent requests
            best_idx = min(range(len(self._keys)), key=lambda i: len(self._request_times[i]))
            if best_idx != self._key_index:
                self._key_index = best_idx
                self.client = self._make_client()
                logging.getLogger(__name__).info(f"🔄 Rotated to Groq key #{self._key_index + 1} ({len(self._request_times[self._key_index])} req/min)")

    def _check_rate_limit(self):
        """Wait if current key is near rate limit."""
        now = self._time.time()
        idx = self._key_index
        # Clean old timestamps
        self._request_times[idx] = [t for t in self._request_times[idx] if now - t < 60]
        
        if len(self._request_times[idx]) >= self._MAX_RPM_PER_KEY:
            # Key exhausted, rotate
            logging.getLogger(__name__).warning(f"⚠️ Key #{idx + 1} at {self._MAX_RPM_PER_KEY} RPM, rotating...")
            self._rotate_key()
            return True
        return False

    def _record_request(self):
        """Record request timestamp for rate limiting."""
        now = self._time.time()
        self._request_times[self._key_index].append(now)
        # Auto-rotate if approaching limit
        if len(self._request_times[self._key_index]) >= self._MAX_RPM_PER_KEY - 2:
            self._rotate_key()

    def analyze_job(self, job: Job, cv_data: Dict[str, Any]) -> JobAudit:
        """
        Analyze a job listing against a candidate profile (CV) for objective compatibility.
        Uses structured metadata when available to improve analysis accuracy.
        Rotates API keys on failure and respects rate limits.
        """
        if not cv_data:
            # Fail closed: never produce a confident score without candidate data.
            logging.getLogger(__name__).warning(
                "analyze_job called without candidate profile data; returning zero score."
            )
            return JobAudit(
                match_score=0,
                is_suitable=False,
                missing_skills=["No candidate profile data provided"],
                seniority_mismatch=False,
                short_verdict="No candidate profile data provided",
                recommended_profile="backend",
                key_requirements=[],
                work_mode="unknown",
                job_country="",
                job_city="",
                requires_residence_in="",
                english_required=None,
                english_evidence="",
            )

        max_retries = max(len(self._keys) * 2, 1)  # Try each key up to 2 times
        last_error = None
        last_transient = False
        last_retry_after = None
        last_status_code = None
        
        for attempt in range(max_retries):
            try:
                # Check rate limit before making request
                self._check_rate_limit()
                self._record_request()
                # Ensure string (pandas may return float NaN)
                job_desc = str(job.description) if job.description is not None else "No description available"

                # Build structured context from metadata
                structured_context = ""
                if job.seniority:
                    structured_context += f"\nReported seniority level: {job.seniority}"
                if job.tags:
                    try:
                        tag_list = json.loads(job.tags) if isinstance(job.tags, str) else job.tags
                        structured_context += f"\nJob skills/tags: {', '.join(tag_list)}"
                    except (json.JSONDecodeError, TypeError):
                        pass
                if job.modality:
                    structured_context += f"\nModality: {job.modality}"
                if job.source_platform:
                    structured_context += f"\nSource: {job.source_platform}"

                audit = self.client.chat.completions.create(
                    model=self.model,
                    response_model=JobAudit,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Act as a technical audit engine. Your task is to perform a strict "
                                "compatibility analysis between a professional profile (JSON) and a job listing.\n\n"
                                "EVALUATION RULES:\n"
                                "1. Base your analysis solely on facts present in the data. If a skill is not in the JSON, "
                                "assume the candidate does not have it.\n"
                                "2. The 'match_score' must be a metric of TECHNICAL OVERLAP only (tech-stack "
                                "overlap). It must be LOW when the candidate profile does not contain the "
                                "required stack. Never inflate it for location, seniority, or enthusiasm.\n"
                                "3. Identify 'seniority' discrepancies by comparing years of experience and project "
                                "responsibility in the CV against job requirements.\n"
                                "4. Be critical with corporate job language: extract the real technical requirements "
                                "hidden behind generic descriptions.\n"
                                "5. The verdict must be a logical conclusion, not a motivational recommendation.\n"
                                f"6. GEOGRAPHIC ELIGIBILITY (NON-NEGOTIABLE): The candidate lives in Mar del Plata, "
                                "Argentina. On-site and hybrid roles are acceptable ONLY in Mar del Plata. Remote "
                                "roles are acceptable UNLESS they require residence in another country (for example "
                                "'Remote - Spain', 'Remote (Barcelona)', 'must reside in Spain', 'US only'). An "
                                "on-site or hybrid role in any other city or country is NOT eligible, regardless of "
                                "technical fit. Never adjust match_score for geography: report the facts in "
                                "'work_mode', 'job_country', 'job_city', and 'requires_residence_in' instead.\n"
                                "7. If structured seniority is provided by the platform, use it as the primary "
                                "reference for evaluating 'seniority_mismatch' — it is more reliable than inferring "
                                "from the description alone.\n"
                                "8. CLASSIFICATION: Determine the best CV profile based on the job's core stack:\n"
                                "   - 'backend_ai': if the job mentions AI, machine learning, LLMs, OpenAI, LangChain, "
                                "deep learning, NLP, transformers, or similar AI/ML keywords\n"
                                "   - 'frontend': if the job is primarily React, Vue, Angular, CSS, UI/UX, Figma, "
                                "or frontend-focused\n"
                                "   - 'backend': for everything else (Python, APIs, databases, DevOps, etc.)\n"
                                "9. KEY REQUIREMENTS: Extract the top 3-5 specific technical requirements from the job "
                                "listing. Be precise (e.g., 'FastAPI', 'PostgreSQL', 'React 19') not generic "
                                "(e.g., 'programming', 'web development').\n"
                                "10. MISSING DATA: If the candidate profile is missing, empty, or does not allow you "
                                "to verify the required stack, return match_score = 0 and is_suitable = false. Never "
                                "guess or default to a confident score.\n"
                                f"{ENGLISH_LEVEL_PROMPT}"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"CANDIDATE DATA (JSON):\n{cv_data}\n\n"
                                f"JOB DATA:\nTitle: {job.title}\nCompany: {job.company}\n"
                                f"Location: {job.location}\nDescription: {job_desc[:3000]}"
                                f"{structured_context}"
                            ),
                        },
                    ]
                )
                return audit
            except Exception as e:
                last_error = e
                last_transient = is_transient_exception(e)
                last_retry_after = extract_retry_after(e)
                last_status_code = extract_status_code(e)
                kind = "transient" if last_transient else "permanent"
                logging.getLogger(__name__).warning(
                    f"Groq key #{self._key_index + 1} failed ({kind}): {e}"
                )
                if attempt < max_retries - 1:
                    if last_transient:
                        # Honor Retry-After when provided; otherwise bounded backoff.
                        delay = compute_backoff(attempt, last_retry_after)
                        self._sleep(delay)
                    self._rotate_key()

        # A transient failure must not be turned into a permanent score: signal
        # the caller so it can persist a retryable row instead of a fake 0/100.
        if last_transient:
            raise TransientAnalysisError(
                f"Transient analysis failure: {str(last_error)[:150]}",
                status_code=last_status_code,
                retry_after=last_retry_after,
            )

        return JobAudit(
            match_score=0,
            is_suitable=False,
            missing_skills=["Error en procesamiento de IA"],
            seniority_mismatch=False,
            short_verdict=f"Error técnico: {str(last_error)[:50]}",
            recommended_profile="backend",
            key_requirements=[],
            english_required=None,
            english_evidence="",
        )

    def generate_cv_content(self, job: Job, audit: JobAudit) -> CVContent:
        """
        Generate customized CV content for a specific job using Groq.
        Rotates API keys on failure and respects rate limits.
        """
        max_retries = max(len(self._keys) * 2, 1)  # Try each key up to 2 times
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Check rate limit before making request
                self._check_rate_limit()
                self._record_request()
                
                job_desc = str(job.description) if job.description is not None else "No description available"

                profile_json = json.dumps(CANDIDATE_PROFILE, ensure_ascii=False, indent=2)

                content = self.client.chat.completions.create(
                    model=self.model,
                    response_model=CVContent,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a CV optimization engine. Your task is to generate CUSTOMIZED content "
                                "for a specific job application.\n\n"
                                "CRITICAL RULES:\n"
                                "1. NEVER fabricate skills, experience, or education. ONLY use data from the candidate profile.\n"
                                "2. REORDER skills: put the most relevant ones for THIS job first.\n"
                                "3. REORDER experience: put the most relevant job first.\n"
                                "4. Write a CUSTOM objective paragraph in SPANISH that maps the candidate's REAL skills "
                                "to THIS specific job's requirements. 2-3 sentences.\n"
                                "5. For experience_emphasis, indicate which ASPECTS of each role are most relevant "
                                "to THIS job (the CV generator will use this to potentially highlight those aspects).\n\n"
                                "SKILL CATEGORIES (flat list for reordering):\n"
                                "- Backend Core: Python (Asyncio), FastAPI, Flask, PostgreSQL, SQL, Bash\n"
                                "- Frontend: React 19, TypeScript, JavaScript (ES6+), MUI, TanStack Query, HTML, CSS, Vite\n"
                                "- Mobile: Flutter\n"
                                "- Firebase/BaaS: Firebase (Auth, Firestore, Storage, Functions), Cloudinary\n"
                                "- AI/IA: OpenAI API, LangChain, Playwright\n"
                                "- DevOps: Docker, Docker Compose, Git, GitHub Actions, Linux (SysAdmin), Nginx, Cloudflare, VPS\n"
                                "- Data Viz: Leaflet, Recharts\n"
                                "- Other: Astro, Mercado Pago, i18n, SEO, XPath\n"
                                "- Systems/C: C, Tesseract OCR, libcurl, libarchive, Linux CLI\n"
                                "- Testing: pytest, Debugging\n"
                                "- Languages: Español (Nativo), Inglés Técnico\n\n"
                                "EXPERIENCE INDICES:\n"
                                "0 = Beemore / Appi.ar (React 19, Firebase, MUI, TanStack Query, Leaflet, Flutter, offline-first)\n"
                                "1 = Bicicletería Amigorena (Bot WhatsApp Python, Playwright, +5000 msgs/mes, 94.7% éxito)\n"
                                "2 = BlackFire E-Commerce (FastAPI, React, Mercado Pago, Docker, PostgreSQL)\n"
                                "3 = Cliente US Fintech (Python scrapers, concurrent processing, dashboards)\n"
                                "4 = Beemore Landing (Astro, TypeScript, i18n, SEO multi-idioma)\n"
                                "5 = MozoPlus (FastAPI, WebSockets, PostgreSQL, Flutter, tiempo real)\n"
                                "6 = Coaching Emocional (Landing page, VPS Linux, Nginx, Cloudflare)\n\n"
                                "The skills_order should be a flat list of individual skills (not categories), "
                                "ordered from most to least relevant for THIS job."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"CANDIDATE PROFILE:\n{profile_json}\n\n"
                                f"JOB DATA:\n"
                                f"Title: {job.title}\n"
                                f"Company: {job.company}\n"
                                f"Location: {job.location}\n"
                                f"Description: {job_desc[:3000]}\n\n"
                                f"PREVIOUS AUDIT:\n"
                                f"Recommended profile: {audit.recommended_profile}\n"
                                f"Key requirements: {', '.join(audit.key_requirements)}\n"
                                f"Missing skills: {', '.join(audit.missing_skills)}\n\n"
                                f"Generate the customized CV content for this specific job."
                            ),
                        },
                    ]
                )
                return content
            except Exception as e:
                last_error = e
                logging.getLogger(__name__).warning(f"Groq key #{self._key_index + 1} failed on CV generation: {e}")
                if attempt < max_retries - 1:
                    self._rotate_key()
        
        # Fallback: return sensible defaults based on profile type
        profile = audit.recommended_profile
        if profile == "backend_ai":
            default_skills = ["Python (Asyncio)", "FastAPI", "PostgreSQL", "OpenAI API", "FastAPI", "Docker", "SQL", "Git"]
        elif profile == "frontend":
            default_skills = ["React 19", "TypeScript", "MUI", "Firebase", "JavaScript (ES6+)", "HTML", "CSS", "Flutter"]
        else:
            default_skills = ["Python (Asyncio)", "FastAPI", "PostgreSQL", "SQL", "Bash", "Docker", "Git", "Linux (SysAdmin)"]

        return CVContent(
            objetivo=f"Desarrollador con experiencia en {', '.join(audit.key_requirements[:3]) if audit.key_requirements else 'desarrollo de software'}. "
                     f"Orientado a la construcción de soluciones robustas y escalables.",
            skills_order=default_skills,
            experience_order=[0, 2, 1] if profile in ("backend", "backend_ai") else [1, 0, 2],
            experience_emphasis={
                0: "FastAPI, PostgreSQL, WebSockets, OpenAI API",
                1: "React, Firebase, TypeScript, MUI",
                2: "Python, scrapers, procesamiento concurrente",
            },
        )

    def extract_company_email(self, job: Job) -> str | None:
        """
        Try to extract a company email from the job description.
        Uses regex first (fast), then Groq as fallback for ambiguous cases.
        """
        import re
        job_desc = str(job.description) if job.description else ""
        
        # Quick regex extraction first
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        emails = re.findall(email_pattern, job_desc)
        
        # Filter out generic/personal emails
        skip_domains = {'example.com', 'gmail.com', 'yahoo.com', 'hotmail.com', 
                       'outlook.com', 'mail.com', 'protonmail.com'}
        skip_patterns = ['noreply', 'no-reply', 'donotreply', 'mailer-daemon']
        
        for email in emails:
            domain = email.split('@')[1].lower()
            local = email.split('@')[0].lower()
            if domain not in skip_domains and not any(p in local for p in skip_patterns):
                return email
        
        return None


# Singleton instance
ai_service = AIService()
