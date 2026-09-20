import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
from sqlmodel import Session

from core.config import settings
from database import engine, create_db_and_tables
from models.JobModels import Job
from services.JobServices import JobService
from services.GetOnBoardService import GetOnBoardService
from services.GroqService import ai_service, SCORING_PROFILE
from services.RedisServices import MemoryQueue
from services.CVGenerator import generate_cv, generate_custom_typst
from services.EmailService import EmailService
from services.LocationPolicy import classify_location, is_notifiable
from services.AnalysisRetry import (
    TransientAnalysisError,
    cap_analysis_attempts,
    retry_after_sleep,
    should_reanalyze,
)
from services.EnglishPolicy import (
    ENGLISH_LEVELS,
    english_allowed,
    is_notifiable_with_stored_english,
    normalize_level,
)
from services.SearchPlanner import build_scrape_plan, parse_csv, summarize_plan

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# In-memory store for jobs with emails (for button callbacks)
# Key: job_id, Value: dict with company, email, cv_path, profile
jobs_with_email: Dict[str, Dict[str, Any]] = {}

# Telegram display labels for the English level, keyed from the single-source
# vocabulary so a level can never be added without a label.
_ENGLISH_LEVEL_DISPLAY = ("No requerido", "Básico", "Intermedio", "Fluido")
ENGLISH_LEVEL_LABELS = dict(zip(ENGLISH_LEVELS, _ENGLISH_LEVEL_DISPLAY))


def _refresh_scraped_fields(target: Job, source: Job) -> Job:
    """
    Copy freshly scraped fields onto an existing persisted row (retry path).

    The row is re-analyzed in place because inserting a new object with the same
    primary key would violate the URL uniqueness constraint. Platform metadata
    is only overwritten when the new scrape actually provides it.
    """
    for field in ("title", "company", "location", "url", "description", "salary",
                  "is_remote", "source_platform"):
        setattr(target, field, getattr(source, field))
    for field in ("seniority", "modality", "tags"):
        value = getattr(source, field)
        if value is not None:
            setattr(target, field, value)
    return target


def _notification_payload(
    job: Job,
    *,
    cv_generated: bool,
    cv_path: Optional[str],
    company_email: Optional[str],
) -> Dict[str, Any]:
    """Build the message payload the Telegram worker consumes from a Job row."""
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "match_score": job.ai_match_score,
        "summary": job.ai_summary,
        "url": job.url,
        "missing_skills": json.loads(job.missing_skills) if job.missing_skills else [],
        "seniority_mismatch": job.seniority_mismatch,
        "is_suitable": job.is_suitable,
        "english_required": job.english_required,
        "recommended_profile": job.recommended_profile,
        "cv_generated": cv_generated,
        "cv_path": cv_path,
        "company_email": company_email,
    }


def _release_english_withheld(
    job: Job,
    session: Session,
    notifications: list[Dict[str, Any]],
) -> bool:
    """
    Notify a stored row that was withheld only by the English ceiling.

    This is deliberately TOKEN-FREE: it decides from persisted values and never
    calls the AI, so raising MAX_ENGLISH_LEVEL is retroactive at zero cost. Do
    not "optimize" it back into a re-analysis -- that would spend one Groq
    request per previously-withheld row, which is exactly what this path avoids.

    Returns True when the row was released.
    """
    if not is_notifiable_with_stored_english(
        location_eligible=job.location_eligible,
        match_score=job.ai_match_score,
        notified=job.notified,
        analysis_failed=job.analysis_failed,
        english_required=job.english_required,
        min_match_score=settings.MIN_MATCH_SCORE,
        max_english_level=settings.MAX_ENGLISH_LEVEL,
    ):
        return False

    job.notified = True
    notifications.append(
        _notification_payload(
            job,
            cv_generated=bool(job.cv_generated),
            cv_path=job.cv_path,
            company_email=None,
        )
    )
    session.add(job)
    session.commit()
    logger.info(
        f"Released previously withheld job {job.title} @ {job.company}: stored "
        f"English level '{job.english_required}' now fits "
        f"MAX_ENGLISH_LEVEL='{settings.MAX_ENGLISH_LEVEL}' (no AI call)."
    )
    return True


