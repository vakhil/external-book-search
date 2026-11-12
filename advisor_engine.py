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
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if key:
        return key
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return cfg.get("google_api_key", "").strip()
        except Exception:
            pass
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
Below is the baseline factual background for "{clean_t}" by {clean_a or 'Unknown Author'}:
"{base_summary}"

Task:
Extract and synthesize an engaging, comprehensive synopsis of this book combining the editorial styles found on Goodreads, Amazon, and leading literary publications.
Length requirement: Strictly between 150 and 400 words (do NOT make it shorter than 150 words).

Cover:
1. Core Premise & Narrative / Conceptual Framework: Central conflict, setting, main characters or core thesis.
2. Thematic Depth & Key Insights: Deep themes, practical takeaways, or philosophical questions explored.
3. Emotional Resonance & Reader Appeal: Why readers on Goodreads and Amazon recommend it, its tone, and who should read it.

Write in clear, fluid paragraphs. Ensure the word count is between 150 and 400 words."""

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3}
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                word_count = len(text.split())
                if word_count >= 140:
                    hybrid_summary = text
        except Exception as e:
            print(f"Notice generating 150-400 word synopsis: {e}")

    # Fallback to base summary if model is offline
    final_summary = hybrid_summary or base_summary

    # 5. Persist to RAM cache and SQLite DB
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
                cursor.execute("UPDATE books SET summary = ? WHERE lower(title) = ?", (final_summary, nt))
                if clean_bid:
                    cursor.execute("UPDATE books SET summary = ? WHERE book_id = ?", (final_summary, clean_bid))
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"Notice saving hybrid summary to DB: {e}")

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

def ask_advisor(question: str) -> Dict[str, Any]:
    """
    Main Advisor entry point.
    1. Checks in-memory query response cache (0ms).
    2. Retrieves top matching candidate books from inventory using intent matching.
    3. Fetches the pre-stored 300-400 word synopses from RAM.
    4. Calls Gemini Flash Lite to synthesize a bespoke recommendation combining
       the user's emotional/intellectual prompt and the rich book synopses.
    5. Returns formatted recommendation banner and matched books list.
    """
    clean_q = (question or "").strip()
    if not clean_q:
        return {
            "question": "",
            "answer": "Please ask a question or tell me what mood, topic, or reading experience you are looking for.",
            "books": [],
            "total_matches": 0
        }

    q_cache_key = clean_q.lower()
    if q_cache_key in _QUERY_RESPONSE_CACHE:
        return _QUERY_RESPONSE_CACHE[q_cache_key]

    load_summaries_into_ram()

    # Step 1: Detect emotional & conceptual keywords from query
    expanded_terms = []
    for mood, keywords in INTENT_THEMES.items():
        if mood in q_cache_key:
            expanded_terms.extend(keywords)

    combined_search_query = clean_q
    if expanded_terms:
        combined_search_query = f"{clean_q} {' '.join(expanded_terms[:4])}"

    # Step 2: Use search engine to find best candidate books in current inventory
    rec_data = search_engine.ask_recommendations(combined_search_query, top_n=25)
    candidate_books = rec_data.get("books", [])

    # If few or no candidates found, fallback to search across cached summaries in RAM
    if len(candidate_books) < 3:
        # Search RAM summary database directly for relevant themes
        q_tokens = [w for w in re.findall(r'\b[a-zA-Z]{3,}\b', q_cache_key) if w not in {"the", "and", "for", "with", "book", "books", "read"}]
        all_inventory = search_engine.get_all_books_cached()
        title_to_inv = {b["title"].lower().strip(): b for b in all_inventory}

        ram_matches = []
        for nt, data in _SUMMARIES_CACHE.items():
            text_blob = f"{data['title']} {data['author']} {data['genre']} {data['summary']}".lower()
            match_score = 0
            for t in q_tokens + expanded_terms:
                if t in text_blob:
                    match_score += 1
            if match_score > 0 and nt in title_to_inv:
                ram_matches.append((match_score, title_to_inv[nt]))

        ram_matches.sort(key=lambda x: x[0], reverse=True)
        top_ram_books = [m[1] for m in ram_matches[:15]]
        if top_ram_books:
            grouped_ram = search_engine.group_physical_copies(top_ram_books)
            # Merge while preserving uniqueness
            seen_titles = {b["title"].lower() for b in candidate_books}
            for gb in grouped_ram:
                if gb["title"].lower() not in seen_titles:
                    candidate_books.append(gb)
                    seen_titles.add(gb["title"].lower())

    # Step 3: Select top 3-4 candidates that have rich summaries in RAM
    top_candidates = []
    for b in candidate_books[:12]:
        t_key = b["title"].lower().strip()
        summary = _SUMMARIES_CACHE.get(t_key, {}).get("summary", "")
        if not summary:
            summary = b.get("summary", "")
        if not summary:
            # Quick fallback synopsis
            summary = f"A notable {b.get('simple_genre', 'featured')} work exploring meaningful perspectives and insights."
        top_candidates.append({
            "title": b["title"],
            "author": b.get("author", "Author"),
            "genre": b.get("simple_genre", b.get("genre", "")),
            "summary": summary,
            "book_obj": b
        })
        if len(top_candidates) >= 4:
            break

    # If no top candidates at all, fallback to rule-based response
    if not top_candidates:
        return rec_data

    # Step 4: Ask Gemini Flash Lite for ultra-fast, compassionate synthesis
    api_key = _get_api_key()
    answer_text = ""

    if api_key:
        try:
            candidates_prompt_list = [
                f"- **{c['title']}** by {c['author']} ({c['genre']}):\n  Synopsis: {c['summary'][:450]}"
                for c in top_candidates
            ]

            prompt = f"""User: "{clean_q}"

