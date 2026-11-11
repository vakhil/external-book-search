"""
Vercel Serverless Function entry point for External Book Search.
Implements standard WSGI interface supported by @vercel/python runtime.
Zero third-party dependencies - 100% Python Standard Library.
"""

import os
import sys
import json
import urllib.parse

# Ensure parent directory is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import database
import search_engine
import advisor_engine

# Prime and verify database on serverless cold-boot
try:
    database.ensure_database_ready()
    # Pre-warm search engine cache into RAM for instant searches
    search_engine.get_all_books_cached()
    # Pre-warm 300-400 word summaries into RAM
    advisor_engine.load_summaries_into_ram()
except Exception as e:
    print(f"Serverless DB init notice: {e}")

def json_response(start_response, data, status_code=200, cache_control=None):
    status_text = f"{status_code} OK" if status_code == 200 else f"{status_code} Error"
    if status_code == 404:
        status_text = "404 Not Found"
    elif status_code == 400:
        status_text = "400 Bad Request"
    elif status_code == 500:
        status_text = "500 Internal Server Error"

    cc = cache_control or "no-cache, no-store, must-revalidate"
    body = json.dumps(data, default=str).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
        ("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With"),
        ("Cache-Control", cc)
    ]
    start_response(status_text, headers)
    return [body]

def read_json_body(environ):
    try:
        content_length = int(environ.get("CONTENT_LENGTH", 0))
    except (ValueError, TypeError):
        content_length = 0
    if content_length > 0:
        wsgi_input = environ.get("wsgi.input")
        if wsgi_input:
            data = wsgi_input.read(content_length)
            try:
                return json.loads(data.decode("utf-8"))
            except Exception:
                return {}
    return {}

def _app_dispatch(environ, start_response):
    """Internal WSGI request dispatcher."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    query_string = environ.get("QUERY_STRING", "")
    query_params = urllib.parse.parse_qs(query_string)

    # Resolve accurate API path
    path = query_params.get("__path__", [""])[0]
    if not path or path == "/api/index.py":
        raw = environ.get("RAW_URI") or environ.get("REQUEST_URI") or environ.get("HTTP_X_MATCHED_PATH", "")
        if raw:
            path = urllib.parse.urlparse(raw).path
    if not path or path == "/api/index.py":
        path = environ.get("PATH_INFO", "")

    # CORS Preflight
    if method == "OPTIONS":
        headers = [
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With"),
            ("Content-Length", "0")
        ]
        start_response("200 OK", headers)
        return [b""]

    # 1. GET Endpoints
    if method == "GET":
        if path == "/api/search":
            q = query_params.get("q", [""])[0]
            stype = query_params.get("type", ["title"])[0]
            include_sold = query_params.get("include_sold", ["false"])[0].lower() in ("true", "1")
            limit = int(query_params.get("limit", [80])[0])
            results = search_engine.search_books(q, search_type=stype, include_sold=include_sold, limit=limit)
            return json_response(start_response, results, cache_control="public, max-age=15, s-maxage=30, stale-while-revalidate=60")

        elif path == "/api/genres":
            dist = database.get_genre_distribution()
            return json_response(start_response, {"genres": dist}, cache_control="public, max-age=60, s-maxage=120, stale-while-revalidate=300")

        elif path == "/api/books/by-genre":
            genre = query_params.get("genre", [""])[0]
            avail_only = query_params.get("available_only", ["true"])[0].lower() in ("true", "1")
            limit = int(query_params.get("limit", [500])[0])
            raw_books = database.get_books_by_genre(genre, available_only=avail_only, limit=limit)
            grouped = search_engine.group_physical_copies(raw_books)
            return json_response(start_response, {"genre": genre, "total_books": len(grouped), "books": grouped}, cache_control="public, max-age=30, s-maxage=60, stale-while-revalidate=120")

        elif path == "/api/books/cover":
            title = query_params.get("title", [""])[0]
            author = query_params.get("author", [""])[0]
            cover_url = database.get_or_fetch_book_cover(title, author)
            return json_response(start_response, {"title": title, "cover_url": cover_url})

        elif path == "/api/books/summary":
            title = query_params.get("title", [""])[0]
            author = query_params.get("author", [""])[0]
            book_id = query_params.get("book_id", [""])[0]
            summary = advisor_engine.get_book_summary(title=title, author=author, book_id=book_id)
            return json_response(start_response, {"title": title, "book_id": book_id, "summary": summary}, cache_control="public, max-age=3600, s-maxage=86400")

        elif path == "/api/stats":
            stats = database.get_inventory_stats()
            return json_response(start_response, {"stats": stats}, cache_control="public, max-age=30, s-maxage=60, stale-while-revalidate=120")

        elif path == "/api/ask-recommendations":
            q = query_params.get("q", [""])[0]
            result = advisor_engine.ask_advisor(q)
            return json_response(start_response, result, cache_control="public, max-age=60, s-maxage=120")

    # 2. POST Endpoints
    elif method == "POST":
        if path == "/api/ask-recommendations":
            body = read_json_body(environ)
            q = body.get("question", "")
            result = advisor_engine.ask_advisor(q)
            return json_response(start_response, result)

    return json_response(start_response, {"error": "Endpoint not found or disabled in external search portal"}, 404)

def app(environ, start_response):
    return _app_dispatch(environ, start_response)

def handler(environ, start_response):
    return _app_dispatch(environ, start_response)
