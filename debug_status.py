import asyncio
from sqlmodel import Session, select, func
from database import engine
from models.JobModels import Job
from services.RedisServices import MemoryQueue

async def show_status():
    print("--- 📉 Ofertas con Score < 70 (Últimas 10) ---")
    with Session(engine) as session:
        # Consulta para scores bajos
        statement = select(Job).where(Job.ai_match_score < 70).order_by(Job.date_found.desc()).limit(10)
        results = session.exec(statement).all()
        
        if not results:
            print("   (No hay ofertas con score bajo aún)")
        
        for job in results:
            print(f"❌ [{job.ai_match_score}/100] {job.company} - {job.title}")
            print(f"   Veredicto: {job.ai_summary}")
            print(f"   URL: {job.url}\n")

        # Contar total
        count_stmt = select(func.count()).select_from(Job).where(Job.ai_match_score < 70)
        total_low = session.exec(count_stmt).one()
        print(f"📌 Total histórico de descartados (<70): {total_low}")

    print("\n--- ℹ️ Nota ---")
    print("Redis ha sido removido. El sistema ahora usa una cola interna en memoria.")

if __name__ == "__main__":
    asyncio.run(show_status())
