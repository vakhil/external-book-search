/**
 * Bookmark - External Book Search & Genre Explorer Frontend Controller
 * Strictly tailored for fast book search and genre-wise browsing.
 */

// Global State
let currentTab = 'tabSearch';
let searchDebounceTimer = null;
let currentSearchType = 'title';
let searchAbortController = null;
let searchSeqCounter = 0;
const clientSearchCache = new Map();
const coverCache = new Map();
const bookSummaryCache = new Map();
let lazyCoverObserver = null;

// Genre tab state
let allLoadedGenreBooks = [];
let genreDataLoaded = false;
let availableGenresList = [];
let selectedGenresSet = new Set();

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  const safeInit = (fnName, fn) => {
    try { fn(); } catch (err) { console.error(`Notice in ${fnName}:`, err); }
  };

  safeInit('initTabs', initTabs);
  safeInit('initSearch', initSearch);
  safeInit('initGenreTab', initGenreTab);
  safeInit('initAdvisorTab', initAdvisorTab);

  // Initial load
  fetchLightweightStats();
});

/* =========================================================================
   1. TABS CONTROLLER
   ========================================================================= */

function initTabs() {
  const allTabButtons = document.querySelectorAll('.tab-btn[data-tab]');
  allTabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const tabId = btn.getAttribute('data-tab');
      switchMainTab(tabId);
    });
  });

  // Middle pillar button smooth scrolling to search workspace and focusing input
  const btnJump = document.getElementById('btnJumpToSearch');
  if (btnJump) {
    btnJump.addEventListener('click', () => {
      switchMainTab('tabSearch');
      const ws = document.getElementById('searchWorkspace');
      if (ws) {
        ws.scrollIntoView({ behavior: 'smooth' });
      }
      setTimeout(() => {
        const inp = document.getElementById('searchInput');
        if (inp) inp.focus();
      }, 350);
    });
  }
}

function switchMainTab(tabId) {
  const allTabButtons = document.querySelectorAll('.tab-btn[data-tab]');
  allTabButtons.forEach(b => {
    if (b.getAttribute('data-tab') === tabId) {
      b.classList.add('active');
    } else {
      b.classList.remove('active');
    }
  });

  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  const target = document.getElementById(tabId);
  if (target) target.classList.add('active');
  currentTab = tabId;

  if (tabId === 'tabGenre') loadGenreTab();
  if (tabId === 'tabAdvisor') {
    const ainp = document.getElementById('advisorQuestionInput');
    if (ainp) ainp.focus();
  }
  if (tabId === 'tabSearch') {
    const sinp = document.getElementById('searchInput');
    if (sinp) sinp.focus();
  }
}

function safeSet(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

async function fetchLightweightStats() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    if (data.stats && data.stats.total_copies) {
      safeSet('headerTotalCopies', `${data.stats.total_copies.toLocaleString()} copies in store`);
    } else {
      safeSet('headerTotalCopies', 'Live Inventory');
    }
  } catch (err) {
    safeSet('headerTotalCopies', 'Live Inventory');
  }
}

/* =========================================================================
   2. INTELLIGENT SEARCH CONTROLLER
   ========================================================================= */

function initSearch() {
  const input = document.getElementById('searchInput');
  const clearBtn = document.getElementById('btnClearSearch');
  const modePills = document.querySelectorAll('.search-mode-pill');

  // Search Mode Selector Buttons
  modePills.forEach(pill => {
    pill.addEventListener('click', () => {
      modePills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      currentSearchType = pill.getAttribute('data-type');

      if (currentSearchType === 'author') {
        input.placeholder = "Search by author's name (e.g. Robin Sharma, Chetan Bhagat)...";
      } else {
        input.placeholder = 'Search by book title (e.g. Awaken the Giant Within)...';
      }

      input.focus();
      if (input.value.trim()) {
        performSearch(input.value);
      }
    });
  });

  // Debounced Search Input
  input.addEventListener('input', (e) => {
    const val = e.target.value;
    clearBtn.style.display = val ? 'block' : 'none';

    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
      performSearch(val);
    }, 120);
  });

  // Clear Search Field
  clearBtn.addEventListener('click', () => {
    input.value = '';
    clearBtn.style.display = 'none';
    const container = document.getElementById('searchResultsContainer');
    container.innerHTML = `
      <div class="empty-prompt">
        <div class="prompt-icon">📖</div>
        <h3>Find Any Book Instantly</h3>
        <p>Type a book title or author to browse matching books.</p>
      </div>
    `;
    input.focus();
  });

  // Setup voice search
  setupVoiceSearch();
}