Available curated books in our store with their in-depth synopses:
{chr(10).join(candidates_prompt_list)}

Task:
You are an empathetic, insightful, literary book advisor.
Write a warm, 2-to-3 sentence personalized recommendation explaining why these specific books will speak to their mood, situation, or question. Synthesize the key themes and lessons from their synopses directly.
Mention 1 or 2 specific titles naturally in your response in bold (e.g. **Title**).
Do not use bullet points or intros like "Here is a recommendation". Speak directly and warmly to the customer."""

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
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                gdata = json.loads(resp.read().decode("utf-8"))
                answer_text = gdata["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            print(f"Gemini fast advisor notice: {e}")

    # Fallback to local synthesis if Gemini is slow, offline, or times out
    if not answer_text:
        c1 = top_candidates[0]
        c2 = top_candidates[1] if len(top_candidates) > 1 else None
        if "bad mood" in q_cache_key or "sad" in q_cache_key:
            if c2:
                answer_text = f"When you're feeling down, **{c1['title']}** by {c1['author']} and **{c2['title']}** by {c2['author']} offer genuine perspective and emotional warmth. Their narratives remind us how to navigate difficult moments, discover inner resilience, and gently restore peace of mind."
            else:
                answer_text = f"To help shift your mood, **{c1['title']}** by {c1['author']} provides an uplifting and compassionate perspective that can help you unwind, reset your thoughts, and find clarity."
        else:
            titles_str = f"**{c1['title']}**" + (f" and **{c2['title']}**" if c2 else "")
            answer_text = f"For what you're seeking, {titles_str} stand out as exceptional choices. Synthesizing profound themes of growth, wisdom, and life perspective, these works will give you both practical inspiration and deep reading enjoyment."

    final_books = [c["book_obj"] for c in top_candidates]
    # Add any remaining candidate books from search_engine
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

    # Store in fast memory cache (limit size to 200 items)
    _QUERY_RESPONSE_CACHE[q_cache_key] = result
    if len(_QUERY_RESPONSE_CACHE) > 200:
        first_k = next(iter(_QUERY_RESPONSE_CACHE))
        _QUERY_RESPONSE_CACHE.pop(first_k, None)

    return result
