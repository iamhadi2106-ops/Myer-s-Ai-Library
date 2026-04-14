import os
import json
import zipfile
import tempfile
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, FileResponse, JsonResponse
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth import login, logout, authenticate
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from .models import Book, ChatMessage, AIConfig, UserProfile
from .forms import BookForm
from .ai_engine import AIEngine
from functools import wraps

try:
    from groq import Groq
except Exception:
    Groq = None

try:
    from gtts import gTTS
except Exception:
    gTTS = None

# --- ROLE MIDDLEWARE & DECORATORS ---

def user_role_required(roles):
    """Decorator for checking UserProfile Role"""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            
            profile = getattr(request.user, 'userprofile', None)
            if not profile:
                return HttpResponse("System Access Error: No User Profile.", status=403)
            
            if profile.is_suspended:
                return HttpResponse("ACCESS DENIED: Your student account has been suspended by a faculty member.", status=403)

            if profile.role in roles:
                return view_func(request, *args, **kwargs)
            
            return HttpResponse(f"ACCESS DENIED: Permission for {profile.role} denied for this node.", status=403)
        return _wrapped
    return decorator

# --- GET AI ENGINE ---
def get_ai_engine():
    config = AIConfig.objects.filter(is_active=True).first()
    api_key = config.groq_api_key if config else os.getenv("GROQ_API_KEY")
    return AIEngine(api_key=api_key)


def _extract_excel_rows(xlsx_path):
    """
    Read the first worksheet from an XLSX file using stdlib only.
    Returns a list of row values.
    """
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(xlsx_path) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall("m:si", ns):
                text_parts = [node.text or "" for node in item.findall(".//m:t", ns)]
                shared_strings.append("".join(text_parts))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = workbook.findall("m:sheets/m:sheet", ns)
        if not sheets:
            return []

        first_sheet_id = sheets[0].attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib.get("Id"): rel.attrib.get("Target") for rel in rels}
        target = rel_map.get(first_sheet_id, "worksheets/sheet1.xml").lstrip("/")
        if not target.startswith("xl/"):
            target = f"xl/{target}"

        sheet_xml = ET.fromstring(archive.read(target))
        rows = []
        for row in sheet_xml.findall("m:sheetData/m:row", ns):
            row_values = []
            for cell in row.findall("m:c", ns):
                cell_type = cell.attrib.get("t")
                value_node = cell.find("m:v", ns)
                raw_value = value_node.text if value_node is not None else ""
                if cell_type == "s" and raw_value.isdigit():
                    idx = int(raw_value)
                    value = shared_strings[idx] if idx < len(shared_strings) else ""
                else:
                    value = raw_value or ""
                row_values.append(value.strip() if isinstance(value, str) else value)
            rows.append(row_values)
        return rows