function setupVoiceSearch() {
  const btnMic = document.getElementById('btnVoiceSearch');
  const btnVoiceAction = document.getElementById('btnVoiceSearchAction');
  const statusNotice = document.getElementById('voiceSearchStatusNotice');
  const statusText = document.getElementById('voiceSearchStatusText');
  const searchInput = document.getElementById('searchInput');

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    const hideOrWarn = (btn) => {
      if (!btn) return;
      btn.addEventListener('click', () => {
        alert('Voice search is not supported in this browser. Please use Chrome, Safari, or Edge.');
      });
    };
    hideOrWarn(btnMic);
    hideOrWarn(btnVoiceAction);
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'en-US';

  let isListening = false;

  const startListening = () => {
    if (isListening) {
      recognition.stop();
      return;
    }
    try {
      recognition.start();
      isListening = true;
      if (btnMic) btnMic.classList.add('mic-active');
      if (statusNotice) {
        statusNotice.style.display = 'flex';
        if (statusText) statusText.textContent = 'Listening... Speak book title or author now';
      }
    } catch (err) {
      console.warn('Speech recognition start notice:', err);
    }
  };

  if (btnMic) btnMic.addEventListener('click', startListening);
  if (btnVoiceAction) btnVoiceAction.addEventListener('click', startListening);

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    if (searchInput) {
      searchInput.value = transcript;
      const clearBtn = document.getElementById('btnClearSearch');
      if (clearBtn) clearBtn.style.display = 'block';
      performSearch(transcript);
    }
  };

  recognition.onerror = (event) => {
    isListening = false;
    if (btnMic) btnMic.classList.remove('mic-active');
    if (statusNotice) {
      if (statusText) statusText.textContent = `Voice recognition error: ${event.error}`;
      setTimeout(() => { statusNotice.style.display = 'none'; }, 2500);
    }
  };

  recognition.onend = () => {
    isListening = false;
    if (btnMic) btnMic.classList.remove('mic-active');
    if (statusNotice) statusNotice.style.display = 'none';
  };
}

function clearSearchCache() {
  clientSearchCache.clear();
}

function performSearch(query) {
  const container = document.getElementById('searchResultsContainer');
  const cleanQ = (query || '').trim();
  if (!cleanQ) {
    if (searchAbortController) {
      searchAbortController.abort();
      searchAbortController = null;
    }
    const hint = currentSearchType === 'author' 
      ? "Enter an author's name above to see all their books." 
      : "Enter a book title above to find matching books in stock.";
    container.innerHTML = `<div class="empty-state-card">${hint}</div>`;
    return;
  }

  const cacheKey = `${currentSearchType}:${cleanQ.toLowerCase()}`;
  if (clientSearchCache.has(cacheKey)) {
    renderSearchResults(clientSearchCache.get(cacheKey));
    return;
  }

  if (searchAbortController) {
    searchAbortController.abort();
  }
  searchAbortController = new AbortController();
  const currentSeq = ++searchSeqCounter;

  if (!container.querySelector('.book-card')) {
    container.innerHTML = '<div class="photo-meta">⚡ Searching live inventory records...</div>';
  }

  fetch(
    `/api/search?q=${encodeURIComponent(cleanQ)}&type=${encodeURIComponent(currentSearchType)}`,
    { signal: searchAbortController.signal }
  )
    .then(res => res.json())
    .then(data => {
      if (currentSeq !== searchSeqCounter) return;

      clientSearchCache.set(cacheKey, data);
      if (clientSearchCache.size > 100) {
        const firstKey = clientSearchCache.keys().next().value;
        clientSearchCache.delete(firstKey);
      }

      renderSearchResults(data);
    })
    .catch(err => {
      if (err.name === 'AbortError') return;
      if (currentSeq !== searchSeqCounter) return;
      container.innerHTML = `<div class="alert alert-danger">Error searching inventory: ${escapeHtml(err.message)}</div>`;
    });
}

