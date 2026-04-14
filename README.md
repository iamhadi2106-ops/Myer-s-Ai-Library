# Myer's College Digital Library Portal

A Django-based digital library platform for managing college books, searching records, and interacting with an AI assistant.

## Quick Start (Windows)

1. Run `Setup_Library.bat` to create the environment and install dependencies.
2. Configure your Groq key:
   - either in `.env` as `GROQ_API_KEY=...`
   - or in the Admin Panel > AI Configuration page
3. Run `Start_Library.bat` to launch the app.
4. Open `http://127.0.0.1:8000/login/`.

## Core Features

- **Library Dashboard**
  - Clean, formal interface with light/dark mode.
  - Real-time filtering, title sorting, and collection stats.
- **Book Management**
  - Add books by title and author from the Upload Resources page.
  - Remove books (teacher/admin).
- **Excel Catalog Sync**
  - Automatically imports records from `Library Books (Autosaved).xlsx`.
  - Attempts to map title/author/description/full text/external link columns.
  - Ignores malformed rows and avoids duplicate titles.
- **AI Assistant**
  - Text chat endpoint for collection-focused Q&A.
  - Voice input pipeline (speech-to-text + AI response + optional spoken reply).
- **Reader/Download Logic**
  - Backend supports local file download and optional external URL fallback.
- **Access Control**
  - Role-based permissions for student, teacher, and admin users.
  - Student suspension controls for staff users.

## Tech Stack

- Django 5
- SQLite (default)
- LangChain + FAISS + HuggingFace embeddings
- Groq API for LLM and speech transcription
- WhiteNoise for static file serving

## Project Structure (Key Paths)

- `library/` - app models, views, forms, routes, AI integration
- `myers_college/` - project settings and root URLs
- `templates/` - HTML templates and UI pages
- `media/` - uploaded/generated media
- `data/faiss_index/` - local vector index

## Deployment (Render - Free Tier)

Use a **Web Service** with:

- **Build command**
  - `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
- **Start command**
  - `gunicorn myers_college.wsgi:application`

Set environment variables:

- `SECRET_KEY` = strong random value
- `DEBUG` = `False`
- `ALLOWED_HOSTS` = `.onrender.com`
- `CSRF_TRUSTED_ORIGINS` = `https://<your-service>.onrender.com`
- `GROQ_API_KEY` = your Groq key

## Notes

- Free hosting tiers may sleep after inactivity (cold start on first request).
- `favicon.ico` 404 in local development is harmless unless you add a favicon.
- For CSRF issues in local browsers, clear site cookies for `localhost`/`127.0.0.1` and retry.

---
Developed for Myer's College  
© 2026 Myer's College Digital Infrastructure
