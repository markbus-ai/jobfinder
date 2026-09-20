import logging
from typing import List
from jobspy import scrape_jobs
from tenacity import retry, stop_after_attempt, wait_exponential
from models.JobModels import Job


class JobService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def _scrape_safe(self, **kwargs):
        """
        Run scrape_jobs with automatic retries on failures (rate limits, network errors).
        Exponential backoff: waits 4s, 8s, 10s... between attempts.
        """
        return scrape_jobs(**kwargs)

    def get_latest_jobs(
        self, 
        term: str = "python developer", 
        location: str = "Argentina",
        country: str = "argentina",
        limit: int = 15,
        is_remote: bool = False,
    ) -> List[Job]:
        """
        Consume JobSpy and map the results to our SQLModel Job model.
        """
        try:
            # Llamada a la librería JobSpy (envuelta en retry)
            # country_indeed drives the Indeed domain and the indeed-co header.
            # The old country_relevant kwarg was silently swallowed by jobspy.
            jobs_df = self._scrape_safe(
                site_name=["linkedin", "google", "indeed"],
                search_term=term,
                location=location,
                results_wanted=limit,
                hours_old=24,
                country_indeed=country,
                is_remote=is_remote,
                description_format="markdown",
            )
            if jobs_df is None or jobs_df.empty:
                self.logger.info(f"No se encontraron ofertas en {location}.")
                return []

            internal_jobs = []
            for _, row in jobs_df.iterrows():
                # El ID es la URL limpia
                job_url = str(row.get("job_url", ""))
                clean_url = job_url.split("?")[0] if job_url else None

                if not clean_url:
                    continue

                # Map exact fields to JobModels.Job
                job = Job(
                    id=clean_url,
                    title=str(row.get("title", "Sin Título")),
                    company=str(row.get("company", "Empresa No Especificada")),
                    location=str(row.get("location", location)),
                    url=clean_url,
                    description=row.get("description")
                    if row.get("description")
                    else "Sin descripción disponible",
                    salary=str(row.get("salary")) if row.get("salary") else None,
                    is_remote=bool(row.get("is_remote", False)),
                    source_platform=str(row.get("site", "jobspy")),
                )
                internal_jobs.append(job)

            return internal_jobs

        except Exception as e:
            self.logger.error(f"Error scraping {location}: {e}")
            return []