function renderSearchResults(data) {
  const container = document.getElementById('searchResultsContainer');
  container.innerHTML = '';

  const { exact_matches, query, search_type } = data;

  if (!exact_matches || exact_matches.length === 0) {
    const typeLabel = search_type === 'author' ? 'author' : (search_type === 'title' ? 'title' : 'books');
    container.innerHTML = `
      <div class="empty-prompt">
        <div class="prompt-icon">🔍</div>
        <h3>No ${typeLabel} found matching "${escapeHtml(query)}"</h3>
        <p>Check spelling or search by another keyword.</p>
      </div>
    `;
    return;
  }

  // Count total physical copies across all matching titles
  let totalCopiesCount = 0;
  exact_matches.forEach(m => {
    totalCopiesCount += (m.copies && m.copies.length > 0) ? m.copies.length : 1;
  });

  let badgeText = 'EXACT MATCH';
  const shownText = (data.total_exact_count && data.total_exact_count > exact_matches.length)
    ? `${totalCopiesCount} shown of ${data.total_exact_count} total`
    : `${totalCopiesCount}`;
  let categoryTitle = `Matching Books (${shownText})`;
  if (search_type === 'author') {
    badgeText = 'AUTHOR MATCH';
    categoryTitle = `✍️ Books by Author "${escapeHtml(query)}" (${shownText})`;
  } else if (search_type === 'title') {
    badgeText = 'TITLE MATCH';
    categoryTitle = `📖 Books Matching Title "${escapeHtml(query)}" (${shownText})`;
  }

  const block = document.createElement('div');
  block.className = 'results-category-block';
  block.innerHTML = `
    <div class="category-header exact-header">
      <span class="badge badge-success">${badgeText}</span>
      <h3 class="category-title">${categoryTitle}</h3>
    </div>
  `;
  const fragment = document.createDocumentFragment();
  exact_matches.forEach(item => {
    fragment.appendChild(createBookCard(item, 'exact'));
  });
  block.appendChild(fragment);
  container.appendChild(block);
  resolveLazyCovers();
}

function getGenreGradient(genre) {
  const g = (genre || '').toLowerCase();
  if (g.includes('fic') || g.includes('novel') || g.includes('lit') || g.includes('stor')) return 'linear-gradient(135deg, #7c3aed, #4f46e5)';
  if (g.includes('sci') || g.includes('tech') || g.includes('comp') || g.includes('math')) return 'linear-gradient(135deg, #0d9488, #0891b2)';
  if (g.includes('hist') || g.includes('bio') || g.includes('memoir') || g.includes('polit')) return 'linear-gradient(135deg, #d97706, #b45309)';
  if (g.includes('mys') || g.includes('thrill') || g.includes('crime') || g.includes('dark')) return 'linear-gradient(135deg, #334155, #1e293b)';
  if (g.includes('child') || g.includes('ya') || g.includes('comic') || g.includes('manga')) return 'linear-gradient(135deg, #db2777, #e11d48)';
  if (g.includes('self') || g.includes('spirit') || g.includes('phil') || g.includes('health') || g.includes('yoga')) return 'linear-gradient(135deg, #059669, #047857)';
  return 'linear-gradient(135deg, #2563eb, #1d4ed8)';
}

