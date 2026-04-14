# 🏛️ Myer's College Digital Library Portal

Official Digital Archive and AI Research System for Myer's College.

## 🚀 Quick Launch (Windows)

1. **Setup**: Run `Setup_Library.bat`. This will create a secure environment and install all necessary academic library components.
2. **API Key**: Open the `.env` file and replace `your_api_key_here` with your **Groq API Key**.
3. **Start**: Double-click `Start_Library.bat` to launch the digital portal in your browser.

---

## 📖 System Features

### 1. 🏛️ Dashboard
A central hub for digital access. Provides a high-level overview of the Myer's College academic archive.

### 2. 📥 Resource Ingest
Allows faculty and authorized users to upload official course books and PDFs. The system automatically fragments and indexes these documents into the secure local archive for later retrieval.

### 3. 🔍 Global Research
A specialized tool for searching external academic databases. Useful for students conducting broad research beyond the immediate college collection.

### 4. 📖 Official AI Librarian
A custom AI assistant representing Myer's College. It is trained to provide academic summaries, literature analysis, and historical context of indexed works.

### 5. 💬 Direct Chat (Archive Q&A)
Powered by **RAG (Retrieval-Augmented Generation)**. Students can ask natural language questions directly to the uploaded college books. The AI will only answer based on the provided context, ensuring alignment with school curriculum.

---

## 🛠️ Technical Requirements

- **Python**: Version 3.10 or higher.
- **API Access**: A valid Groq API Key is required for the AI Librarian and Archive Chat functionalities.
- **Internet**: Required for initial setup and for the Global Research/AI services to communicate with Groq cloud nodes.

## 🔒 Data Security & Privacy

- **Local Storage**: All uploaded PDFs are stored locally in the `uploads/` directory.
- **Vector Database**: Document indexes are stored in the `data/faiss_index` folder.
- **No External Data Leakage**: The system is designed to prioritize local information over general web data when queried via the Direct Chat module.

---
**Developed for Myer's College by Muhammad Hadi**  
*© 2026 Myer’s College Digital Infrastructure*
