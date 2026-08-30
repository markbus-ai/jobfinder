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
Desarrollador Frontend especializado en React 19, TypeScript y ecosistema Firebase. Construyo interfaces en producción que son rápidas, responsivas y mantenibles. Me obsesiona la experiencia de usuario, el rendimiento y el código limpio. Busco un equipo de producto donde pueda aportar desde el frontend para crear soluciones que la gente realmente use.
]

#sectionsep

#section("Experiencia")

#job(
  position: "Desarrollador Frontend & Full Stack | Consultor Freelance",
  institution: [Múltiples Clientes y Agencias],
  location: "Remoto / Mar del Plata, ARG",
  date: "2024 - Actualidad",
  description: [
    - *Beemore (Appi.ar):* Desarrollo frontend completo de AppiarWeb — plataforma de gestión apícola en producción con React 19, TypeScript, MUI y Firebase (Auth, Firestore, Storage, Functions). Integración de Cloudinary para gestión multimedia, optimización de performance y diseño responsivo multi-dispositivo. Arquitectura offline-first para zonas sin conectividad estable.
    - *Sistema MozoPlus:* Desarrollo de interfaz web en tiempo real para sistema de gestión gastronómica de alta demanda. Visualización de datos en vivo mediante WebSockets, con foco en usabilidad y experiencia de usuario en entornos de ritmo rápido.
    - *Bicicletería Amigorena:* Diseño de frontend para sistema de atención automatizada 24/7. Interfaz limpia para monitoreo de +5,000 mensajes mensuales procesados (94.7% de éxito).
    - *Cliente US (Fintech):* Desarrollo de dashboards web para visualización de datos extraídos desde 6 plataformas. Reportes automatizados y monitoreo en tiempo real.
    - *Coaching Emocional:* Diseño y desarrollo de landing page optimizada para conversión. Implementación responsiva, despliegue en VPS Linux y optimización de velocidad de carga.
  ],
)

#sectionsep

#section("Habilidades")

#oneline-title-item(
  title: "Frontend & Desarrollo Web",
  content: [React 19, TypeScript, JavaScript (ES6+), HTML, CSS, MUI],
)

#oneline-title-item(
  title: "Backend & BaaS",
  content: [Firebase (Auth, Firestore, Storage, Functions), Cloudinary],
)

#oneline-title-item(
  title: "Diseño & UX/UI",
  content: [Figma, Diseño Responsivo, Optimización de Performance, UX Research],
)

#oneline-title-item(
  title: "Herramientas & Automatización",
  content: [Git, GitHub, WebSockets, Playwright, Linux],
)

#oneline-title-item(
  title: "Idiomas",
  content: [Español (Nativo), Inglés: Avanzado (técnico, documentación y código)],
)

#sectionsep

#section("Proyecto Open Source")

#job(
  position: "Creador de WhatsPlay",
  institution: [#link("https://github.com/markbus-ai/WhatsPlay")[GitHub / Proyecto Personal]],
  location: "Remoto",
  date: "2025",
  description: [
    - Librería propia para automatización de WhatsApp Web basada en Playwright y Python.
    - Automatización de interacciones web con manejo asincrónico y persistencia de sesión.
    - Arquitectura resiliente a cambios de UI con selección dinámica de elementos.
  ],
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

#set document(author: "Marcos Bustos", title: "CV Web Marcos Bustos 2026")