function getBookCoverHtml(title, author, genre, imageUrl) {
  const safeTitle = escapeHtml(title || 'Book');
  const safeAuthor = escapeHtml(author || '');
  const safeGenre = escapeHtml(genre || '');
  const bg = getGenreGradient(genre);

  const effectiveUrl = imageUrl || coverCache.get(safeTitle.toLowerCase());

  if (effectiveUrl) {
    return `
      <div class="book-cover-container" title="${safeTitle} by ${safeAuthor}">
        <img src="${escapeHtml(effectiveUrl)}" alt="${safeTitle}" class="book-cover-img" loading="lazy"
             onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='flex';" />
        <div class="book-cover-placeholder" style="display:none; background:${bg};">
          <span class="placeholder-icon">📖</span>
          <span class="placeholder-genre">${safeGenre || 'Book'}</span>
        </div>
      </div>
    `;
  }

  return `
    <div class="book-cover-container" data-lazy-title="${safeTitle}" data-lazy-author="${safeAuthor}" title="${safeTitle} by ${safeAuthor}">
      <div class="book-cover-placeholder" style="background:${bg};">
        <span class="placeholder-icon">📖</span>
        <span class="placeholder-genre">${safeGenre || 'Book'}</span>
      </div>
    </div>
  `;
}

function resolveLazyCovers() {
  if (!('IntersectionObserver' in window)) return;
  if (!lazyCoverObserver) {
    lazyCoverObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        const container = entry.target;
        lazyCoverObserver.unobserve(container);

        if (container.getAttribute('data-resolving') || container.getAttribute('data-resolved')) return;
        const title = container.getAttribute('data-lazy-title');
        const author = container.getAttribute('data-lazy-author') || '';
        if (!title) return;

        if (coverCache.has(title.toLowerCase())) {
          applyCoverToContainer(container, coverCache.get(title.toLowerCase()), title);
          return;
        }

        container.setAttribute('data-resolving', 'true');
        fetch(`/api/books/cover?title=${encodeURIComponent(title)}&author=${encodeURIComponent(author)}`)
          .then(res => res.json())
          .then(data => {
            if (data && data.cover_url) {
              coverCache.set(title.toLowerCase(), data.cover_url);
              applyCoverToContainer(container, data.cover_url, title);
            } else {
              container.removeAttribute('data-resolving');
              container.setAttribute('data-resolved', 'true');
            }
          })
          .catch(() => {
            container.removeAttribute('data-resolving');
          });
      });
    }, { rootMargin: '100px 0px' });
  }

  document.querySelectorAll('.book-cover-container[data-lazy-title]:not([data-resolved]):not([data-resolving])').forEach(el => {
    lazyCoverObserver.observe(el);
  });
}

function applyCoverToContainer(container, coverUrl, title) {
  container.removeAttribute('data-resolving');
  container.setAttribute('data-resolved', 'true');
  if (coverUrl) {
    const existingImg = container.querySelector('.book-cover-img');
    if (existingImg) existingImg.remove();

    const img = document.createElement('img');
    img.src = coverUrl;
    img.alt = title;
    img.className = 'book-cover-img';
    img.loading = 'lazy';
    img.onerror = () => {
      img.remove();
      const ph = container.querySelector('.book-cover-placeholder');
      if (ph) ph.style.display = 'flex';
    };
    container.insertBefore(img, container.firstChild);
    const ph = container.querySelector('.book-cover-placeholder');
    if (ph) ph.style.display = 'none';
  }
}

function cleanBookTitle(rawTitle) {
  if (!rawTitle) return '';
  return String(rawTitle).trim();
}

function getBookState(book, copy) {
  const s = ((copy && copy.status) || (book && book.status) || '').toUpperCase();
  if (s === 'SOLD') return 'SOLD';
  return 'ASSIGNED';
}

function formatAvailabilityBadge(state) {
  if (state === 'SOLD') {
    return `<span class="state-chip state-sold"><span class="chip-dot"></span> Out of Stock</span>`;
  }
  return `<span class="state-chip state-assigned"><span class="chip-dot"></span> In Stock</span>`;
}

