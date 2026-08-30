import asyncio
import json
import logging
import time
from typing import Dict, Any

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
from sqlmodel import Session

from core.config import settings
from database import engine, create_db_and_tables
from models.JobModels import Job
from services.JobServices import JobService
from services.GetOnBoardService import GetOnBoardService
from services.GroqService import ai_service
from services.RedisServices import MemoryQueue
from services.CVGenerator import generate_cv, generate_custom_typst, classify_job
from services.EmailService import EmailService

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# In-memory store for jobs with emails (for button callbacks)
# Key: job_id, Value: dict with company, email, cv_path, profile
jobs_with_email: Dict[str, Dict[str, Any]] = {}


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
    search_terms = [t.strip() for t in settings.SEARCH_TERMS.split(",") if t.strip()]
    sources = [s.strip().lower() for s in settings.SEARCH_SOURCES.split(",") if s.strip()]

    logger.info("🔎 Starting job scraping...")

    all_jobs = []

    # --- GetOnBoard (LATAM public API, no auth needed) ---
    if settings.GETONBOARD_ENABLED and "getonboard" in sources:
        for term in search_terms:
            try:
                logger.info(f"🌎 Searching '{term}' on GetOnBoard...")
                gob_jobs = getonboard_service.get_latest_jobs(term=term)
                all_jobs.extend(gob_jobs)
            except Exception as e:
                logger.error(f"❌ Error searching '{term}' on GetOnBoard: {e}")
        time.sleep(2)

    # --- JobSpy: LinkedIn, Indeed, Google (per-country) ---
    jobspy_sources = [s for s in sources if s != "getonboard"]
    if jobspy_sources:
        search_locations = [
            {"loc": "Argentina", "country": "argentina"},
            {"loc": "Spain", "country": "spain"},
            {"loc": "Mexico", "country": "mexico"},
            {"loc": "Colombia", "country": "colombia"},
            {"loc": "Chile", "country": "chile"},
            {"loc": "Uruguay", "country": "uruguay"},
        ]

        for target in search_locations:
            for term in search_terms:
                try:
                    logger.info(f"🔎 Searching '{term}' in {target['loc']}...")
                    jobs = job_service.get_latest_jobs(
                        term=term,
                        location=target["loc"],
                        country=target["country"],
                        limit=15,
                    )
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.error(f"❌ Error searching in {target['loc']}: {e}")
            time.sleep(2)

    # Deduplicate by ID (URL)
    unique_jobs_map = {job.id: job for job in all_jobs}
    scraped_jobs = list(unique_jobs_map.values())

    logger.info(f"✅ Found {len(scraped_jobs)} unique candidates total.")

    notifications = []

    with Session(engine) as session:
        for job in scraped_jobs:
            # Skip if already exists (deduplication by URL)
            existing_job = session.get(Job, job.id)
            if existing_job:
                continue

            logger.info(f"🤖 Analyzing: {job.title} @ {job.company}")

            # AI analysis
            audit = ai_service.analyze_job(job, {})

            # Detailed logging
            logger.info(f"📊 Analysis for {job.company} - {job.title}:")
            logger.info(f"   🎯 Score: {audit.match_score}/100 | {'✅ Suitable' if audit.is_suitable else '❌ Not suitable'}")
            logger.info(f"   📝 Verdict: {audit.short_verdict}")
            logger.info(f"   👤 Profile: {audit.recommended_profile}")
            if audit.missing_skills:
                logger.info(f"   📉 Missing: {', '.join(audit.missing_skills)}")
            if audit.seniority_mismatch:
                logger.info(f"   ⚠️ Alert: Seniority mismatch")

            # Update model fields from audit
            job.ai_match_score = audit.match_score
            job.ai_summary = audit.short_verdict
            job.is_suitable = audit.is_suitable
            job.seniority_mismatch = audit.seniority_mismatch
            job.recommended_profile = audit.recommended_profile
            job.missing_skills = json.dumps(audit.missing_skills) if audit.missing_skills else "[]"

            # --- CV Generation for suitable jobs ---
            cv_generated = False
            cv_path = None
            company_email = None

            if (job.ai_match_score >= 70 or job.is_suitable):
                # 1. Generate customized CV content via Groq
                try:
                    cv_content = ai_service.generate_cv_content(job, audit)
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
            if (job.ai_match_score >= 70 or job.is_suitable) and not job.notified:
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

                notifications.append({
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
                    "recommended_profile": audit.recommended_profile,
                    "cv_generated": cv_generated,
                    "cv_path": cv_path,
                    "company_email": company_email,
                })

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

                        msg_text = (
                            f"🚀 <b>{suitability_icon} {job_data['match_score']}/100</b>\n\n"
                            f"🏢 <b>{job_data['company']}</b>\n"
                            f"💼 {job_data['title']}\n"
                            f"📍 {job_data['location']}\n\n"
                            f"📋 {profile_label}\n"
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
