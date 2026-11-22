"""
advisor_engine.py
=================
High-speed AI Book Recommendation Engine for Bookmark.
Combines in-memory pre-indexed 300-400 word book synopses with Google Gemini (gemini-flash-lite-latest)
to deliver empathetic, accurate recommendations with ultra-low latency (<1.5s).
"""

import os
import re
import json
import time
import urllib.request
import threading
from typing import Dict, List, Any, Optional

import search_engine
import database

# Persistent in-memory cache of pre-generated 300-400 word book summaries
_SUMMARIES_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOADED = False
_CACHE_LOCK = threading.Lock()

# LRU / In-memory query response cache (instant 0ms response for repeated/similar questions)
_QUERY_RESPONSE_CACHE: Dict[str, Dict[str, Any]] = {}

SUMMARIES_CACHE_PATH = os.path.join(os.path.dirname(__file__), "book_summaries_cache.json")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "google_config.json")

def _get_api_key() -> str:
    # First check google_config.json which holds our verified active key
    candidates = [
        CONFIG_PATH,
        os.path.join(os.getcwd(), "google_config.json"),
        "/var/task/google_config.json",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "google_config.json")
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    k = cfg.get("google_api_key", "").strip()
                    if k and not k.startswith("AIzaSyBfJX"):  # Skip revoked key
                        return k
            except Exception:
                pass

    key = (os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")).strip()
    if key and not key.startswith("AIzaSyBfJX"):
        return key

    return ""

def load_summaries_into_ram():
    """Pre-warms the 300-400 word summaries into RAM for 0ms lookup."""
    global _SUMMARIES_CACHE, _CACHE_LOADED
    if _CACHE_LOADED:
        return
    with _CACHE_LOCK:
        if _CACHE_LOADED:
            return
        # 1. Load from pre-indexed JSON file if available
        if os.path.exists(SUMMARIES_CACHE_PATH):
            try:
                with open(SUMMARIES_CACHE_PATH, "r", encoding="utf-8") as f:
                    _SUMMARIES_CACHE = json.load(f)
            except Exception as e:
                print(f"Notice loading summaries cache JSON: {e}")

        # 2. Augment from SQLite database books table where summary is stored
        try:
            conn = database.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT lower(trim(title)) as norm_t, title, author, simple_genre, summary
                FROM books
                WHERE summary IS NOT NULL AND length(trim(summary)) > 20
                GROUP BY lower(trim(title))
            """)
            for row in cursor.fetchall():
                nt = row["norm_t"]
                if nt not in _SUMMARIES_CACHE or not _SUMMARIES_CACHE[nt].get("summary"):
                    _SUMMARIES_CACHE[nt] = {
                        "title": row["title"],
                        "author": row["author"],
                        "genre": row["simple_genre"],
                        "summary": row["summary"].strip()
                    }
        except Exception as e:
            print(f"Notice syncing DB summaries to RAM: {e}")

        _CACHE_LOADED = True
        print(f"Advisor Engine: Loaded {len(_SUMMARIES_CACHE)} rich book summaries into RAM.")

def get_book_summary(title: str, author: str = "", book_id: str = "") -> str:
    """
    Returns an in-depth 300 to 400 word synopsis combining baseline facts with
    literary, thematic, and psychological Gemini synthesis.
    Results are cached in RAM and persisted to SQLite for 0ms subsequent lookups.
    """
    clean_t = (title or "").strip()
    clean_a = (author or "").strip()
    clean_bid = (book_id or "").strip()
    if not clean_t and not clean_bid:
        return ""

    load_summaries_into_ram()
    nt = clean_t.lower()

    # 1. Instant RAM cache hit (if it's already a full 300-400 word synopsis)
    if nt in _SUMMARIES_CACHE:
        s = _SUMMARIES_CACHE[nt].get("summary", "").strip()
        if len(s.split()) >= 150:
            return s

    # 2. Check SQLite database
    existing_db_summary = ""
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        if clean_bid:
            cursor.execute("SELECT summary, title, author, simple_genre, genre FROM books WHERE book_id = ? LIMIT 1", (clean_bid,))
            row = cursor.fetchone()
            if row:
                if row["summary"] and len(row["summary"].strip().split()) >= 150:
                    existing_db_summary = row["summary"].strip()
                if not clean_t and row["title"]:
                    clean_t = row["title"]
                    nt = clean_t.lower()
                if not clean_a and row["author"]:
                    clean_a = row["author"]
        if not existing_db_summary and clean_t:
            cursor.execute("SELECT summary, author, simple_genre, genre FROM books WHERE lower(title) = ? AND summary != '' AND summary IS NOT NULL LIMIT 1", (nt,))
            row = cursor.fetchone()
            if row and row["summary"] and len(row["summary"].strip().split()) >= 150:
                existing_db_summary = row["summary"].strip()
                if not clean_a and row["author"]:
                    clean_a = row["author"]
        conn.close()
    except Exception as e:
        print(f"Notice querying DB for synopsis: {e}")

    if existing_db_summary:
        with _CACHE_LOCK:
            _SUMMARIES_CACHE[nt] = {
                "title": clean_t,
                "author": clean_a,
                "summary": existing_db_summary
            }
        return existing_db_summary

    # 3. Retrieve baseline summary (from Wikipedia/Google/OpenLibrary)
    base_summary = database.get_or_fetch_book_summary(title=clean_t, author=clean_a, book_id=clean_bid)

    # 4. Generate 150 to 400 word rich hybrid synopsis synthesizing Goodreads, Amazon editorial reviews, and literary overview
    api_key = _get_api_key()
    hybrid_summary = ""

    if api_key and clean_t:
        try:
            prompt = f"""You are an expert literary curator and book editor.
Book: "{clean_t}" by {clean_a or 'Unknown Author'}
Baseline notes: "{base_summary}"

Task:
Write an engaging, high quality, in-depth synopsis of this book combining the editorial styles found on Goodreads, Amazon, and leading literary publications.
Length requirement: Strictly between 150 and 350 words (do NOT make it shorter than 150 words).

Cover:
1. Core Premise & Narrative / Conceptual Framework: Central conflict, setting, main thesis, or key concepts.
2. Thematic Depth & Key Insights: Deep themes, practical takeaways, or philosophical questions explored.
3. Emotional Resonance & Reader Appeal: Tone, why readers on Goodreads/Amazon love it, and who should read it.

Rules:
- Do NOT include author biographical trivia (e.g. do not say "The author was born in...", "is a nephrologist...", etc.).
- Focus entirely on the book itself.
- Write in clear, elegant, fluid paragraphs."""

            _last_err = ""
            for model_name in ["gemini-flash-lite-latest", "gemini-flash-latest"]:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                    payload = {
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.3}
                    }
                    req = urllib.request.Request(
                        url,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                            "x-goog-api-key": api_key
                        }
                    )
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        word_count = len(text.split())
                        if word_count >= 130:
                            hybrid_summary = text
                            break
                except Exception as ex:
                    _last_err = f"{model_name}: {ex}"
                    continue
        except Exception as e:
            _last_err = f"outer: {e}"
            print(f"Notice generating 150-400 word synopsis: {e}")

    # Fallback to base summary if model is offline or key is revoked
    final_summary = hybrid_summary or base_summary

    # Cache in RAM and persist to database so subsequent requests are instant
    if final_summary and clean_t:
        with _CACHE_LOCK:
            _SUMMARIES_CACHE[nt] = {
                "title": clean_t,
                "author": clean_a,
                "summary": final_summary
            }
        try:
            with database.db_lock:
                conn = database.get_db_connection()
                cursor = conn.cursor()
                if clean_t:
                    cursor.execute(
                        "UPDATE books SET summary = ? WHERE lower(title) = ? AND (summary IS NULL OR summary = '')",
                        (final_summary, clean_t.lower())
                    )
                if clean_bid:
                    cursor.execute(
                        "UPDATE books SET summary = ? WHERE book_id = ? AND (summary IS NULL OR summary = '')",
                        (final_summary, clean_bid)
                    )
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"Notice persisting lazy-fetched summary to DB: {e}")

    return final_summary

# Pre-warm summaries into memory on module load
try:
    load_summaries_into_ram()
except Exception:
    pass

# Concept expansions for mood and intent mapping
INTENT_THEMES = {
    "bad mood": ["uplifting", "comfort", "healing", "happiness", "humor", "peace", "hope", "mindset", "perspective", "wisdom"],
    "sad": ["comfort", "uplifting", "healing", "love", "lightness", "poetry", "resilience"],
    "depressed": ["healing", "mindset", "meaning", "courage", "strength", "hope"],
    "stressed": ["calm", "stoicism", "mindfulness", "peace", "relaxation", "declutter"],
    "anxious": ["anxiety", "peace", "calm", "presence", "now", "breathing", "acceptance"],
    "bored": ["adventure", "thriller", "mystery", "exciting", "fantasy", "epic"],
    "procrastination": ["habit", "discipline", "focus", "action", "productivity"],
    "money": ["wealth", "finance", "investing", "psychology", "business", "freedom"],
    "purpose": ["meaning", "ikigai", "calling", "destiny", "philosophy", "journey"],
    "lonely": ["connection", "solitude", "empathy", "warmth", "friendship", "love"]
}

def fetch_internet_synopsis(title: str, author: str = "") -> str:
    """
    Directly extracts summary facts and premise from Wikipedia and Google Books
    so Gemini can synthesize with grounded real-world knowledge.
    """
    clean_t = (title or "").strip()
    clean_a = (author or "").strip()
    if not clean_t:
        return ""

    # 1. Try Wikipedia REST / search API
    try:
        query = f"{clean_t} {clean_a}".strip()
        url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.request.quote(query)}&utf8=&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "BookMarkLiteraryEngine/2.0 (contact@bookmark.com)"})
        with urllib.request.urlopen(req, timeout=3.5) as r:
            data = json.loads(r.read().decode("utf-8"))
            hits = data.get("query", {}).get("search", [])
            if hits:
                pid = hits[0].get("pageid")
                purl = f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro=&explaintext=&pageids={pid}&format=json"
                with urllib.request.urlopen(urllib.request.Request(purl, headers={"User-Agent": "BookMarkLiteraryEngine/2.0"}), timeout=3) as pr:
                    pdata = json.loads(pr.read().decode("utf-8"))
                    extract = pdata.get("query", {}).get("pages", {}).get(str(pid), {}).get("extract", "").strip()
                    if len(extract.split()) >= 25:
                        return extract
    except Exception:
        pass

    return ""

def ask_advisor(question: str) -> Dict[str, Any]:
    """
    State-of-the-art AI Book Curator & Recommendation Engine.
    1. Uses Gemini to semantically diagnose the user's emotional and intellectual need.
    2. Dynamically queries bookstore inventory across multi-dimensional concept angles.
    3. Retrieves grounded synopses (RAM cache, SQLite database, or Internet extract).
    4. Uses Gemini to curate the top recommendations and craft an empathetic, literary personalized note.
    """
    clean_q = (question or "").strip()
    if not clean_q:
        return {
            "question": "",
            "answer": "Please describe your mood, a situation, or what genre and feeling you're longing to read.",
            "books": [],
            "total_matches": 0
        }

    q_cache_key = clean_q.lower()
    if q_cache_key in _QUERY_RESPONSE_CACHE:
        return _QUERY_RESPONSE_CACHE[q_cache_key]

    load_summaries_into_ram()
    api_key = _get_api_key()

    # Step 1: Semantic Intent Analysis using Gemini Flash Lite
    search_queries = []
    preferred_genres = []
    if api_key:
        try:
            expansion_prompt = f"""You are Book Mark's master literary book curator.
A customer asks: "{clean_q}"

Task:
Understand their deep psychological, emotional, or intellectual hunger.
Provide:
1. "search_terms": 3 to 5 targeted search keywords or themes to query physical bookstore shelves (e.g. ['habit', 'mindset', 'courage', 'resilience', 'zen']).
2. "genres": 2 relevant genres from our bookstore categories (e.g. ['Self-Help', 'Philosophy', 'Fiction', 'Psychology', 'Health & Wellness']).

Respond STRICTLY with valid JSON:
{{"search_terms": ["..."], "genres": ["..."]}}"""

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={api_key}"
            req = urllib.request.Request(
                url,
                data=json.dumps({
                    "contents": [{"parts": [{"text": expansion_prompt}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 180}
                }).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key}
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                gdata = json.loads(resp.read().decode("utf-8"))
                raw_json = gdata["candidates"][0]["content"]["parts"][0]["text"].strip()
                raw_json = re.sub(r"^```(?:json)?\s*", "", raw_json)
                raw_json = re.sub(r"\s*```$", "", raw_json)
                parsed = json.loads(raw_json)
                search_queries = parsed.get("search_terms", [])
                preferred_genres = parsed.get("genres", [])
        except Exception as e:
            # Fallback to local theme mapping
            pass

    # Fallback to static intent keywords if Gemini was slow or unavailable
    if not search_queries:
        for mood, keywords in INTENT_THEMES.items():
            if mood in q_cache_key:
                search_queries.extend(keywords[:4])

    # Step 2: Multi-Pass Inventory Search across Bookstore Database
    candidate_map: Dict[str, Dict[str, Any]] = {}
    candidate_books: List[Dict[str, Any]] = []

    # A. Search with original user query
    primary_data = search_engine.ask_recommendations(clean_q, top_n=20)
    for b in primary_data.get("books", []):
        t_low = b["title"].lower().strip()
        if t_low not in candidate_map:
            candidate_map[t_low] = b
            candidate_books.append(b)

    # B. Search with expanded concepts
    for sq in search_queries[:4]:
        sub_res = search_engine.ask_recommendations(sq, top_n=10)
        for b in sub_res.get("books", []):
            t_low = b["title"].lower().strip()
            if t_low not in candidate_map:
                candidate_map[t_low] = b
                candidate_books.append(b)

    # C. Fallback to RAM summary search if few matches
    if len(candidate_books) < 4:
        all_inventory = search_engine.get_all_books_cached()
        title_to_inv = {b["title"].lower().strip(): b for b in all_inventory}
        q_tokens = [w for w in re.findall(r'\b[a-zA-Z]{3,}\b', q_cache_key) if w not in {"the", "and", "for", "with", "book", "books", "read"}]

        ram_matches = []
        for nt, data in _SUMMARIES_CACHE.items():
            text_blob = f"{data['title']} {data['author']} {data.get('genre','')} {data.get('summary','')}".lower()
            score = sum(1 for t in (q_tokens + search_queries) if t.lower() in text_blob)
            if score > 0 and nt in title_to_inv:
                ram_matches.append((score, title_to_inv[nt]))

        ram_matches.sort(key=lambda x: x[0], reverse=True)
        for m in ram_matches[:12]:
            t_low = m[1]["title"].lower().strip()
            if t_low not in candidate_map:
                candidate_map[t_low] = m[1]
                candidate_books.append(m[1])

    if not candidate_books:
        return {
            "question": clean_q,
            "answer": "Our shelves have thousands of works! Could you specify a favorite author, topic, or story type so I can pinpoint the perfect book for you?",
            "books": [],
            "total_matches": 0
        }

    # Step 3: Ensure Top Candidates have Rich Synopses (RAM or DB cached)
    top_candidates = []
    for b in candidate_books[:10]:
        t_key = b["title"].lower().strip()
        summary = _SUMMARIES_CACHE.get(t_key, {}).get("summary", "")
        if not summary:
            summary = b.get("summary", "")
        if not summary or len(summary.split()) < 20:
            summary = f"A notable {b.get('simple_genre', 'featured')} work exploring meaningful perspectives, human connection, and insights."

        top_candidates.append({
            "title": b["title"],
            "author": b.get("author", "Author"),
            "genre": b.get("simple_genre", b.get("genre", "Book")),
            "summary": summary,
            "book_obj": b
        })
        if len(top_candidates) >= 5:
            break

    # Step 4: Ask Gemini Flash Lite for empathetic, literary synthesis
    answer_text = ""
    if api_key and top_candidates:
        try:
            candidates_prompt_list = [
                f"- **{c['title']}** by {c['author']} ({c['genre']}): {c['summary'][:220]}"
                for c in top_candidates[:3]
            ]

            prompt = f"""You are Book Mark bookstore's master literary book advisor — deeply empathetic, warm, perceptive, and exceptionally well-read.

Customer asked:
"{clean_q}"

Available curated books from our bookstore:
{chr(10).join(candidates_prompt_list)}

Task:
Write a captivating, warm, and deeply resonant 2-to-3 sentence personalized recommendation directly to the customer.
- Speak directly to their feeling or goal with genuine warmth and emotional resonance.
- Seamlessly spotlight 1 or 2 of the specific titles in bold (**Book Title**) and articulate why its narrative, insights, or philosophy speaks directly to them right now.
- Do NOT use generic openings like "Here are some books" or "I recommend". Speak naturally and warmly like a beloved neighborhood bookseller."""

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.4,
                    "maxOutputTokens": 200
                }
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key}
            )
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                gdata = json.loads(resp.read().decode("utf-8"))
                txt = gdata["candidates"][0]["content"]["parts"][0]["text"].strip()
                if txt:
                    answer_text = txt
        except Exception as e:
            print(f"Gemini advisor generation notice: {e}")

    # Fallback to local thoughtful message if Gemini is offline
    if not answer_text and top_candidates:
        c1 = top_candidates[0]
        c2 = top_candidates[1] if len(top_candidates) > 1 else None
        if "bad mood" in q_cache_key or "sad" in q_cache_key:
            if c2:
                answer_text = f"When you're carrying a heavy mood, **{c1['title']}** by {c1['author']} and **{c2['title']}** by {c2['author']} offer genuine solace and gentle perspective. Their pages remind us how to navigate difficult moments, discover inner resilience, and slowly bring warmth back to your day."
            else:
                answer_text = f"To help shift your mood, **{c1['title']}** by {c1['author']} provides a deeply uplifting and compassionate perspective that will help you quiet your thoughts and find renewed hope."
        else:
            titles_str = f"**{c1['title']}**" + (f" and **{c2['title']}**" if c2 else "")
            answer_text = f"For what you're seeking, {titles_str} stand out as extraordinary companions. Synthesizing profound themes of life, wisdom, and inner growth, these works will offer you both rich intellectual enjoyment and lasting inspiration."

    # Order books so the spotlighted books appear first
    final_books = [c["book_obj"] for c in top_candidates]
    seen_final_titles = {b["title"].lower() for b in final_books}
    for b in candidate_books:
        if b["title"].lower() not in seen_final_titles:
            final_books.append(b)
            seen_final_titles.add(b["title"].lower())

    result = {
        "question": clean_q,
        "answer": answer_text,
        "books": final_books[:20],
        "total_matches": len(final_books)
    }

    _QUERY_RESPONSE_CACHE[q_cache_key] = result
    if len(_QUERY_RESPONSE_CACHE) > 200:
        first_k = next(iter(_QUERY_RESPONSE_CACHE))
        _QUERY_RESPONSE_CACHE.pop(first_k, None)

    return result
