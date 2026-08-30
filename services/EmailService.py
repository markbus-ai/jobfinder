"""
Email Service for sending CVs to companies.

Extracted and refactored from ~/.config/cvs/enviar_cvs.py.
Loads SMTP configuration from config_smtp.json or environment variables.
"""

import json
import logging
import os
import smtplib
import ssl
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from core.config import settings

logger = logging.getLogger(__name__)

CVS_DIR = Path.home() / ".config" / "cvs"

# CV file mapping: cv_type -> PDF filename
CV_FILES = {
    "backend": "cv_marcos_bustos_backend.pdf",
    "frontend": "cv_marcos_bustos_frontend.pdf",
    "backend_ai": "cv_back_ia.pdf",
}

# Stack descriptions for email body
STACK_DESCRIPTIONS = {
    "backend": "Python, PostgreSQL, APIs REST, Docker y cloud",
    "frontend": "React, TypeScript, maquetado responsive, Figma y UX/UI",
    "backend_ai": "Python, IA/LLMs, APIs REST, PostgreSQL, Docker y cloud",
}


class EmailService:
    """Service for sending CV emails to companies via Gmail SMTP."""

    def __init__(self):
        self.sender_email = settings.SENDER_EMAIL
        self.sender_name = settings.SENDER_NAME
        self.smtp_password = settings.SMTP_PASSWORD
        self.smtp_server = settings.SMTP_SERVER
        self.smtp_port = settings.SMTP_PORT

    def _build_message(
        self, company_name: str, company_email: str, cv_type: str, cv_pdf_path: str
    ) -> Optional[MIMEMultipart]:
        """Build the email MIME message with CV attachment."""
        if not cv_pdf_path or not Path(cv_pdf_path).exists():
            logger.error(f"CV PDF not found: {cv_pdf_path}")
            return None

        area = cv_type.replace("_", " ").title()
        stack = STACK_DESCRIPTIONS.get(cv_type, "desarrollo de software")

        msg = MIMEMultipart()
        msg["From"] = f"{self.sender_name} <{self.sender_email}>"
        msg["To"] = company_email
        msg["Subject"] = f"Postulación espontánea - Desarrollador {area}"

        body = (
            f"Hola, equipo de {company_name}.\n\n"
            f"Me presento: soy {self.sender_name}, desarrollador de Mar del Plata "
            f"especializado en {stack}.\n\n"
            f"Les escribo para ofrecer mi disponibilidad laboral y contarles que "
            f"estoy en búsqueda activa de nuevos desafíos. Adjunto mi CV para "
            f"que puedan evaluar mi perfil.\n\n"
            f"Quedo atento a cualquier posibilidad de colaborar con su equipo.\n\n"
            f"Saludos cordiales.\n"
            f"{self.sender_name}\n"
            f"{self.sender_email}"
        )
        msg.attach(MIMEText(body, "plain"))

        # Attach CV PDF
        with open(cv_pdf_path, "rb") as f:
            attachment = MIMEApplication(f.read(), _subtype="pdf")
            filename = Path(cv_pdf_path).name
            attachment.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(attachment)

        return msg

    def send_cv(
        self,
        company_email: str,
        company_name: str,
        cv_type: str,
        cv_pdf_path: str,
    ) -> bool:
        """
        Send a CV email to a company.

        Args:
            company_email: Recipient email address
            company_name: Company name (for the email body)
            cv_type: One of "backend", "frontend", "backend_ai"
            cv_pdf_path: Path to the PDF file to attach

        Returns:
            True if sent successfully, False otherwise
        """
        if not company_email:
            logger.info(f"No email for {company_name}, skipping")
            return False

        if not self.sender_email or not self.smtp_password:
            logger.warning("SMTP credentials not configured. Cannot send emails.")
            return False

        msg = self._build_message(company_name, company_email, cv_type, cv_pdf_path)
        if not msg:
            return False

        context = ssl.create_default_context()

        try:
            with smtplib.SMTP_SSL(
                self.smtp_server, self.smtp_port, context=context, timeout=60
            ) as server:
                server.login(self.sender_email, self.smtp_password)
                server.sendmail(self.sender_email, company_email, msg.as_string())

            logger.info(f"Email sent to {company_name} <{company_email}>")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP authentication failed. Check credentials.")
            return False
        except Exception as e:
            logger.error(f"Failed to send email to {company_name}: {e}")
            return False


def load_smtp_config() -> dict:
    """Load SMTP config from config_smtp.json or environment variables."""
    config_path = CVS_DIR / "config_smtp.json"
    config = {}

    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load SMTP config from {config_path}: {e}")

    return {
        "sender_email": config.get("sender_email") or os.environ.get("SENDER_EMAIL", ""),
        "sender_name": config.get("sender_name") or os.environ.get("SENDER_NAME", "Marcos Bustos"),
        "smtp_password": config.get("smtp_password") or os.environ.get("SMTP_PASSWORD", ""),
        "smtp_server": config.get("smtp_server") or os.environ.get("SMTP_SERVER", "smtp.gmail.com"),
        "smtp_port": int(config.get("smtp_port", 465) or os.environ.get("SMTP_PORT", "465")),
    }