def process_jobs_sync(job_service: JobService, getonboard_service: GetOnBoardService, email_service: EmailService):
    """
    Synchronous function that:
    1. Scrapes jobs from multiple sources (GetOnBoard, LinkedIn, Indeed, Google)
    2. Deduplicates by URL
    3. Analyzes each with AI (Groq/Llama3)
    4. Generates CV if suitable
    5. Extracts company email from description
    6. Saves results to DB
    7. Returns list of notifications
    """
    search_terms = parse_csv(settings.SEARCH_TERMS)
    remote_terms = parse_csv(settings.SEARCH_TERMS_REMOTE)
    remote_locations = parse_csv(settings.REMOTE_SEARCH_LOCATIONS)
    sources = [s.strip().lower() for s in settings.SEARCH_SOURCES.split(",") if s.strip()]

    # JobSpy per-country targets. Each country token drives the Indeed domain.
    search_locations = [
        ("Argentina", "argentina"),
        ("Spain", "spain"),
        ("Mexico", "mexico"),
        ("Colombia", "colombia"),
        ("Chile", "chile"),
        ("Uruguay", "uruguay"),
    ]

    plan = build_scrape_plan(
        search_terms=search_terms,
        sources=sources,
        jobspy_locations=search_locations,
        getonboard_enabled=settings.GETONBOARD_ENABLED,
        remote_enabled=settings.REMOTE_SEARCH_ENABLED,
        remote_terms=remote_terms,
        remote_locations=remote_locations,
    )
    counts = summarize_plan(plan)
    logger.info(
        f"🔎 Starting job scraping: {counts['total']} searches this cycle "
        f"(getonboard={counts['getonboard']}, jobspy={counts['jobspy']}, remote={counts['remote']})."
    )

    all_jobs = []

    for index, search in enumerate(plan):
        try:
            if search.source == "getonboard":
                logger.info(f"🌎 Searching '{search.term}' on GetOnBoard...")
                all_jobs.extend(getonboard_service.get_latest_jobs(term=search.term))
            else:
                mode = "remote" if search.is_remote else "local"
                logger.info(f"🔎 Searching '{search.term}' in {search.location} ({mode})...")
                all_jobs.extend(
                    job_service.get_latest_jobs(
                        term=search.term,
                        location=search.location,
                        country=search.country,
                        limit=search.limit,
                        is_remote=search.is_remote,
                    )
                )
        except Exception as e:
            logger.error(f"❌ Error searching '{search.term}' in {search.location or 'getonboard'}: {e}")

        # Preserve the original pacing: brief pause between source/location groups.
        next_search = plan[index + 1] if index + 1 < len(plan) else None
        if next_search is not None and (
            next_search.source != search.source
            or (search.source == "jobspy" and next_search.location != search.location)
        ):
            time.sleep(2)

    # Deduplicate by ID (URL)
    unique_jobs_map = {job.id: job for job in all_jobs}
    scraped_jobs = list(unique_jobs_map.values())

    logger.info(f"✅ Found {len(scraped_jobs)} unique candidates total.")

    notifications = []

    # Config may lower the retry budget but never raise it past the hard cap.
    max_analysis_attempts = cap_analysis_attempts(settings.MAX_ANALYSIS_ATTEMPTS)

    with Session(engine) as session:
        for job in scraped_jobs:
            # Deduplicate by URL. A transiently failed row with attempts left is
            # re-analyzed in place; healthy or exhausted rows are skipped.
            existing_job = session.get(Job, job.id)
            if existing_job is not None:
                if not should_reanalyze(
                    existing_job.analysis_failed,
                    existing_job.analysis_attempts,
                    max_analysis_attempts,
                ):
                    # A stored row skipped by dedup may still be releasable if
                    # MAX_ENGLISH_LEVEL was raised after it was withheld. That
                    # check is token-free (stored values only), never a re-analysis.
                    _release_english_withheld(existing_job, session, notifications)
                    continue
                job = _refresh_scraped_fields(existing_job, job)

            # --- Location policy gate: runs BEFORE any AI call to save tokens ---
            verdict = classify_location(
                location=job.location,
                is_remote=bool(job.is_remote),
                modality=job.modality,
                title=job.title,
                description=job.description or "",
                candidate_city=settings.CANDIDATE_CITY,
                candidate_country=settings.CANDIDATE_COUNTRY,
                allow_remote=settings.ALLOW_REMOTE,
                block_foreign_restricted_remote=settings.BLOCK_FOREIGN_RESTRICTED_REMOTE,
            )
            job.work_mode = verdict.work_mode
            job.location_eligible = verdict.eligible
            job.location_reason = verdict.reason

            if not verdict.eligible:
                # Persisted for auditability, but it will never be notified and
                # never reaches the AI/CV/email pipeline.
                logger.info(
                    f"⛔ Ineligible location [{verdict.reason}] {job.title} @ {job.company} "
                    f"| location={job.location!r} | work_mode={verdict.work_mode}"
                )
                session.add(job)
                session.commit()
                continue

            logger.info(f"🤖 Analyzing: {job.title} @ {job.company}")

            # AI analysis (with rate limiting)
            try:
                audit = ai_service.analyze_job(job, SCORING_PROFILE)
            except TransientAnalysisError as e:
                # A rate limit / network blip must never be frozen as a 0/100.
                job.analysis_attempts = (job.analysis_attempts or 0) + 1
                job.analysis_failed = True
                if job.analysis_attempts >= max_analysis_attempts:
                    # Exhausted: persist a permanent 0 so it never loops forever.
                    job.ai_match_score = 0
                    job.ai_summary = f"Analysis failed after {job.analysis_attempts} attempts"
                    job.is_suitable = False
                    job.missing_skills = json.dumps(["Analysis failed: transient error"])
                logger.warning(
                    f"Transient AI failure for {job.title} @ {job.company} "
                    f"(attempt {job.analysis_attempts}/{max_analysis_attempts}, "
                    f"status={e.status_code or 'n/a'}, "
                    f"retry_after={e.retry_after if e.retry_after is not None else 'n/a'}); "
                    f"not notifying, retrying later."
                )
                session.add(job)
                session.commit()
                # Honor Retry-After so the next job in this cycle does not hammer
                # a rate-limited API. Capped by retry_after_sleep.
                time.sleep(retry_after_sleep(e.retry_after))
                continue

            # Small delay between API calls to respect rate limits
            time.sleep(0.5)

            # Detailed logging
            logger.info(f"📊 Analysis for {job.company} - {job.title}:")
            logger.info(f"   🎯 Score: {audit.match_score}/100 | {'✅ Suitable' if audit.is_suitable else '❌ Not suitable'}")
            logger.info(f"   📝 Verdict: {audit.short_verdict}")
            logger.info(f"   👤 Profile: {audit.recommended_profile}")
            if audit.missing_skills:
                logger.info(f"   📉 Missing: {', '.join(audit.missing_skills)}")
            if audit.seniority_mismatch:
                logger.info(f"   ⚠️ Alert: Seniority mismatch")
            logger.info(
                f"   🌍 AI location: mode={audit.work_mode} country={audit.job_country or 'n/a'} "
                f"city={audit.job_city or 'n/a'} residence_required={audit.requires_residence_in or 'none'}"
            )
            logger.info(
                f"   English: required={audit.english_required} "
                f"evidence={audit.english_evidence or 'n/a'}"
            )

            # Update model fields from audit
            job.ai_match_score = audit.match_score
            job.ai_summary = audit.short_verdict
            job.is_suitable = audit.is_suitable
            job.seniority_mismatch = audit.seniority_mismatch
            job.recommended_profile = audit.recommended_profile
            job.missing_skills = json.dumps(audit.missing_skills) if audit.missing_skills else "[]"
            job.english_required = audit.english_required
            job.english_evidence = audit.english_evidence
            job.analysis_failed = False

            # Notification gate: location + score + English ceiling. The English
            # level only exists after the AI call, so it is applied here and not
            # in the location gate (which runs before any AI call).
            notifiable = is_notifiable(
                job.location_eligible, job.ai_match_score, settings.MIN_MATCH_SCORE
            ) and english_allowed(job.english_required, settings.MAX_ENGLISH_LEVEL)
            if not notifiable and job.ai_match_score is not None and job.ai_match_score >= settings.MIN_MATCH_SCORE:
                if normalize_level(job.english_required) is None:
                    logger.info(
                        f"   Withheld: English level missing or outside the closed "
                        f"vocabulary (english_required={job.english_required!r}); failing closed."
                    )
                else:
                    logger.info(
                        f"   Withheld: English level '{job.english_required}' exceeds "
                        f"MAX_ENGLISH_LEVEL='{settings.MAX_ENGLISH_LEVEL}'."
                    )

            # --- CV Generation for suitable jobs ---
            cv_generated = False
            cv_path = None
            company_email = None

            if notifiable:
                # 1. Generate customized CV content via Groq
                try:
                    cv_content = ai_service.generate_cv_content(job, audit)
                    time.sleep(0.5)  # Rate limit delay
                    logger.info(f"   📝 CV content generated: objective={len(cv_content.objetivo)} chars, "
                              f"skills_order={len(cv_content.skills_order)} items, "
                              f"experience_order={cv_content.experience_order}")
                except Exception as e:
                    logger.error(f"Failed to generate CV content: {e}")
                    cv_content = None

                # 2. Generate custom Typst CV if content was generated
                if cv_content:
                    cv_path = generate_custom_typst(job, cv_content, audit.recommended_profile)
                    if cv_path:
                        cv_generated = True
                        job.cv_generated = True
                        job.cv_path = cv_path
                else:
                    # Fallback to static template if Groq content generation fails
                    cv_path = generate_cv(job, audit.recommended_profile)
                    if cv_path:
                        cv_generated = True
                        job.cv_generated = True
                        job.cv_path = cv_path

                # 3. Extract company email from job description
                company_email = ai_service.extract_company_email(job)
                if company_email:
                    logger.info(f"   📧 Email found: {company_email}")

            # --- Notification ---
            if notifiable and not job.notified:
                # Mark as notified first
                job.notified = True

                # Store job data for button callback
                if company_email and cv_path:
                    jobs_with_email[job.id] = {
                        "company": job.company,
                        "email": company_email,
                        "cv_path": cv_path,
                        "profile": audit.recommended_profile,
                    }

                notifications.append(
                    _notification_payload(
                        job,
                        cv_generated=cv_generated,
                        cv_path=cv_path,
                        company_email=company_email,
                    )
                )

            # Single commit per job — save all state at once
            session.add(job)
            session.commit()

    return notifications


