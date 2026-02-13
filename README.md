# 🕵️ JobFinder AI

Un orquestador inteligente que busca ofertas de trabajo en múltiples plataformas (LinkedIn, Indeed, Google Jobs), las analiza utilizando Inteligencia Artificial (Groq/Llama3) para determinar si coinciden con tu perfil, y te notifica vía Telegram.

## 🚀 Características

*   **Scraping Multi-plataforma:** Busca en LinkedIn, Indeed y Google Jobs.
*   **Filtrado Inteligente:** Usa `jobspy` para buscar y modelos LLM (vía Groq) para analizar la descripción de la oferta frente a tu CV.
*   **Soporte Regional:** Configurado para buscar en todos los países de habla hispana.
*   **Notificaciones:** Envía alertas a Telegram solo de las ofertas relevantes.
*   **Resiliencia:** Sistema de reintentos automáticos para evitar bloqueos y fallos de red.
*   **Persistencia:** Evita duplicados guardando el historial en SQLite.

## 🛠️ Requisitos Previo

*   Python 3.10+
*   Una API Key de [Groq](https://groq.com/) (Gratuita actualmente).
*   Un Bot de Telegram (Token y Chat ID) si quieres notificaciones.

## 📦 Instalación

1.  **Clonar el repositorio:**
    ```bash
    git clone https://github.com/tu-usuario/jobfinder.git
    cd jobfinder
    ```

2.  **Crear un entorno virtual:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # En Windows: venv\Scripts\activate
    ```

3.  **Instalar dependencias:**
    ```bash
    pip install -r requirements.txt
    ```

## ⚙️ Configuración

1.  **Variables de Entorno:**
    Copia el archivo de ejemplo y rellénalo con tus datos.
    ```bash
    cp .env.example .env
    ```
    Edita `.env` con tu `GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN`, etc.

2.  **Tu Perfil (CV):**
    El sistema necesita saber quién eres para filtrar las ofertas.
    Copia el ejemplo y edítalo con tus habilidades reales.
    ```bash
    cp cv.example.json cv.json
    ```
    *Nota: `cv.json` está ignorado por git para proteger tu privacidad.*

## ▶️ Uso

Ejecuta el script principal:

```bash
python main.py
```

El bot comenzará a:
1.  Buscar ofertas en Argentina, España, México, Colombia, etc.
2.  Analizarlas con IA.
3.  Enviarte un mensaje a Telegram si encuentra un "Match" (Puntuación > 70 o Apto).
4.  Dormir 5 minutos y repetir.

## 🛡️ Estructura del Proyecto

*   `main.py`: Punto de entrada y orquestador.
*   `services/`: Lógica de negocio (Scraping, IA, Telegram).
*   `models/`: Definiciones de base de datos (SQLModel).
*   `core/`: Configuraciones generales.
*   `cv.json`: Tu información personal (Local, no se sube).

## 📄 Licencia

Este proyecto está bajo la Licencia MIT.
