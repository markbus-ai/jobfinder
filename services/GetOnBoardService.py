import json
import logging
from typing import List, Optional
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from models.JobModels import Job


class GetOnBoardService:
    """
    Service for fetching jobs from GetOnBoard (LATAM's largest tech job platform).
    Uses the public API — no authentication required.
    Docs: https://www.getonbrd.com/api/v0/
    """

    BASE_URL = "https://www.getonbrd.com/api/v0"
    SANDBOX_URL = "https://sandbox.getonbrd.dev/api/v0"

    def __init__(self, per_page: int = 50, use_sandbox: bool = False):
        self.logger = logging.getLogger(__name__)
        self.base_url = self.SANDBOX_URL if use_sandbox else self.BASE_URL
        self.per_page = per_page
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "JobFinder/1.0",
        })

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def _fetch_page(self, params: dict) -> dict:
        """Fetch a single page from the GetOnBoard search API with retry logic."""
        url = f"{self.base_url}/search/jobs"
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def _parse_job(self, raw: dict) -> Optional[Job]:
        """Map a single GetOnBoard job entry to our internal Job model."""
        try:
            attrs = raw.get("attributes", {})
            job_id = str(raw.get("id", ""))
            title = attrs.get("title", "Untitled")

            # Build the URL from the job ID and title slug
            # GetOnBoard URLs follow: https://www.getonbrd.com/jobs/{department}/{title_slug}-{id}
            # Since the API doesn't return the full URL, use a canonical link
            url = f"https://www.getonbrd.com/job/{job_id}"

            company_obj = attrs.get("company", {}) or {}
            company = company_obj.get("name", "Company Not Specified")

            location_parts = []
            countries = attrs.get("countries", [])
            if countries:
                location_parts.extend(countries)
            if attrs.get("city"):
                location_parts.append(attrs["city"])
            location = ", ".join(location_parts) if location_parts else "Remote"

            description = attrs.get("description", "No description available")

            # Salary info
            salary = None
            min_sal = attrs.get("min_salary")
            max_sal = attrs.get("max_salary")
            currency = attrs.get("currency", "")
            if min_sal and max_sal:
                salary = f"{currency} {min_sal} - {max_sal}"
            elif min_sal:
                salary = f"{currency} {min_sal}+"
            elif max_sal:
                salary = f"Up to {currency} {max_sal}"

            # Remote flag
            is_remote = bool(attrs.get("remote", False))

            # Seniority
            seniority = attrs.get("seniority", None)

            # Modality
            modality = attrs.get("modality", None)

            # Skill tags
            tags = attrs.get("tags", []) or []
            tags_str = json.dumps(tags) if tags else None

            job = Job(
                id=url,
                title=title,
                company=company,
                location=location,
                url=url,
                description=description,
                salary=salary,
                is_remote=is_remote,
                seniority=seniority,
                modality=modality,
                tags=tags_str,
                source_platform="getonboard",
            )
            return job

        except Exception as e:
            self.logger.warning(f"Failed to parse GetOnBoard job: {e}")
            return None

    def get_latest_jobs(
        self,
        term: str = "python developer",
        page: int = 1,
    ) -> List[Job]:
        """
        Search GetOnBoard for jobs matching a keyword.
        Returns a list of Job models mapped from the API response.
        """
        params = {
            "query": term,
            "page": page,
            "per_page": self.per_page,
        }

        try:
            data = self._fetch_page(params)
        except Exception as e:
            self.logger.error(f"Error fetching GetOnBoard jobs for '{term}': {e}")
            return []

        raw_jobs = data.get("data", [])
        if not raw_jobs:
            self.logger.info(f"No GetOnBoard jobs found for '{term}'.")
            return []

        jobs = []
        for raw in raw_jobs:
            job = self._parse_job(raw)
            if job:
                jobs.append(job)

        self.logger.info(f"GetOnBoard: found {len(jobs)} jobs for '{term}'.")
        return jobs
