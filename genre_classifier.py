"""
Standardized Book Genre Classifier.
Maps 2,900+ detailed/niche book subgenres into a clean, fixed list of common genres.
"""

from typing import List

FIXED_COMMON_GENRES: List[str] = [
    "Fiction",
    "Philosophy",
    "Self-Help",
    "History",
    "Biography",
    "Business & Economics",
    "Politics",
    "Law",
    "Psychology",
    "Science & Technology",
    "Religion & Spirituality",
    "Health & Wellness",
    "Music",
    "Art & Culture",
    "Children & Young Adult",
    "Travel & Adventure",
    "Cookery & Food",
    "Education & Reference",
    "Humor & Lifestyle",
    "General Non-Fiction"
]

def classify_common_genre(raw_genre: str, title: str = "") -> str:
    """
    Classifies a raw subgenre or title into one of the fixed canonical common genres.
    
    Examples:
      - 'Indian Philosophy / Non-Western Philosophy' -> 'Philosophy'
      - 'Music History / Business' -> 'Music'
      - 'Tax Law / Real Estate Law' -> 'Law'
      - 'self-help' -> 'Self-Help'
    """
    if not raw_genre:
        return "General Non-Fiction"

    g = raw_genre.lower().strip()
    primary = g.split("/")[0].strip()
    t = title.lower().strip()

    # 1. Law (Check early so compound legal subgenres like 'Tax Law / Real Estate Law' map to Law)
    if any(k in g for k in [
        "tax law", "corporate law", "criminal law", "civil law", "labour law", "labor law",
        "patent law", "medical law", "company law", "legal reference", "legal studies",
        "constitutional law", "legal history", "legal memoir", "jurisprudence", "intellectual property",
        "leases", "securities law", "entertainment law", "gst reference", "finance reference & law"
    ]) or (any(k in primary for k in ["law", "legal"]) and "law of attraction" not in g):
        if "law of attraction" not in g:
            return "Law"

    # 2. Music (Check early so 'Music History / Business', 'Sound Studies' map to Music)
    if any(k in primary for k in ["music", "sound studies", "albums", "records", "beatles"]) or \
       any(k in g for k in [
           "music history", "music theory", "popular music", "music production",
           "sound art", "songwriting", "jazz", "classical music", "rock music", "hip hop",
           "opera", "musicians", "soundtrack"
       ]):
        return "Music"

    # 3. Philosophy (e.g. 'Indian Philosophy', 'Philosophy / History of Philosophy' -> 'Philosophy')
    if any(k in g for k in [
        "philosophy", "philosophical", "aesthetics", "ethics", "epistemology",
        "metaphysics", "existentialism", "stoic", "stoicism", "kantian", "nietzsche",
        "logic", "spinoza", "hegel", "wittgenstein", "heidegger", "socrat"
    ]):
        return "Philosophy"

    # 4. Self-Help / Personal Growth (e.g. 'self-help', 'habits', 'productivity')
    if any(k in g for k in [
        "self-help", "self help", "personal development", "personal growth", "motivation",
        "motivational", "productivity", "habits", "habit formation", "mindset", "life skills",
        "time management", "inspirational", "happiness", "mindfulness", "confidence",
        "career planning", "career guide", "professional growth", "personal reinvention",
        "personal branding", "interpersonal skills", "trust building", "positive thinking",
        "creative thinking", "solitude", "self-discovery", "nlp", "neuro-linguistic"
    ]):
        return "Self-Help"

    # 5. Biography & Memoir (e.g. 'Biography / Cold War History' -> 'Biography')
    if any(k in primary for k in [
        "biography", "autobiography", "memoir", "diaries", "life of", "biographical", "collected letters"
    ]) or any(k in g for k in ["biography", "autobiography", "memoir", "diaries"]):
        return "Biography"

    # 6. History
    if any(k in primary for k in [
        "history", "historical", "historian", "civil war", "world war", "ancient",
        "medieval", "colonial", "archaeology", "antiquity", "empire", "dynasty", "revolution"
    ]):
        return "History"

    # 7. Politics & International Relations
    if any(k in g for k in [
        "international relations", "politics", "political", "geopolitics", "government",
        "public policy", "diplomacy", "foreign policy", "governance", "democracy",
        "communism", "socialism", "public administration", "security studies", "espionage",
        "cold war", "middle eastern studies", "caucasian", "civics", "sociology", "social policy",
        "social criticism", "feminist essays", "public affairs", "social activism", "feminism",
        "human rights", "marxism"
    ]):
        return "Politics"

    # History general fallback
    if any(k in g for k in [
        "history", "historical", "historian", "civil war", "world war", "ancient",
        "medieval", "colonial", "archaeology", "antiquity", "empire", "dynasty", "revolution"
    ]):
        return "History"

    # 8. Business & Economics
    if any(k in g for k in [
        "business", "finance", "financial", "economics", "economic", "investing",
        "investment", "stock market", "management", "marketing", "advertising",
        "entrepreneurship", "leadership", "accounting", "commerce", "corporate",
        "startup", "wealth", "money", "banking", "sales", "real estate", "industry",
        "trade", "taxation", "logistics", "supply chain", "public relations", "social enterprise",
        "innovation", "freelancing", "remote work", "organizational development", "mentorship"
    ]):
        return "Business & Economics"

    # 9. Psychology
    if any(k in g for k in [
        "psychology", "psychological", "psychiatry", "cognitive science", "mental health",
        "psychoanalysis", "behavioral", "behavioural", "counseling", "neurodiversity",
        "autism", "addiction recovery", "trauma", "neuroscience", "cbt"
    ]):
        return "Psychology"

    # Law fallback if 'law' is anywhere in genre string
    if "law" in g and "law of attraction" not in g:
        return "Law"

    # 10. Religion & Spirituality
    if any(k in g for k in [
        "religion", "religious", "spirituality", "spiritual", "theology", "mythology",
        "hinduism", "buddhism", "christianity", "islam", "judaism", "sufism", "meditation",
        "vedic", "gita", "upanishad", "bible", "quran", "scripture", "mysticism", "occult",
        "zen", "sikhism", "jainism", "prayer", "god", "law of attraction", "astrology"
    ]):
        return "Religion & Spirituality"

    # 11. Science & Technology
    if any(k in g for k in [
        "science", "scientific", "physics", "chemistry", "biology", "biological",
        "astronomy", "astrophysics", "mathematics", "math", "computer science",
        "programming", "software", "technology", "artificial intelligence", "machine learning",
        "data science", "cyber", "engineering", "genetics", "evolution", "quantum",
        "nature", "botany", "zoology", "environment", "ecology", "geology", "climate"
    ]):
        return "Science & Technology"

    # 12. Health & Wellness
    if any(k in g for k in [
        "health", "fitness", "medicine", "medical", "nutrition", "diet", "wellness",
        "yoga", "workout", "healing", "exercise", "disease", "anatomy", "physiology",
        "pharmacy", "nursing", "weight loss", "physical therapy", "pilates"
    ]):
        return "Health & Wellness"

    # 13. Cookery & Food
    if any(k in g for k in [
        "cookery", "cooking", "cookbook", "food", "baking", "recipe", "culinary",
        "gastronomy", "wine", "cocktails", "cuisine", "dietary", "dessert"
    ]):
        return "Cookery & Food"

    # 14. Children & Young Adult
    if any(k in g for k in [
        "children", "young adult", "ya", "picture book", "middle grade", "juvenile",
        "teen", "fairy tale", "nursery", "comics", "manga", "graphic novel", "fables"
    ]):
        return "Children & Young Adult"

    # 15. Art & Culture
    if any(k in g for k in [
        "art", "photography", "cinema", "film", "theater", "theatre",
        "design", "architecture", "fashion", "performing arts", "painting", "sculpture",
        "media studies", "journalism", "cultural studies", "broadcasting", "anthropology"
    ]):
        return "Art & Culture"

    # 16. Travel & Adventure
    if any(k in g for k in [
        "travel", "geography", "exploration", "adventure", "outdoors", "mountaineering",
        "expedition", "guidebook", "cartography", "tourism"
    ]):
        return "Travel & Adventure"

    # 17. Education & Reference
    if any(k in g for k in [
        "education", "educational", "reference", "dictionary", "grammar", "textbook",
        "study guide", "pedagogy", "linguistics", "language", "encyclopedia",
        "academic writing", "higher education", "teaching", "school", "rhetoric", "communication",
        "writing guide", "authorship"
    ]):
        return "Education & Reference"

    # 18. Humor & Lifestyle
    if any(k in g for k in [
        "humor", "humour", "comedy", "satire", "jokes", "trivia", "pop culture",
        "games", "puzzles", "lifestyle", "parenting", "relationships", "dating",
        "marriage", "sports", "cricket", "football", "chess", "animals", "pet care"
    ]):
        return "Humor & Lifestyle"

    # 19. Fiction (Romance, Thriller, Mystery, Sci-Fi, Crime, Fantasy, Poetry, Drama, Classics, Literature)
    if any(k in g for k in [
        "fiction", "novel", "thriller", "mystery", "crime", "detective", "romance",
        "sci-fi", "science fiction", "fantasy", "horror", "suspense", "stories",
        "short stories", "drama", "plays", "poetry", "poems", "classics", "classic literature",
        "literary", "literature", "anthology"
    ]):
        return "Fiction"

    return "General Non-Fiction"