function fetchBookSummary(title, author, bookId) {
  const cleanT = (title || '').trim();
  const cleanA = (author || '').trim();
  const cleanB = (bookId || '').trim();
  const cacheKey = (cleanB || cleanT).toLowerCase();
  if (!cacheKey) return Promise.resolve('');
  if (bookSummaryCache.has(cacheKey)) {
    return Promise.resolve(bookSummaryCache.get(cacheKey));
  }
  return fetch(`/api/books/summary?title=${encodeURIComponent(cleanT)}&author=${encodeURIComponent(cleanA)}&book_id=${encodeURIComponent(cleanB)}`)
    .then(res => res.json())
    .then(data => {
      if (data && data.summary) {
        bookSummaryCache.set(cacheKey, data.summary);
        if (cleanT) bookSummaryCache.set(cleanT.toLowerCase(), data.summary);
        if (cleanB) bookSummaryCache.set(cleanB.toLowerCase(), data.summary);
        return data.summary;
      }
      return '';
    })
    .catch(() => '');
}

/**
 * Creates a clean, read-only tile for one physical book copy.
 */
function createBookTile(book, copy, matchType) {
  const card = document.createElement('div');
  card.className = 'book-card-item';

  const state = getBookState(book, copy);
  let cardClass = 'book-card-item';
  if (state === 'SOLD') cardClass += ' card-is-sold';
  else if (state === 'UNASSIGNED') cardClass += ' card-is-unassigned';
  else cardClass += ' card-is-assigned';
  card.className = cardClass;

  const cleanTitle = cleanBookTitle(copy.title || book.title || '');
  const cleanAuthor = escapeHtml(copy.author || book.author || 'Author');
  const genre = copy.simple_genre || book.simple_genre || copy.genre || book.genre || '';
  const coverHtml = getBookCoverHtml(cleanTitle, copy.author || book.author, genre, copy.image_url || book.image_url);
  const bookId = copy.book_id || book.book_id || '';
  const language = copy.language || book.language || 'English';
  const sellingPrice = (copy.selling_price !== null && copy.selling_price !== undefined && copy.selling_price !== '') ? copy.selling_price : (book.selling_price || '');
  const existingSummary = copy.summary || book.summary || bookSummaryCache.get(cleanTitle.toLowerCase()) || '';

  card.innerHTML = `
    <div class="book-card-main">
      <div class="book-card-header-left">
        <div class="book-cover-3d-wrap">
          ${coverHtml}
        </div>
        <div class="book-info">
          <h3 class="book-title" style="margin: 0 0 0.2rem 0; line-height: 1.3;">${escapeHtml(cleanTitle)}</h3>
          <div class="book-author">
            <span class="author-prefix">by</span>
            <b>${cleanAuthor}</b>
          </div>
          <div class="book-meta-line" style="margin-top: 0.5rem;">
            ${formatAvailabilityBadge(state)}
            <span class="chip book-lang-chip">🌐 ${escapeHtml(language)}</span>
            ${genre ? `<span class="chip simple-genre-chip">${escapeHtml(genre)}</span>` : ''}
            ${sellingPrice ? `<span class="chip" style="background:#f0fdf4; color:#166534; font-weight:700;">₹${escapeHtml(sellingPrice)}</span>` : ''}
          </div>
        </div>
      </div>
    </div>
    <div class="book-card-expanded-area">
      <div class="book-summary-box">
        <div class="synopsis-header-row">
          <strong style="color: #0f172a; display: flex; align-items: center; gap: 0.4rem; font-size: 0.88rem;">
            <span>📖</span> In-Depth Synopsis &amp; Analysis
          </strong>
          <span class="synopsis-badge">✨ 150–400 Words &bull; Editorial Synopsis</span>
        </div>
        <div class="book-summary-text">${existingSummary ? escapeHtml(existingSummary).replace(/\n\n/g, '<br><br>') : '<em style="color:#64748b;">Loading comprehensive 300-400 word synopsis...</em>'}</div>
      </div>
    </div>
  `;

  // Always pre-load full synopsis into card if not already rendered
  if (!existingSummary) {
    fetchBookSummary(cleanTitle, cleanAuthor, bookId).then(sum => {
      if (sum) {
        copy.summary = sum;
        book.summary = sum;
        const sumEl = card.querySelector('.book-summary-text');
        if (sumEl) {
          sumEl.innerHTML = escapeHtml(sum).replace(/\n\n/g, '<br><br>');
        }
      }
    });
  }

  // Hover on tile to set quick browser tooltip
  card.addEventListener('mouseenter', () => {
    const existing = copy.summary || book.summary || bookSummaryCache.get(cleanTitle.toLowerCase());
    if (existing) {
      card.setAttribute('title', `📖 ${cleanTitle} by ${cleanAuthor}\n\n${existing.slice(0, 300)}...`);
    } else {
      fetchBookSummary(cleanTitle, cleanAuthor, bookId).then(sum => {
        if (sum) {
          copy.summary = sum;
          book.summary = sum;
          card.setAttribute('title', `📖 ${cleanTitle} by ${cleanAuthor}\n\n${sum.slice(0, 300)}...`);
          const sumEl = card.querySelector('.book-summary-text');
          if (sumEl && sumEl.innerHTML.includes('Loading comprehensive')) {
            sumEl.innerHTML = escapeHtml(sum).replace(/\n\n/g, '<br><br>');
          }
        }
      });
    }
  });

  // Card click to expand / select
  card.addEventListener('click', () => {
    const wasSelected = card.classList.contains('is-selected');
    document.querySelectorAll('.book-card-item.is-selected').forEach(c => {
      if (c !== card) c.classList.remove('is-selected');
    });
    if (wasSelected) {
      card.classList.remove('is-selected');
    } else {
      card.classList.add('is-selected');
      const sumEl = card.querySelector('.book-summary-text');
      if (sumEl && (sumEl.innerHTML.includes('Loading comprehensive') || !copy.summary)) {
        fetchBookSummary(cleanTitle, cleanAuthor, bookId).then(sum => {
          if (sum && sumEl) {
            sumEl.innerHTML = escapeHtml(sum).replace(/\n\n/g, '<br><br>');
            copy.summary = sum;
            book.summary = sum;
          }
        });
      }
    }
  });

  return card;
}