async def scraper_scheduler(queue: MemoryQueue):
    """Infinite loop that runs scraping every N minutes."""
    loop = asyncio.get_running_loop()

    # Create services once outside the loop (not per cycle)
    job_service = JobService()
    getonboard_service = GetOnBoardService(per_page=settings.GETONBOARD_PER_PAGE)
    email_service = EmailService()

    while True:
        try:
            logger.info("⏳ Starting scraping cycle...")

            jobs_to_notify = await loop.run_in_executor(
                None, process_jobs_sync, job_service, getonboard_service, email_service
            )

            if jobs_to_notify:
                logger.info(f"📨 Enqueuing {len(jobs_to_notify)} notifications...")

                if settings.TELEGRAM_CHAT_ID:
                    for job_data in jobs_to_notify:
                        # Format missing skills
                        skills_text = ", ".join(job_data['missing_skills']) if job_data['missing_skills'] else "None detected"
                        seniority_alert = "\n⚠️ <b>Alert:</b> Seniority mismatch" if job_data['seniority_mismatch'] else ""
                        suitability_icon = "✅" if job_data['is_suitable'] else "⚖️"

                        # Profile label
                        profile_labels = {
                            "backend": "🔧 Backend",
                            "frontend": "🎨 Frontend",
                            "backend_ai": "🤖 Backend + AI",
                        }
                        profile_label = profile_labels.get(job_data['recommended_profile'], job_data['recommended_profile'])

                        # CV status
                        cv_status = f"📄 CV: ✓" if job_data['cv_generated'] else "📄 CV: ✗"

                        # Email status
                        company_email = job_data.get('company_email')
                        email_status = f"📧 {company_email}" if company_email else "📧 Sin email"

                        # English level required by the listing
                        english_level = ENGLISH_LEVEL_LABELS.get(
                            job_data.get('english_required'), job_data.get('english_required') or "n/a"
                        )

                        msg_text = (
                            f"🚀 <b>{suitability_icon} {job_data['match_score']}/100</b>\n\n"
                            f"🏢 <b>{job_data['company']}</b>\n"
                            f"💼 {job_data['title']}\n"
                            f"📍 {job_data['location']}\n\n"
                            f"📋 {profile_label}\n"
                            f"Inglés: {english_level}\n"
                            f"📉 Skills: <i>{skills_text}</i>"
                            f"{seniority_alert}\n\n"
                            f"📝 {job_data['summary']}\n\n"
                            f"{cv_status} | {email_status}\n\n"
                            f"<a href='{job_data['url']}'>🔗 Ver oferta</a>"
                        )

                        # Add "Auto-postular" button if email is available
                        if company_email and job_data['cv_generated']:
                            keyboard = [[
                                InlineKeyboardButton(
                                    text=f"📧 Auto-postular a {job_data['company']}",
                                    callback_data=f"apply:{job_data['id']}"
                                )
                            ]]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            await queue.enqueue(settings.TELEGRAM_CHAT_ID, msg_text, reply_markup=reply_markup)
                        else:
                            await queue.enqueue(settings.TELEGRAM_CHAT_ID, msg_text)
                else:
                    logger.warning("TELEGRAM_CHAT_ID not configured. No messages will be sent.")

            logger.info("💤 Cycle finished. Sleeping 5 minutes.")

        except Exception as e:
            logger.error(f"❌ Error in scraper_scheduler: {e}")

        await asyncio.sleep(300)


