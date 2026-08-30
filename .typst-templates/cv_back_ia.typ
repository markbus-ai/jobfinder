#import "@preview/silver-dev-cv:1.0.2": *

#show: cv.with(
  font-type: "PT Serif",
  continue-header: "false",
  name: "Marcos Bustos",
  address: "Mar del Plata, Buenos Aires, Argentina",
  lastupdated: "false",
  pagecount: "false",
  contacts: (
    (text: "LinkedIn", link: "https://www.linkedin.com/in/marcos-bustos-7327962ab/"),
    (text: "GitHub", link: "https://github.com/markbus-ai"),
    (text: "marcosbustos.dev@gmail.com", link: "mailto:marcosbustos.dev@gmail.com"),
  ),
)

#section[Objetivo Profesional]
#descript[
Desarrollador Backend especializado en Python (FastAPI/Flask) y arquitecturas asincrónicas. Orientado al diseño de APIs escalables, despliegue en entornos cloud (GCP: Firestore, Storage) e integración con APIs de IA generativa (OpenAI). Busco integrarme a un equipo de producto para aportar en la construcción de servicios robustos, optimizados y de alta disponibilidad.
]

#sectionsep

#section("Experiencia")

#job(
  position: "Full-Stack Developer & Tech Lead",
  institution: [Código del Mar],
  location: "Mar del Plata, ARG",
  date: "Enero 2025 - Actualidad",
  description: [
    - Liderazgo técnico y desarrollo B2B, coordinando sprints, peer code reviews y flujos colaborativos mediante Git en un equipo de 3 desarrolladores.
    - *MozoPlus:* Diseño y desarrollo full-stack de sistema de gestión gastronómica. Backend asincrónico con FastAPI, PostgreSQL y sincronización en tiempo real vía WebSockets para alta demanda concurrente.
    - *Bicicletería Amigorena:* Implementación de bot automatizado asincrónico (Python) con atención 24/7, procesando +5,000 mensajes mensuales. Integración con API de OpenAI para clasificación de consultas y mejora del flujo conversacional.
  ],
)

#job(
  position: "Desarrollador Full-Stack",
  institution: [Beemore],
  location: "Remoto / Mar del Plata, ARG",
  date: "Enero 2025 - Actualidad",
  description: [
    - Desarrollo core de Appi.ar, plataforma de gestión apícola en producción B2B utilizando React 19, TypeScript y ecosistema GCP / Firebase (Auth, Firestore, Cloud Storage, Cloud Functions) junto con MUI.
    - Diseño e implementación de arquitectura offline-first, garantizando la operatividad del sistema en zonas rurales sin conectividad estable. Desarrollo de la versión mobile con Flutter.
    - Refactorización de base de código legacy, optimización general de performance e integración con Cloudinary para el manejo eficiente de assets multimedia.
  ],
)

#job(
  position: "Desarrollador Backend (Contractor)",
  institution: [Cliente US (Fintech)],
  location: "Remoto",
  date: "Enero 2024 - Diciembre 2025",
  description: [
    - Desarrollo e implementación de web scrapers asincrónicos utilizando Python para extracción automatizada de datos a escala.
    - Procesamiento concurrente de +39 productos extrayendo información vital desde 6 plataformas distintas en simultáneo.
    - Generación de reportes automatizados y construcción de dashboards para monitoreo de datos y toma de decisiones.
  ],
)

#sectionsep

#section("Proyectos Open Source")

#job(
  position: "Creador y Mantenedor: WhatsPlay",
  institution: [#link("https://github.com/markbus-ai/WhatsPlay")[GitHub / Proyecto Open Source]],
  location: "Remoto",
  date: "Enero 2025 - Actualidad",
  description: [
    - Desarrollo de librería propia para automatización de WhatsApp Web basada en Playwright y Python.
    - Implementación de manejo asincrónico y persistencia de sesión 24/7 optimizada para servidores Linux.
    - Diseño de un sistema de selectores dinámicos basado en XPath, garantizando alta resiliencia ante cambios en la UI de la plataforma.
  ],
)

#sectionsep

#section("Habilidades")

#oneline-title-item(
  title: "Core Backend & Cloud",
  content: [Python (Asyncio), FastAPI, Flask, PostgreSQL, GCP (Firestore, Storage), SQL, Bash],
)

#oneline-title-item(
  title: "Frontend & Mobile",
  content: [TypeScript, React 19, MUI, Flutter, JavaScript],
)

#oneline-title-item(
  title: "IA & Automatización",
  content: [OpenAI API, LangChain, Playwright, WhatsPlay, WebSockets, Git, Docker],
)

#oneline-title-item(
  title: "Testing & CI/CD",
  content: [pytest, GitHub Actions, Integración Continua, Debugging],
)

#oneline-title-item(
  title: "Infraestructura",
  content: [Linux (SysAdmin), Cloudflare, VPS, Nginx],
)

#oneline-title-item(
  title: "Idiomas",
  content: [Español (Nativo), Inglés: Técnico (Lectura y Documentación fluida)],
)

#sectionsep

#section("Educación")

#education(
  institution: [ISFT 204],
  major: [Tecnicatura Superior en Desarrollo de Software],
  date: [2024 -- En curso],
  location: "Mar del Plata, ARG",
)

#education(
  institution: [CFP 403],
  major: [Especialización en Programación Backend, Bases de Datos y Testing],
  date: [2023 -- 2026],
  location: "Mar del Plata, ARG",
)

#set document(author: "Marcos Bustos", title: "CV Marcos Bustos 2026")