function createBookCard(bookGroup, matchType) {
  const fragment = document.createDocumentFragment();
  const copies = (bookGroup.copies && bookGroup.copies.length > 0) ? bookGroup.copies : [bookGroup];
  copies.forEach(copy => {
    fragment.appendChild(createBookTile(bookGroup, copy, matchType));
  });
  return fragment;
}

/* =========================================================================
   3. GENRE TAB CONTROLLER
   ========================================================================= */

async function loadGenreTab() {
  if (genreDataLoaded && availableGenresList.length > 0) return;
  try {
    const res = await fetch('/api/genres');
    const data = await res.json();
    const select = document.getElementById('genreSelect');
    const pillsWrap = document.getElementById('quickGenrePills');
    if (!select || !data.genres) return;

    availableGenresList = data.genres || [];
    select.innerHTML = '<option value="">-- Choose a Single Genre --</option>';
    if (pillsWrap) pillsWrap.innerHTML = '';

    availableGenresList.forEach(g => {
      const opt = document.createElement('option');
      opt.value = g.simple_genre;
      opt.textContent = `${g.simple_genre} (${g.total_copies.toLocaleString()} copies)`;
      select.appendChild(opt);

      // Add interactive collector pill
      if (pillsWrap) {
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.className = 'quick-genre-pill';
        pill.setAttribute('data-genre', g.simple_genre);
        pill.innerHTML = `<span>${escapeHtml(g.simple_genre)}</span> <small style="opacity:0.75; font-size:0.72rem; margin-left:3px;">(${g.total_copies})</small>`;
        
        pill.addEventListener('click', () => {
          toggleGenreSelection(g.simple_genre);
        });
        pillsWrap.appendChild(pill);
      }
    });

    genreDataLoaded = true;
    updateGenrePillsUI();
  } catch (err) {
    console.error('Failed to load genres list:', err);
  }
}