def _sync_books_from_excel():
    """
    Import book titles/authors from root workbook if present.
    Idempotent: avoids duplicate title inserts.
    """
    xlsx_path = Path(settings.BASE_DIR) / "Library Books (Autosaved).xlsx"
    if not xlsx_path.exists():
        return

    try:
        rows = _extract_excel_rows(xlsx_path)
    except Exception:
        return

    if not rows:
        return

    header = [str(col).strip().lower() for col in rows[0]]

    def _pick_title_index():
        preferred = (
            "book title",
            "title",
            "book name",
            "name of book",
            "book",
        )
        for label in preferred:
            for idx, col_name in enumerate(header):
                if col_name == label or label in col_name:
                    return idx

        # If headers are unclear, infer the most "title-like" column.
        sample_rows = rows[1:80]
        if not sample_rows:
            return 0
        width = max((len(r) for r in sample_rows), default=1)
        best_idx = 0
        best_score = -1
        for idx in range(width):
            score = 0
            for r in sample_rows:
                if idx >= len(r):
                    continue
                cell = str(r[idx]).strip()
                if len(cell) < 3:
                    continue
                if any(ch.isalpha() for ch in cell):
                    score += 2
                if "http" in cell.lower():
                    score -= 3
                if cell.isdigit():
                    score -= 2
            if score > best_score:
                best_score = score
                best_idx = idx
        return best_idx

    title_idx = _pick_title_index()
    author_idx = next((i for i, name in enumerate(header) if "author" in name or "writer" in name), None)
    description_idx = next((i for i, name in enumerate(header) if "description" in name or "summary" in name or "about" in name), None)
    full_text_idx = next((i for i, name in enumerate(header) if "full text" in name or "content" in name or "body" in name), None)
    external_url_idx = next((i for i, name in enumerate(header) if "pdf" in name or "url" in name or "link" in name), None)

    seen = set()
    for row in rows[1:]:
        if title_idx >= len(row):
            continue
        title = str(row[title_idx]).strip()
        title = title.strip("`'\".-_ ")
        if not title:
            continue
        if len(title) < 3:
            continue
        if title.isdigit():
            continue
        if not any(ch.isalpha() for ch in title):
            continue
        if title.lower().startswith(("http://", "https://")):
            continue
        norm_title = title.lower()
        if norm_title in seen:
            continue
        seen.add(norm_title)

        author = ""
        if author_idx is not None and author_idx < len(row):
            author = str(row[author_idx]).strip()

        description = ""
        if description_idx is not None and description_idx < len(row):
            description = str(row[description_idx]).strip()

        full_text = ""
        if full_text_idx is not None and full_text_idx < len(row):
            full_text = str(row[full_text_idx]).strip()

        external_url = ""
        if external_url_idx is not None and external_url_idx < len(row):
            external_url = str(row[external_url_idx]).strip()
            if external_url and not external_url.startswith(("http://", "https://")):
                external_url = ""

        metadata_defaults = {}
        if full_text:
            metadata_defaults["full_text"] = full_text
        if external_url:
            metadata_defaults["external_url"] = external_url

        metadata_defaults["source"] = "excel_import"
        defaults = {"author": author} if author else {}
        if description:
            defaults["description"] = description
        if metadata_defaults:
            defaults["metadata"] = metadata_defaults

        book, created = Book.objects.get_or_create(title=title, defaults=defaults)

        if not created:
            changed = False
            if author and not book.author:
                book.author = author
                changed = True
            if description and not book.description:
                book.description = description
                changed = True
            meta = dict(book.metadata or {})
            if external_url and not meta.get("external_url"):
                meta["external_url"] = external_url
                changed = True
            if full_text and not meta.get("full_text"):
                meta["full_text"] = full_text
                changed = True
            if changed:
                book.metadata = meta
                book.save()

    # Cleanup obviously invalid old spreadsheet imports.
    for stale in Book.objects.filter(file__isnull=True):
        meta = stale.metadata or {}
        clean = (stale.title or "").strip("`'\".-_ ")
        bad = not clean or len(clean) < 3 or clean.isdigit()
        bad = bad or not any(ch.isalpha() for ch in clean)
        # Only auto-delete records that look imported and have no useful metadata/file.
        is_weak_record = not stale.file and not (stale.author or "").strip() and not (stale.description or "").strip()
        if meta.get("source") != "excel_import" and not is_weak_record:
            continue
        if bad:
            stale.delete()

# --- AUTH VIEWS ---

@never_cache
@ensure_csrf_cookie
def login_view(request):
    if request.method == 'POST':
        user_id = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        # MASTER ADMIN SPECIAL ACCESS
        if password == '2106' and not user_id:
            # Special auto-login for Master Admin
            admin_user, _ = User.objects.get_or_create(username='SystemAdmin')
            if not hasattr(admin_user, 'userprofile'):
                UserProfile.objects.create(user=admin_user, role='admin')
            login(request, admin_user)
            return redirect('book_list')

        # STANDARD AUTH
        user = authenticate(username=user_id, password=password)
        if user:
            login(request, user)
            profile = user.userprofile
            if profile.is_suspended:
                logout(request)
                get_token(request)
                return render(request, 'login.html', {'error': 'STUDENT ACCOUNT SUSPENDED.'})
            return redirect('book_list')
        
        get_token(request)
        return render(request, 'login.html', {'error': 'CREDENTIALS REJECTED BY ARCHIVE.'})

    get_token(request)
    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    return redirect('login')

# --- DASHBOARD & PERSISTENT VIEWS ---

