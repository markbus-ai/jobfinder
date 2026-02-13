import instructor
from groq import Groq
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from core.config import settings
from models.JobModels import Job

class JobAudit(BaseModel):
    match_score: int = Field(description="Puntaje de 0 a 100 de compatibilidad técnica")
    is_suitable: bool = Field(description="Si el candidato debería aplicar basándose en datos duros")
    missing_skills: List[str] = Field(description="Tecnologías o requisitos que pide la oferta y el candidato no tiene")
    seniority_mismatch: bool = Field(description="True si la oferta pide mucha más experiencia de la que el perfil muestra")
    short_verdict: str = Field(description="Justificación técnica objetiva de máximo 15 palabras")

class AIService:
    def __init__(self, api_key: str = settings.GROQ_API_KEY, model: str = settings.GROQ_MODEL):
        self.client = instructor.from_groq(Groq(api_key=api_key), mode=instructor.Mode.JSON)
        self.model = model

    def analyze_job(self, job: Job, cv_data: Dict[str, Any]) -> JobAudit:
        """
        Analiza de forma objetiva una oferta contra un perfil (CV) proporcionado.
        """
        try:
            # Asegurar que sea string (pandas puede devolver float NaN)
            job_desc = str(job.description) if job.description is not None else "Sin descripción disponible"
            
            audit = self.client.chat.completions.create(
                model=self.model,
                response_model=JobAudit,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Actúa como un motor de auditoría técnica. Tu tarea es realizar un análisis de "
                            "compatibilidad estricto entre un perfil profesional (JSON) y una oferta laboral.\n\n"
                            "REGLAS DE EVALUACIÓN:\n"
                            "1. Basate únicamente en hechos presentes en los datos. Si una habilidad no está en el JSON, "
                            "asumí que el candidato no la posee.\n"
                            "2. El 'match_score' debe ser una métrica de superposición técnica (tech-stack overlap).\n"
                            "3. Identificá discrepancias de 'seniority' comparando los años de experiencia y nivel de "
                            "responsabilidad de los proyectos en el CV contra los requerimientos de la oferta.\n"
                            "4. Sé crítico con el lenguaje corporativo de las ofertas: extrae los requisitos técnicos "
                            "reales ocultos tras descripciones genéricas.\n"
                            "5. El veredicto debe ser una conclusión lógica, no una recomendación motivacional.\n"
                            "6. PRIORIDAD GEOGRÁFICA CRÍTICA: El candidato vive en 'Mar del Plata, Argentina'. Si la oferta es presencial o híbrida en esta ciudad, AUMENTA EL 'match_score' en +20 puntos y considera 'is_suitable' como True (salvo incompatibilidad técnica total), ya que estas ofertas son escasas y valiosas."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"DATOS DEL CANDIDATO (JSON):\n{cv_data}\n\n"
                            f"DATOS DE LA VACANTE:\nTítulo: {job.title}\nDescripción: {job_desc[:3000]}"
                        ),
                    },
                ]
            )
            return audit
        except Exception as e:
            return JobAudit(
                match_score=0,
                is_suitable=False,
                missing_skills=["Error en procesamiento de IA"],
                seniority_mismatch=False,
                short_verdict=f"Error técnico: {str(e)[:50]}"
            )

# Instancia genérica
ai_service = AIService()