function updateGenrePillsUI() {
  const pillsWrap = document.getElementById('quickGenrePills');
  const countLabel = document.getElementById('genreSelectedCountLabel');
  const select = document.getElementById('genreSelect');

  if (pillsWrap) {
    pillsWrap.querySelectorAll('.quick-genre-pill').forEach(pill => {
      const g = pill.getAttribute('data-genre');
      if (selectedGenresSet.has(g)) {
        pill.classList.add('active');
        pill.style.background = '#4f46e5';
        pill.style.color = '#ffffff';
        pill.style.borderColor = '#4338ca';
      } else {
        pill.classList.remove('active');
        pill.style.background = '#f1f5f9';
        pill.style.color = '#334155';
        pill.style.borderColor = '#cbd5e1';
      }
    });
  }

  if (countLabel) {
    if (selectedGenresSet.size > 0) {
      countLabel.style.display = 'inline-block';
      countLabel.textContent = `${selectedGenresSet.size} genre${selectedGenresSet.size === 1 ? '' : 's'} collected`;
    } else {
      countLabel.style.display = 'none';
    }
  }

  if (select) {
    if (selectedGenresSet.size === 1) {
      select.value = Array.from(selectedGenresSet)[0];
    } else {
      select.value = '';
    }
  }
}

function toggleGenreSelection(genreName) {
  if (!genreName) return;
  if (selectedGenresSet.has(genreName)) {
    selectedGenresSet.delete(genreName);
  } else {
    selectedGenresSet.add(genreName);
  }
  updateGenrePillsUI();
  fetchBooksForCollectedGenres();
}

async function fetchBooksForCollectedGenres() {
  const container = document.getElementById('genreBooksContainer');
  if (!container) return;

  if (selectedGenresSet.size === 0) {
    allLoadedGenreBooks = [];
    container.innerHTML = `
      <div class="empty-prompt">
        <div class="prompt-icon">🏷️</div>
        <h3>Select or Collect Genres Above</h3>
        <p>Click any common genre pill above (e.g. <b>Fiction</b>, <b>Philosophy</b>, <b>History</b>, <b>Self-Help</b>) to collect and browse all matching books.</p>
      </div>
    `;
    safeSet('genreBooksCountBadge', '0 Books');
    return;
  }

  const genresArr = Array.from(selectedGenresSet);
  const displayNames = genresArr.length <= 3 
    ? genresArr.join(', ')
    : `${genresArr.slice(0, 2).join(', ')} and ${genresArr.length - 2} more`;

  container.innerHTML = `<div class="empty-prompt"><p>Loading books in ${escapeHtml(displayNames)}...</p></div>`;

  try {
    const genreParam = genresArr.join(',');
    const res = await fetch(`/api/books/by-genre?genre=${encodeURIComponent(genreParam)}&available_only=true&limit=1000`);
    const data = await res.json();
    allLoadedGenreBooks = data.books || [];
    renderFilteredGenreBooks();
  } catch (err) {
    console.error('Failed to load books by genre:', err);
    container.innerHTML = '<div class="empty-prompt"><p style="color:var(--danger)">Failed to load books for selected genres.</p></div>';
  }
}

function renderFilteredGenreBooks() {
  const container = document.getElementById('genreBooksContainer');
  const filterVal = (document.getElementById('genreFilterInput')?.value || '').toLowerCase().trim();

  let filtered = allLoadedGenreBooks;
  if (filterVal) {
    filtered = allLoadedGenreBooks.filter(b => 
      (b.title && b.title.toLowerCase().includes(filterVal)) || 
      (b.author && b.author.toLowerCase().includes(filterVal)) ||
      (b.genre && b.genre.toLowerCase().includes(filterVal)) ||
      (b.simple_genre && b.simple_genre.toLowerCase().includes(filterVal))
    );
  }

  let totalCopies = 0;
  filtered.forEach(b => {
    totalCopies += (b.copies && b.copies.length > 0) ? b.copies.length : 1;
  });
  safeSet('genreBooksCountBadge', `${totalCopies} Book${totalCopies === 1 ? '' : 's'}`);

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-prompt">
        <div class="prompt-icon">📖</div>
        <h3>No Matching Books Found</h3>
        <p>No books in the collected genres match your search filter.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = '';
  filtered.forEach(bookGroup => {
    container.appendChild(createBookCard(bookGroup, 'genre'));
  });
  resolveLazyCovers();
}

