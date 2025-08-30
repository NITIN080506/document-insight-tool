import os, io, json, hashlib
from datetime import datetime
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import pdfplumber
from collections import Counter
import re

app = FastAPI()

# static (frontend)
os.makedirs("static", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

UPLOAD_DIR = "uploads"
HISTORY_FILE = "history.json"
os.makedirs(UPLOAD_DIR, exist_ok=True)
if not os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "w") as f:
        json.dump([], f)

def save_history(entry):
    with open(HISTORY_FILE, "r+", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception:
            data = []
        data.append(entry)
        f.seek(0); f.truncate()
        json.dump(data, f, indent=2, ensure_ascii=False)

def extract_text_from_pdf_bytes(pdf_bytes):
    text = ""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

def top_n_words(text, n=5):
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    common = Counter(words).most_common(n)
    return [w for w,_ in common]

def naive_summary(text, max_chars=400):
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    summary = " ".join(sentences[:3])
    if len(summary) > max_chars:
        summary = summary[:max_chars] + "..."
    return summary

@app.post("/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file uploaded")
    filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as f:
        f.write(contents)

    text = extract_text_from_pdf_bytes(contents)
    fallback_top_words = top_n_words(text, 5)
    # Try external summarizer (Sarvam AI) if you set env vars:
    SARVAM_API_URL = os.environ.get("SARVAM_API_URL")  # e.g. "https://api.sarvam.ai/summarize"
    SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY")
    summary = None
    if SARVAM_API_URL and SARVAM_API_KEY:
        try:
            import requests
            resp = requests.post(SARVAM_API_URL, json={"text": text}, headers={"Authorization": f"Bearer {SARVAM_API_KEY}"}, timeout=10)
            if resp.ok:
                data = resp.json()
                summary = data.get("summary") or data.get("result") or None
        except Exception:
            summary = None

    if not summary:
        summary = naive_summary(text)

    entry = {
        "id": hashlib.md5(filename.encode()).hexdigest(),
        "filename": filename,
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
        "summary": summary,
        "top_words": fallback_top_words
    }
    save_history(entry)
    return JSONResponse(entry)

@app.get("/insights")
def get_insights(limit: int = 10):
    with open(HISTORY_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data[-limit:]
