import sqlite3
import urllib.request
import json
import time
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "bookstore.db")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "book_summaries_cache.json")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "google_config.json")

def load_google_key():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            c = json.load(f)
            return c.get("google_api_key")
    return None

def fetch_top_books(limit=120):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT lower(trim(title)) as norm_title, title, author, simple_genre, count(*) as cnt
        FROM books
        GROUP BY lower(trim(title))
        ORDER BY cnt DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def generate_summaries_batch(books_batch, api_key):
    prompt = """You are a master literary scholar and librarian. For each of the following books, provide a rich, insightful, comprehensive 300 to 400 word synopsis/summary.
Detail:
- The core premise, story arc or main philosophical argument.
- Key themes, psychological insights, or intellectual concepts.
- Emotional resonance and why readers connect with it (e.g. for comfort, inspiration, mood shift, self-discovery, or clarity).

You MUST return a JSON object where keys are the exact book titles provided and values are the 300-400 word summary string.

Books to summarize:
"""
    for b in books_batch:
        prompt += f'- "{b[1]}" by {b[2]} (Genre: {b[3]})\n'

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        res_text = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(res_text)

def main():
    api_key = load_google_key()
    if not api_key:
        print("No Google API key found!")
        return

    existing = {}
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH) as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    print(f"Loaded {len(existing)} existing cached summaries.")

    top_books = fetch_top_books(limit=100)
    to_generate = [b for b in top_books if b[0] not in existing]
    print(f"Need to generate summaries for {len(to_generate)} titles.")

    batch_size = 10
    for i in range(0, len(to_generate), batch_size):
        batch = to_generate[i:i+batch_size]
        print(f"Generating batch {i//batch_size + 1}/{(len(to_generate)-1)//batch_size + 1} ({len(batch)} books)...")
        try:
            results = generate_summaries_batch(batch, api_key)
            for b in batch:
                norm_title = b[0]
                exact_title = b[1]
                # match key
                summary = results.get(exact_title) or results.get(norm_title)
                if not summary:
                    for k, v in results.items():
                        if k.lower().strip() == norm_title:
                            summary = v
                            break
                if summary:
                    existing[norm_title] = {
                        "title": exact_title,
                        "author": b[2],
                        "genre": b[3],
                        "summary": summary
                    }
                    print(f"  ✓ {exact_title} ({len(summary.split())} words)")
            # Save progress incrementally
            with open(OUTPUT_PATH, "w") as f:
                json.dump(existing, f, indent=2)
            time.sleep(1)
        except Exception as e:
            print(f"Error generating batch: {e}")
            time.sleep(2)

    print(f"Total cached summaries saved: {len(existing)}")

if __name__ == "__main__":
    main()