function initGenreTab() {
  const select = document.getElementById('genreSelect');
  if (select) {
    select.addEventListener('change', (e) => {
      const g = e.target.value;
      if (g) {
        selectedGenresSet.clear();
        selectedGenresSet.add(g);
      } else {
        selectedGenresSet.clear();
      }
      updateGenrePillsUI();
      fetchBooksForCollectedGenres();
    });
  }

  const filterInp = document.getElementById('genreFilterInput');
  if (filterInp) {
    filterInp.addEventListener('input', () => {
      renderFilteredGenreBooks();
    });
  }

  const btnSelectAll = document.getElementById('btnSelectAllGenres');
  if (btnSelectAll) {
    btnSelectAll.addEventListener('click', () => {
      if (availableGenresList.length === 0) return;
      selectedGenresSet = new Set(availableGenresList.map(g => g.simple_genre));
      updateGenrePillsUI();
      fetchBooksForCollectedGenres();
    });
  }

  const btnClearAll = document.getElementById('btnClearGenreSelection');
  if (btnClearAll) {
    btnClearAll.addEventListener('click', () => {
      selectedGenresSet.clear();
      updateGenrePillsUI();
      fetchBooksForCollectedGenres();
    });
  }
}

/* =========================================================================
   4. AI ADVISOR CONTROLLER
   ========================================================================= */

function initAdvisorTab() {
  const btnAsk = document.getElementById('btnAskAdvisor');
  const inputQ = document.getElementById('advisorQuestionInput');

  async function submitQuestion(questionText) {
    const q = (questionText || inputQ?.value || '').trim();
    if (!q) return;

    if (inputQ) inputQ.value = q;

    const container = document.getElementById('advisorResultsContainer');
    const summaryBanner = document.getElementById('advisorSummaryBanner');
    const summaryText = document.getElementById('advisorSummaryText');

    container.innerHTML = `
      <div class="empty-prompt">
        <div style="font-size:2.2rem; animation: pulse 1.5s infinite;">✨</div>
        <h3 style="margin-top:0.5rem;">Advisor Thinking...</h3>
        <p>Analyzing in-depth synopses across our collection to craft your personalized recommendations.</p>
      </div>
    `;
    if (summaryBanner) summaryBanner.style.display = 'none';

    try {
      const res = await fetch('/api/ask-recommendations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q })
      });
      const data = await res.json();

      if (summaryBanner && summaryText && data.answer) {
        summaryText.innerHTML = escapeHtml(data.answer).replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
        summaryBanner.style.display = 'block';
      }

      if (!data.books || data.books.length === 0) {
        container.innerHTML = `
          <div class="empty-prompt">
            <div class="prompt-icon">🔍</div>
            <h3>No Direct Recommendations Found</h3>
            <p>Try rephrasing your question or browse our <b>Browse by Genre</b> tab.</p>
          </div>
        `;
        return;
      }

      container.innerHTML = '';
      data.books.forEach(item => {
        container.appendChild(createBookCard(item, 'recommendation'));
      });
      resolveLazyCovers();
    } catch (err) {
      console.error('Error fetching recommendations:', err);
      container.innerHTML = `
        <div class="empty-prompt">
          <p style="color:var(--danger)">Failed to process recommendation request.</p>
        </div>
      `;
    }
  }

  if (btnAsk) {
    btnAsk.addEventListener('click', () => submitQuestion());
  }

  if (inputQ) {
    inputQ.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        submitQuestion();
      }
    });
  }

  // Example question pills
  document.querySelectorAll('.example-question-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      const q = pill.getAttribute('data-q');
      if (q) submitQuestion(q);
    });
  });
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
