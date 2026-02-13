import asyncio
import json
import logging
import os
from datetime import datetime

from telegram import Bot
from telegram.constants import ParseMode
from sqlmodel import Session, select

from core.config import settings
from database import engine, create_db_and_tables
from models.JobModels import Job
from services.JobServices import JobService
from services.GroqService import ai_service
from services.RedisServices import MemoryQueue

# Configuración de Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Cargar datos del CV
try:
    with open("cv.json", "r") as f:
        CV_DATA = json.load(f)
except FileNotFoundError:
    logger.error("cv.json no encontrado. Usando diccionario vacío.")
    CV_DATA = {}

def process_jobs_sync():
    """
    Función síncrona que:
    1. Scrapea ofertas (bloqueante)
    2. Verifica duplicados en DB
    3. Analiza con IA (bloqueante)
    4. Guarda resultados
    5. Retorna lista de notificaciones
    """
    job_service = JobService()
    logger.info("🔎 Iniciando scraping de ofertas...")
    
    # Búsqueda en todos los países de habla hispana
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
    
    all_jobs = []
    for target in search_locations:
        try:
            logger.info(f"🔎 Buscando 'Python Developer' en {target['loc']}...")
            jobs = job_service.get_latest_jobs(
                term="Python Developer", 
                location=target["loc"], 
                country=target["country"],
                limit=15
            )
            all_jobs.extend(jobs)
        except Exception as e:
            logger.error(f"❌ Error buscando en {target['loc']}: {e}")

    # Deduplicar por ID (URL)
    unique_jobs_map = {job.id: job for job in all_jobs}
    scraped_jobs = list(unique_jobs_map.values())
    
    logger.info(f"✅ Se encontraron {len(scraped_jobs)} candidatos únicos totales en todos los países.")
    
    notifications = []
    
    with Session(engine) as session:
        for job in scraped_jobs:
            # Verificar si ya existe por ID (URL)
            existing_job = session.get(Job, job.id)
            if existing_job:
                continue

            logger.info(f"🤖 Analizando: {job.title} @ {job.company}")
            
            # Análisis de IA
            audit = ai_service.analyze_job(job, CV_DATA)

            # Logging detallado
            logger.info(f"📊 Análisis para {job.company} - {job.title}:")
            logger.info(f"   🎯 Score: {audit.match_score}/100 | {'✅ Apto' if audit.is_suitable else '❌ No apto'}")
            logger.info(f"   📝 Veredicto: {audit.short_verdict}")
            if audit.missing_skills:
                logger.info(f"   📉 Faltantes: {', '.join(audit.missing_skills)}")
            if audit.seniority_mismatch:
                logger.info(f"   ⚠️ Alerta: Discrepancia de Seniority")

            # Actualizar campos del modelo con el resultado de la auditoría
            job.ai_match_score = audit.match_score
            job.ai_summary = audit.short_verdict
            # job.is_junior removed as requested
            job.is_suitable = audit.is_suitable
            job.seniority_mismatch = audit.seniority_mismatch
            # Serializamos la lista de skills faltantes a JSON string
            job.missing_skills = json.dumps(audit.missing_skills) if audit.missing_skills else "[]"

            # Guardar en DB
            session.add(job)
            session.commit()
            session.refresh(job)

            # Criterio de Notificación: Score >= 70 OR marcado como suitable
            if (job.ai_match_score >= 70 or job.is_suitable) and not job.notified:
                notifications.append({
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "match_score": job.ai_match_score,
                    "summary": job.ai_summary,
                    "url": job.url,
                    "missing_skills": json.loads(job.missing_skills) if job.missing_skills else [],
                    "seniority_mismatch": job.seniority_mismatch,
                    "is_suitable": job.is_suitable
                })
                
                # Marcar como notificado
                job.notified = True
                session.add(job)
                session.commit()
    
    return notifications

async def scraper_scheduler(queue: MemoryQueue):
    """Loop infinito que ejecuta el scraping cada X tiempo."""
    loop = asyncio.get_running_loop()

    while True:
        try:
            logger.info("⏳ Ejecutando ciclo de scraping...")
            
            # Ejecutar la lógica síncrona en un thread pool para no bloquear el loop async
            jobs_to_notify = await loop.run_in_executor(None, process_jobs_sync)
            
            if jobs_to_notify:
                logger.info(f"📨 Encolando {len(jobs_to_notify)} notificaciones...")
                
                if settings.TELEGRAM_CHAT_ID:
                    for job_data in jobs_to_notify:
                        # Formatear skills faltantes
                        skills_text = ", ".join(job_data['missing_skills']) if job_data['missing_skills'] else "Ninguna detectada"
                        seniority_alert = "\n⚠️ <b>Alerta:</b> Posible discrepancia de seniority" if job_data['seniority_mismatch'] else ""
                        suitability_icon = "✅" if job_data['is_suitable'] else "⚖️"

                        msg_text = (
                            f"🚀 <b>{suitability_icon} Oportunidad Encontrada</b>\n\n"
                            f"🏢 <b>Empresa:</b> {job_data['company']}\n"
                            f"💼 <b>Puesto:</b> {job_data['title']}\n"
                            f"📍 <b>Ubicación:</b> {job_data['location']}\n\n"
                            f"🎯 <b>Match:</b> <code>{job_data['match_score']}/100</code>\n"
                            f"📉 <b>Skills Faltantes:</b> <i>{skills_text}</i>"
                            f"{seniority_alert}\n\n"
                            f"📝 <b>Veredicto IA:</b>\n{job_data['summary']}\n\n"
                            f"<a href='{job_data['url']}'>🔗 Ver Vacante en Portal</a>"
                        )
                        await queue.enqueue(settings.TELEGRAM_CHAT_ID, msg_text)
                else:
                    logger.warning("TELEGRAM_CHAT_ID no configurado. No se enviarán mensajes.")

            logger.info("💤 Ciclo finalizado. Durmiendo 5 minutos.")
            
        except Exception as e:
            logger.error(f"❌ Error en scraper_scheduler: {e}")
        
        # Esperar 5 minutos (300 segundos)
        await asyncio.sleep(300)

async def telegram_worker(queue: MemoryQueue):
    """Consume mensajes de la cola de memoria y los envía a Telegram."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("⚠️ TELEGRAM_BOT_TOKEN no configurado. Worker de Telegram pausado.")
        return

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    logger.info("📡 Worker de Telegram iniciado (Cola Interna)...")

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
                    logger.info(f"✅ Mensaje enviado a {chat_id}")
        except Exception as e:
            logger.error(f"❌ Error en telegram_worker: {e}")
            await asyncio.sleep(5)

async def main():
    print(f"🚀 Iniciando {settings.PROJECT_NAME} Orchestrator (Redis-Free)...")
    
    # 1. Inicializar DB
    create_db_and_tables()
    print("💾 Base de datos inicializada.")
    
    # 2. Inicializar Cola compartida en memoria
    shared_queue = MemoryQueue()
    
    # 3. Iniciar tareas concurrentes
    await asyncio.gather(
        telegram_worker(shared_queue),
        scraper_scheduler(shared_queue)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Apagando orquestador...")