@user_role_required(['student', 'teacher', 'admin'])
def book_list(request):
    _sync_books_from_excel()
    books = Book.objects.all().order_by('-uploaded_at')
    profile = request.user.userprofile
    return render(request, 'book_list.html', {'books': books, 'role': profile.role})

# --- TEACHER & ADMIN: BOOK MANAGEMENT ---

@user_role_required(['teacher', 'admin'])
def upload_book(request):
    if request.method == 'POST':
        form = BookForm(request.POST)
        if form.is_valid():
            book = form.save()
            if book.file and getattr(book.file, "path", None):
                engine = get_ai_engine()
                try:
                    engine.process_pdf(book.file.path)
                except Exception as e:
                    print(f"AI Indexing Fail: {e}")
            return redirect('book_list')
    else: form = BookForm()
    return render(request, 'upload.html', {'form': form})

@user_role_required(['teacher', 'admin'])
def delete_book(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if book.file and getattr(book.file, "path", None) and os.path.exists(book.file.path):
        os.remove(book.file.path)
    book.delete()
    return redirect('book_list')

@user_role_required(['student', 'teacher', 'admin'])
def download_book(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if book.file and getattr(book.file, "path", None) and os.path.exists(book.file.path):
        return FileResponse(open(book.file.path, 'rb'), as_attachment=True, filename=os.path.basename(book.file.path))
    external_url = (book.metadata or {}).get("external_url", "")
    if external_url:
        return redirect(external_url)
    return HttpResponse('Record not Found.', status=404)


@user_role_required(['student', 'teacher', 'admin'])
def read_book(request, pk):
    book = get_object_or_404(Book, pk=pk)
    meta = book.metadata or {}
    local_pdf_url = book.file.url if book.file else None
    external_url = meta.get("external_url")
    full_text = meta.get("full_text") or book.description or ""
    return render(request, 'read_book.html', {
        'book': book,
        'local_pdf_url': local_pdf_url,
        'external_url': external_url,
        'full_text': full_text,
    })

# --- TEACHER: STUDENT MANAGEMENT ---

@user_role_required(['teacher', 'admin'])
def manage_students(request):
    students = UserProfile.objects.filter(role='student')
    return render(request, 'manage_students.html', {'students': students})

@user_role_required(['teacher', 'admin'])
def toggle_suspension(request, pk):
    profile = get_object_or_404(UserProfile, pk=pk)
    if profile.role == 'student':
        profile.is_suspended = not profile.is_suspended
        profile.save()
    return redirect('manage_students')

# --- ADMIN: MASTER SYSTEM UI (Teacher/Student Add) ---

@user_role_required(['admin'])
def master_admin_hub(request):
    users = UserProfile.objects.exclude(user__username='SystemAdmin')
    if request.method == 'POST':
        uname = request.POST.get('new_user_id')
        upass = request.POST.get('new_user_pass')
        urole = request.POST.get('new_role') # 'teacher' or 'student'
        
        if uname and upass:
            try:
                new_user = User.objects.create_user(username=uname, password=upass)
                UserProfile.objects.create(user=new_user, role=urole)
                return render(request, 'admin_hub.html', {'success': f'Added {urole.upper()}: {uname}', 'users': users})
            except:
                return render(request, 'admin_hub.html', {'error': 'Username already registered.', 'users': users})
                
    return render(request, 'admin_hub.html', {'users': users})

@user_role_required(['admin'])
def config_view(request):
    config = AIConfig.objects.first()
    if request.method == 'POST':
        new_key = request.POST.get('api_key', '')
        if config:
            config.groq_api_key = new_key
            config.save()
        else:
            AIConfig.objects.create(groq_api_key=new_key)
        return redirect('book_list')
    return render(request, 'config.html', {'config': config})

@user_role_required(['admin'])
def delete_user(request, pk):
    user_to_del = get_object_or_404(User, pk=pk)
    # Prevent deleting self or non-managed accounts if needed
    if user_to_del.username != 'SystemAdmin':
        user_to_del.delete()
    return redirect('admin_hub')

# --- AI CORE (Librarian) ---

@user_role_required(['student', 'teacher', 'admin'])
@ensure_csrf_cookie
def ai_chat(request):
    messages = ChatMessage.objects.filter(user=request.user)[:50]
    return render(request, 'ai_chat.html', {'chat_history': messages})

@user_role_required(['student', 'teacher', 'admin'])
def search_exact(request):
    _sync_books_from_excel()
    q = request.GET.get('q', '').strip()
    results = Book.objects.filter(title__icontains=q) if q else []
    profile = request.user.userprofile
    return render(request, 'book_list.html', {'books': results, 'query': q, 'role': profile.role})

@user_role_required(['student', 'teacher', 'admin'])
def chat_api(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        query = data.get('message', '')
        context_type = 'archive' # Strictly enforced for local library knowledge
        engine = get_ai_engine()
        response = engine.ask_ai(query, context_type=context_type)
        ChatMessage.objects.create(user=request.user, message=query, response=response, context_source=context_type)
        return JsonResponse({"response": response})
    return JsonResponse({"error": "Invalid method"}, status=400)


@user_role_required(['student', 'teacher', 'admin'])
@require_POST
def speech_chat_api(request):
    audio_file = request.FILES.get('audio')
    if not audio_file:
        return JsonResponse({"error": "No audio file uploaded."}, status=400)

    config = AIConfig.objects.filter(is_active=True).first()
    api_key = config.groq_api_key if config else os.getenv("GROQ_API_KEY")
    if not api_key:
        return JsonResponse({"error": "Speech agent unavailable: API key missing."}, status=400)
    if Groq is None:
        return JsonResponse({"error": "Speech agent dependency missing: groq package unavailable."}, status=500)

    transcript = ""
    try:
        client = Groq(api_key=api_key)
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(audio_file.name).suffix or ".webm") as tmp:
            for chunk in audio_file.chunks():
                tmp.write(chunk)
            temp_path = tmp.name

        try:
            with open(temp_path, "rb") as audio_stream:
                transcription = client.audio.transcriptions.create(
                    file=(audio_file.name, audio_stream.read()),
                    model="whisper-large-v3",
                    response_format="json",
                    language="en",
                    temperature=0.0,
                )
            transcript = (getattr(transcription, "text", "") or "").strip()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    except Exception as exc:
        return JsonResponse({"error": f"Transcription failed: {exc}"}, status=500)

    if not transcript:
        return JsonResponse({"error": "No speech detected. Please try again."}, status=400)

    engine = get_ai_engine()
    response_text = engine.ask_ai(transcript, context_type='archive')
    ChatMessage.objects.create(
        user=request.user,
        message=f"[VOICE] {transcript}",
        response=response_text,
        context_source="archive_voice",
    )

    audio_reply_url = None
    if gTTS is not None:
        try:
            tts_dir = Path(settings.MEDIA_ROOT) / "tts"
            tts_dir.mkdir(parents=True, exist_ok=True)
            filename = f"reply_{uuid.uuid4().hex}.mp3"
            output_path = tts_dir / filename
            gTTS(text=response_text, lang="en", slow=False).save(str(output_path))
            audio_reply_url = f"{settings.MEDIA_URL}tts/{filename}"
        except Exception:
            audio_reply_url = None

    return JsonResponse({
        "transcript": transcript,
        "response": response_text,
        "audio_url": audio_reply_url,
    })


def error_400(request, exception):
    return render(request, 'errors/error.html', {
        'status_code': 400,
        'title': 'Request Error',
        'message': 'Something was wrong with this request. Please try again.'
    }, status=400)


def error_403(request, exception=None, reason=None):
    return render(request, 'errors/error.html', {
        'status_code': 403,
        'title': 'Access Denied',
        'message': reason or 'You do not have permission to access this page.'
    }, status=403)


def error_404(request, exception):
    return render(request, 'errors/error.html', {
        'status_code': 404,
        'title': 'Page Not Found',
        'message': 'The page you requested could not be found.'
    }, status=404)


def error_500(request):
    return render(request, 'errors/error.html', {
        'status_code': 500,
        'title': 'Server Error',
        'message': 'Something unexpected happened. Please try again shortly.'
    }, status=500)
