import asyncio
import json
import logging
import time

from telegram import Bot
from telegram.constants import ParseMode
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


def process_jobs_sync(job_service: JobService, getonboard_service: GetOnBoardService, email_service: EmailService):
    """
    Synchronous function that:
    1. Scrapes jobs from multiple sources (GetOnBoard, LinkedIn, Indeed, Google)
    2. Deduplicates by URL
    3. Analyzes each with AI (Groq/Llama3)
    4. Generates CV if suitable
    5. Tries to send email if company email available
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
            {"loc": "Peru", "country": "peru"},
            {"loc": "Ecuador", "country": "ecuador"},
            {"loc": "Venezuela", "country": "venezuela"},
            {"loc": "Guatemala", "country": "guatemala"},
            {"loc": "Cuba", "country": "cuba"},
            {"loc": "Bolivia", "country": "bolivia"},
            {"loc": "Dominican Republic", "country": "dominican republic"},
            {"loc": "Honduras", "country": "honduras"},
            {"loc": "Paraguay", "country": "paraguay"},
            {"loc": "El Salvador", "country": "el salvador"},
            {"loc": "Nicaragua", "country": "nicaragua"},
            {"loc": "Costa Rica", "country": "costa rica"},
            {"loc": "Panama", "country": "panama"},
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

            # --- CV Generation + Email for suitable jobs ---
            cv_generated = False
            cv_path = None
            email_sent = False

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

                # 2. Try to send email (most job listings don't have company email)
                # Note: email is only sent if the company email is explicitly available
                # In practice, most scraped job listings don't include company email
                # so this will typically be skipped
                company_email = None  # Scraped listings rarely have email
                if company_email and cv_path:
                    email_sent = email_service.send_cv(
                        company_email=company_email,
                        company_name=job.company,
                        cv_type=audit.recommended_profile,
                        cv_pdf_path=cv_path,
                    )
                    job.email_sent = email_sent

            # --- Notification ---
            if (job.ai_match_score >= 70 or job.is_suitable) and not job.notified:
                # Mark as notified first
                job.notified = True

                notifications.append({
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
                    "email_sent": email_sent,
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
                        seniority_alert = "\n⚠️ <b>Alert:</b> Possible seniority mismatch" if job_data['seniority_mismatch'] else ""
                        suitability_icon = "✅" if job_data['is_suitable'] else "⚖️"

                        # Profile label
                        profile_labels = {
                            "backend": "🔧 Backend",
                            "frontend": "🎨 Frontend",
                            "backend_ai": "🤖 Backend + AI",
                        }
                        profile_label = profile_labels.get(job_data['recommended_profile'], job_data['recommended_profile'])

                        # CV + Email status
                        cv_status = f"📄 CV: Generado ✓ → <code>{job_data['cv_path']}</code>" if job_data['cv_generated'] else "📄 CV: Error ✗"
                        email_status = (
                            "📧 Email: Enviado ✓" if job_data['email_sent']
                            else "📧 Email: Sin email"
                        )

                        msg_text = (
                            f"🚀 <b>{suitability_icon} Job Opportunity Found</b>\n\n"
                            f"🏢 <b>Company:</b> {job_data['company']}\n"
                            f"💼 <b>Position:</b> {job_data['title']}\n"
                            f"📍 <b>Location:</b> {job_data['location']}\n\n"
                            f"🎯 <b>Match:</b> <code>{job_data['match_score']}/100</code>\n"
                            f"📋 <b>Perfil:</b> {profile_label}\n"
                            f"📉 <b>Missing Skills:</b> <i>{skills_text}</i>"
                            f"{seniority_alert}\n\n"
                            f"📝 <b>AI Verdict:</b>\n{job_data['summary']}\n\n"
                            f"{cv_status}\n"
                            f"{email_status}\n\n"
                            f"<a href='{job_data['url']}'>🔗 View Job Posting</a>"
                        )
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
                if chat_id and text:
                    await bot.send_message(
                        chat_id=chat_id, text=text, parse_mode=ParseMode.HTML
                    )
                    logger.info(f"✅ Message sent to {chat_id}")
        except Exception as e:
            logger.error(f"❌ Error in telegram_worker: {e}")
            await asyncio.sleep(5)


async def main():
    print(f"🚀 Starting {settings.PROJECT_NAME} Orchestrator (Redis-Free)...")

    # 1. Initialize DB
    create_db_and_tables()
    print("💾 Database initialized.")

    # 2. Initialize shared in-memory queue
    shared_queue = MemoryQueue()

    # 3. Start concurrent tasks
    await asyncio.gather(
        telegram_worker(shared_queue),
        scraper_scheduler(shared_queue)
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Shutting down orchestrator...")