async def telegram_worker(queue: MemoryQueue):
    """Consumes messages from the in-memory queue and sends them to Telegram."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("⚠️ TELEGRAM_BOT_TOKEN not configured. Telegram worker paused.")
        return

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    logger.info("📡 Telegram worker started (Internal Queue)...")

    while True:
        try:
            msg_data = await queue.dequeue()
            if msg_data:
                chat_id = msg_data.get("chat_id")
                text = msg_data.get("text")
                reply_markup = msg_data.get("reply_markup")
                if chat_id and text:
                    await bot.send_message(
                        chat_id=chat_id, text=text, parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
                    logger.info(f"✅ Message sent to {chat_id}")
        except Exception as e:
            logger.error(f"❌ Error in telegram_worker: {e}")
            await asyncio.sleep(5)


async def handle_apply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Auto-postular' button clicks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("apply:"):
        return

    job_id = data.split(":", 1)[1]
    job_data = jobs_with_email.get(job_id)

    if not job_data:
        await query.edit_message_text(
            text=query.message.text + "\n\n❌ <b>Error:</b> Job data not found (maybe after restart)"
        )
        return

    # Show "sending..." status
    await query.edit_message_text(
        text=query.message.text + "\n\n⏳ <b>Enviando CV...</b>"
    )

    # Send CV via email
    email_service = EmailService()
    success = email_service.send_cv(
        company_email=job_data["email"],
        company_name=job_data["company"],
        cv_type=job_data["profile"],
        cv_pdf_path=job_data["cv_path"],
    )

    if success:
        await query.edit_message_text(
            text=query.message.text + "\n\n✅ <b>CV enviado!</b>"
        )
        logger.info(f"📧 CV sent to {job_data['company']} <{job_data['email']}>")
    else:
        await query.edit_message_text(
            text=query.message.text + "\n\n❌ <b>Error al enviar</b> — intenta manualmente"
        )
        logger.error(f"❌ Failed to send CV to {job_data['company']}")


async def main():
    print(f"🚀 Starting {settings.PROJECT_NAME} Orchestrator (Redis-Free)...")

    # 1. Initialize DB
    create_db_and_tables()
    print("💾 Database initialized.")

    # 2. Initialize shared in-memory queue
    shared_queue = MemoryQueue()

    # 3. Build Telegram application with callback handler
    if settings.TELEGRAM_BOT_TOKEN:
        app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CallbackQueryHandler(handle_apply_callback, pattern=r"^apply:"))

        # Start polling for callbacks in background
        async with app:
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)

            # 4. Start concurrent tasks
            await asyncio.gather(
                telegram_worker(shared_queue),
                scraper_scheduler(shared_queue)
            )
    else:
        # No Telegram token — just run scraper without bot
        await asyncio.gather(
            telegram_worker(shared_queue),
            scraper_scheduler(shared_queue)
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Shutting down orchestrator...")
