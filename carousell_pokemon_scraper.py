#!/usr/bin/env python3
"""
Carousell Malaysia - Pokemon Card Scraper
Modes: Surface (fast) | Deep (detailed)
Filters: Price range, Condition, Keywords, Seller rating
Exports: JSON + CSV
"""

import asyncio
import json
import re
import csv
import os
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Optional
from playwright.async_api import async_playwright


# ==================== CONFIG ====================

@dataclass
class ScrapeConfig:
    """Edit these settings before running."""
    
    # MODE
    deep_scrape: bool = False           # False = fast surface mode
    max_listings: int = 100             # Cap for deep mode (more = slower)
    max_clicks: int = 30                # "Show more" clicks for surface mode
    
    # FILTERS (leave empty/None to disable)
    min_price: Optional[float] = None   # e.g., 50.0
    max_price: Optional[float] = None   # e.g., 500.0
    conditions: List[str] = None        # e.g., ["Brand new", "Like new"]
    keywords: List[str] = None            # e.g., ["PSA", "Charizard", "holo"]
    require_rating: bool = False          # Only deep mode: skip unrated sellers
    require_protection: bool = False    # Only listings with Buyer Protection
    
    # BROWSER
    headless: bool = True               # False = watch it work (debugging only)

    # SEARCH
    sort_by: str = "3"                  # Carousell sort param. 3 = Recent.
                                        # If the run reports "STILL sorted by
                                        # popular", try "time_created" or "recent".
    max_sane_price: float = 50000.0     # Above this = placeholder, not a real price
    autosave_every: int = 20            # Autosave every N clicks (0 = off)

    # OUTPUT
    output_dir: str = "./carousell_data"
    export_csv: bool = True

    # TROUBLESHOOTING
    block_resources: bool = True        # Set False if the page won't load at all
    debug: bool = False                 # Log failed requests and HTTP 4xx/5xx


# ==================== SCRAPER ====================

class CarousellPokemonScraper:
    def __init__(self, config: ScrapeConfig):
        self.cfg = config
        self.data: List[dict] = []
        self.seen_ids: set = set()
        self._processed_cards: int = 0   # index of last-scanned card (avoids O(n^2))
        self.search_url = (
            "https://www.carousell.com.my/categories/hobbies-toys-6245/toys-games-12/"
            "?search=pokemon%20card&t-search_query_source=ss_dropdown"
            f"&sort_by={self.cfg.sort_by}"
        )
        os.makedirs(self.cfg.output_dir, exist_ok=True)

    async def run(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.cfg.headless,
                slow_mo=0 if self.cfg.headless else 50
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                locale="en-MY",
                timezone_id="Asia/Kuala_Lumpur",
                service_workers="block",   # Carousell is a PWA; its SW serves the
                                           # "Oh no! Unable to download an application
                                           # file" page when a chunk fetch fails.
            )
            # Block heavy resources — NEVER block stylesheet/script/xhr/fetch,
            # they're needed for the SPA to boot.
            if self.cfg.block_resources:
                await context.route("**/*", lambda route, request: (
                    route.abort() if request.resource_type in ["media", "font", "image"]
                    else route.continue_()
                ))
            page = await context.new_page()

            if self.cfg.debug:
                page.on("requestfailed", lambda r: (
                    print(f"   ❌ FAILED [{r.resource_type}] {r.url[:110]}")
                    if self._is_real_failure(r) else None))
                page.on("response", lambda r: (
                    print(f"   ⚠️  HTTP {r.status} {r.url[:110]}")
                    if r.status >= 400 and self._is_real_failure(r) else None))

            print("=" * 60)
            print("🔍 CAROUSELL MALAYSIA - POKEMON CARD SCRAPER")
            print("=" * 60)
            print(f"Mode: {'DEEP' if self.cfg.deep_scrape else 'SURFACE'}")
            print(f"Filters: price={self.cfg.min_price}-{self.cfg.max_price}, "
                  f"conditions={self.cfg.conditions}, keywords={self.cfg.keywords}")
            print("=" * 60)

            # "networkidle" rarely fires on Carousell (constant polling) —
            # wait for the listing cards instead.
            await page.goto(self.search_url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_selector("a[href*='/p/']", timeout=30000)
            except Exception:
                print("\n❌ No listing cards appeared. Dumping page state...")
                await self._dump_debug(page)
                await browser.close()
                return
            await page.wait_for_timeout(2000)
            await self._close_popups(page)
            await self._force_sort_recent(page)

            if self.cfg.deep_scrape:
                await self._deep_scrape(page)
            else:
                await self._surface_scrape(page)

            await browser.close()

        self._apply_filters()
        self._analyze_and_save()

    def _autosave(self):
        """Overwrite a single recovery file so a crash never costs the whole run."""
        try:
            path = f"{self.cfg.output_dir}/_autosave.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)
            print(f"      💾 autosaved {len(self.data)} listings")
        except Exception as e:
            print(f"      ⚠️ autosave failed: {e}")

    # ==================== DEBUG ====================
    async def _dump_debug(self, page):
        """Save screenshot + HTML so you can see what the browser actually got."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shot = f"{self.cfg.output_dir}/debug_{ts}.png"
        html = f"{self.cfg.output_dir}/debug_{ts}.html"
        try:
            await page.screenshot(path=shot, full_page=True)
            with open(html, "w", encoding="utf-8") as f:
                f.write(await page.content())
            body = (await page.inner_text("body"))[:400]
            print(f"   📄 Page text: {body!r}")
            print(f"   📸 Screenshot: {shot}")
            print(f"   📄 HTML:       {html}")
        except Exception as e:
            print(f"   ⚠️ Could not dump debug info: {e}")

    # ==================== POPUPS ====================
    async def _close_popups(self, page):
        selectors = [
            "button[aria-label='Close']", "button[aria-label='close']",
            "[data-testid='close-button']", "[data-testid='modal-close']",
            "button:has-text('Maybe later')", "button:has-text('Not now')",
            "button:has-text('Skip')", "button:has-text('No thanks')",
            "button:has-text('Dismiss')", "button:has-text('Continue in browser')",
            "button:has-text('✕')", "button:has-text('×')",
            "[role='dialog'] button:first-child",
            "div[class*='modal'] button", "div[class*='popup'] button",
            "div[class*='overlay'] button",
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible(timeout=300):
                    await loc.click(timeout=1000)
                    await page.wait_for_timeout(300)
            except:
                continue
        try:
            await page.keyboard.press("Escape")
        except:
            pass

    # Ad networks, trackers, and analytics. Their failures are irrelevant to us.
    NOISE_DOMAINS = (
        "googlesyndication", "doubleclick", "google-analytics", "analytics.google",
        "googletagmanager", "google.com/measurement", "ads/ga-audiences",
        "adtrafficquality", "adsbygoogle", "ssp.yahoo", "criteo", "adnxs",
        "pubmatic", "rubiconproject", "casalemedia", "360yield", "rlcdn",
        "bidswitch", "media.net", "taboola", "outbrain", "teads", "3lift",
        "smartadserver", "clmbtech", "1rx.io", "socdm", "crwdcntrl", "agkn",
        "bing.com/c.gif", "btloader", "tercept", "ecs.carousell.com/event",
        "facebook.com/tr", "ad-score.com", "connect.facebook",
    )

    def _is_real_failure(self, r):
        """Ignore resources WE blocked, plus ad/tracker noise."""
        try:
            if self.cfg.block_resources and r.resource_type in ("media", "font", "image"):
                return False
            url = r.url.lower()
            return not any(d in url for d in self.NOISE_DOMAINS)
        except Exception:
            return True

    # ==================== SORT ====================
    async def _verify_sort(self, page, tries=3):
        """Read the sort mode Carousell ACTUALLY applied.

        Result links carry ?t-referrer_sort_by=<mode>, but those params are
        attached by JS after hydration — reading one link immediately after
        load returns a bare href and yields 'unknown'. So: wait, and sample
        many links rather than just the first.
        """
        for attempt in range(tries):
            try:
                hrefs = await page.locator("a[href*='/p/']").evaluate_all(
                    "els => els.slice(0, 30).map(e => e.getAttribute('href') || '')")
                for h in hrefs:
                    m = re.search(r'(?:t-referrer_)?sort_by=([\w_]+)', h)
                    if m:
                        return m.group(1)
            except Exception:
                pass
            if attempt < tries - 1:
                await page.wait_for_timeout(2500)
        # Fall back to what we asked for in the page URL
        m = re.search(r'[?&]sort_by=([\w_]+)', page.url)
        return f"{m.group(1)} (unconfirmed)" if m else "unknown"

    @staticmethod
    def _sort_ok(applied):
        return any(k in str(applied) for k in ("recent", "time_created", "3"))

    async def _force_sort_recent(self, page):
        print("\n⏳ Applying sort...")
        applied = await self._verify_sort(page)
        if self._sort_ok(applied):
            print(f"   ✅ Sort confirmed: {applied}")
            return True

        print(f"   ⚠️ Page reports sort '{applied}' — clicking the sort control...")
        try:
            sort_btn = page.locator("button").filter(
                has_text=re.compile(r"Sort|Relevant|Popular|Recent", re.I)
            ).first
            if await sort_btn.count() > 0 and await sort_btn.is_visible(timeout=2000):
                await sort_btn.click()
                await page.wait_for_timeout(1500)
                for opt_text in ["Recent", "Latest", "Newest"]:
                    opt = page.get_by_text(re.compile(rf"^{opt_text}$", re.I)).first
                    if await opt.count() > 0 and await opt.is_visible(timeout=1500):
                        await opt.click()
                        await page.wait_for_timeout(4000)
                        break
        except Exception as e:
            print(f"   ⚠️ Sort click error: {e}")

        applied = await self._verify_sort(page)
        if self._sort_ok(applied):
            print(f"   ✅ Sort confirmed: {applied}")
            return True
        print(f"   ❌ Sort reads '{applied}'. Results may NOT be recency-ordered.")
        print("      Continuing anyway — check posted_hours_ago in the output to confirm.")
        print(f"      Try a different self.cfg.sort_by value (current: {self.cfg.sort_by}).")
        return False


    # ==================== SURFACE MODE ====================
    async def _surface_scrape(self, page):
        print("\n📜 SURFACE MODE: Scraping search results...")
        t0 = datetime.now()
        for i in range(self.cfg.max_clicks):
            before = len(self.data)
            await self._extract_surface_cards(page)
            added = len(self.data) - before
            elapsed = (datetime.now() - t0).total_seconds()
            rate = elapsed / (i + 1)
            eta = rate * (self.cfg.max_clicks - i - 1) / 60
            print(f"   Click {i+1}/{self.cfg.max_clicks}: +{added} new | "
                  f"Total: {len(self.data)} | {elapsed/60:.1f}m elapsed, ~{eta:.0f}m left")

            # Autosave — a 75-minute run should never lose everything to a crash
            if self.cfg.autosave_every and (i + 1) % self.cfg.autosave_every == 0:
                self._autosave()

            if added == 0 and i > 2:
                print("   🛑 No new listings. Stopping.")
                break
            
            clicked = await self._click_show_more(page)
            if clicked:
                await page.wait_for_timeout(3000)
                await self._close_popups(page)
            else:
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2500)

    async def _extract_surface_cards(self, page):
        """Extract cards. Walks UP from the /p/ anchor to the real card
        container, because seller + timeAgo live OUTSIDE the anchor.

        Only processes cards appended SINCE the last call. Rescanning the whole
        page every click is O(n^2) — at 2,000 listings that's 2,000 browser
        round-trips to find 47 new ones, and it gets worse every click.
        """
        locator = page.locator("a[href*='/p/']")
        total = await locator.count()
        start = self._processed_cards
        if total <= start:
            return
        cards = (await locator.all())[start:]
        self._processed_cards = total

        for card in cards:
            try:
                href = await card.get_attribute("href") or ""
                if not href:
                    continue

                id_match = re.search(r'/p/[^/]+-(\d+)', href)
                listing_id = id_match.group(1) if id_match else ""
                if not listing_id or listing_id in self.seen_ids:
                    continue

                item = await card.evaluate("""(el) => {
                    const TIME_RE = /(\\d+\\s*(?:s|m|h|d|w|mo|y|seconds?|minutes?|hours?|days?|weeks?|months?|years?)(?:\\s+ago)?)/i;
                    const COND_RE = /(Brand new|Like new|Lightly used|Well used|Heavily used)/i;

                    // ---- STEP 1: climb to the real card container ----
                    // The anchor only holds title/price/image. Seller name and
                    // "x hours ago" sit in a sibling block. Walk up until we
                    // find an ancestor that also contains a /u/ profile link.
                    let card = el, container = el;
                    for (let i = 0; i < 6 && card.parentElement; i++) {
                        card = card.parentElement;
                        const pLinks = card.querySelectorAll("a[href*='/p/']").length;
                        const uLink  = card.querySelector("a[href*='/u/']");
                        if (uLink && pLinks === 1) { container = card; break; }
                        if (pLinks > 1) break;          // went too far, hit the grid
                        container = card;
                    }

                    const aText = el.innerText || '';
                    const cText = container.innerText || '';
                    const aLines = aText.split('\\n').map(l => l.trim()).filter(l => l);
                    const cLines = cText.split('\\n').map(l => l.trim()).filter(l => l);

                    // ---- PRICE (from the anchor only) ----
                    let priceText = '', priceIdx = -1;
                    for (let i = 0; i < aLines.length; i++) {
                        if (aLines[i].match(/^RM\\s?[\\d,]+/)) { priceText = aLines[i]; priceIdx = i; break; }
                    }

                    // ---- TITLE ----
                    const isNoise = (l) => l.match(/^RM/) || l.match(COND_RE) && l.length < 15 ||
                        l.match(TIME_RE) && l.length < 20 || l.toLowerCase().includes('protection');
                    let title = '';
                    if (priceIdx > 0) {
                        for (let i = priceIdx - 1; i >= 0; i--) {
                            if (!isNoise(aLines[i]) && aLines[i].length > 3) { title = aLines[i]; break; }
                        }
                    }
                    if (!title) {
                        for (const l of aLines) {
                            if (!isNoise(l) && l.length > title.length) title = l;
                        }
                    }

                    // ---- SELLER (from the /u/ profile link) ----
                    let seller = '', sellerUrl = '';
                    const uLink = container.querySelector("a[href*='/u/']");
                    if (uLink) {
                        sellerUrl = uLink.href || '';
                        seller = (uLink.innerText || '').trim().split('\\n')[0] || '';
                        if (!seller) {
                            const m = sellerUrl.match(/\\/u\\/([^/?#]+)/);
                            if (m) seller = decodeURIComponent(m[1]);
                        }
                    }
                    if (!seller) {
                        const img = container.querySelector("img[alt]");
                        if (img && img.alt && img.alt.length < 40) seller = img.alt.trim();
                    }

                    // ---- TIME (search container text, not just the anchor) ----
                    let timeAgo = '';
                    const tEl = container.querySelector('time');
                    if (tEl) timeAgo = (tEl.innerText || tEl.getAttribute('datetime') || '').trim();
                    if (!timeAgo) {
                        for (const l of cLines) {
                            if (aLines.includes(l)) continue;
                            const m = l.match(/^(\\d+\\s*(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\\s+ago)$/i)
                                   || l.match(/^(\\d+\\s*(?:s|m|h|d|w|mo|y))$/i);
                            if (m) { timeAgo = m[1]; break; }
                        }
                    }
                    if (!timeAgo) {
                        const m = cText.match(/(\\d+\\s*(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\\s+ago)/i);
                        if (m) timeAgo = m[1];
                    }

                    const cm = cText.match(COND_RE);
                    const condition = cm ? cm[0] : '';
                    const img = (el.querySelector('img') || container.querySelector('img'))?.src || '';
                    const hasBuyerProtection = cText.toLowerCase().includes('buyer protection');

                    return { title, priceText, condition, timeAgo, seller, sellerUrl,
                             hasBuyerProtection, img };
                }""")

                if item and item.get("title") and item.get("priceText"):
                    item["id"] = listing_id
                    item["href"] = href if href.startswith("http") else f"https://www.carousell.com.my{href}"
                    item["scraped_at"] = datetime.now().isoformat()
                    # --- price sanitization ---
                    price, flag = self._clean_price(item.get("priceText"))
                    item["price_numeric"] = price
                    item["price_flag"] = flag
                    item["posted_hours_ago"] = self._parse_time_ago(item.get("timeAgo"))
                    self.seen_ids.add(listing_id)
                    self.data.append(item)
            except Exception:
                continue

    # ==================== SHOW MORE ====================
    async def _click_show_more(self, page):
        for text in ["Show more results", "Show more", "Load more", "More results"]:
            try:
                loc = page.locator(f"button:has-text('{text}')").first
                if await loc.count() > 0 and await loc.is_visible(timeout=1500):
                    await loc.scroll_into_view_if_needed(timeout=3000)
                    await page.wait_for_timeout(300)
                    await loc.click(timeout=5000)
                    return True
            except:
                continue
        return False

    # ==================== DEEP MODE ====================
    async def _deep_scrape(self, page):
        # Phase 1: Collect URLs
        print("\n📜 Phase 1: Collecting listing URLs...")
        urls = []
        cap = self.cfg.max_listings or 9999
        
        for i in range(self.cfg.max_clicks):
            cards = await page.locator("a[href*='/p/']").all()
            before = len(urls)
            
            for card in cards:
                try:
                    href = await card.get_attribute("href")
                    if href:
                        full = href if href.startswith("http") else f"https://www.carousell.com.my{href}"
                        lid = re.search(r'/p/[^/]+-(\d+)', full)
                        if lid and lid.group(1) not in self.seen_ids:
                            self.seen_ids.add(lid.group(1))
                            urls.append(full)
                except:
                    continue
            
            print(f"   Click {i+1}: +{len(urls)-before} new | Total URLs: {len(urls)}")
            
            if len(urls) >= cap:
                urls = urls[:cap]
                print(f"   🛑 Cap reached: {cap}")
                break
            
            if not await self._click_show_more(page):
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2500)
                if len(urls) == before and i > 2:
                    break
            else:
                await page.wait_for_timeout(3000)
                await self._close_popups(page)
        
        # Phase 2: Visit each listing
        print(f"\n🔎 Phase 2: Deep scraping {len(urls)} listings...")
        self.seen_ids.clear()
        
        for idx, url in enumerate(urls, 1):
            print(f"   [{idx:3d}/{len(urls)}] ", end="", flush=True)
            item = await self._scrape_detail_page(page, url)
            if item:
                self.data.append(item)
                print(f"✓ {item.get('title', 'N/A')[:50]}")
            else:
                print("✗ Failed")
            await asyncio.sleep(1.5)
        
        print(f"\n   ✅ Deep scrape complete: {len(self.data)} listings")

    async def _scrape_detail_page(self, page, url):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            await self._close_popups(page)
            
            result = await page.evaluate("""() => {
                const text = document.body.innerText || '';
                
                // Title
                let title = '';
                for (const sel of ['h1', '[data-testid=\"listing-title\"]', 'h2']) {
                    const el = document.querySelector(sel);
                    if (el) { title = el.innerText.trim(); break; }
                }
                
                // Price
                const pm = text.match(/RM[\\s]?([\\d,]+\\.?\\d*)/);
                const priceText = pm ? 'RM' + pm[1] : '';
                
                // Description
                let desc = '';
                for (const sel of ['[data-testid=\"listing-description\"]', '[class*=\"description\"] p', 'p']) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.length > 20) { desc = el.innerText.trim(); break; }
                }
                
                // Condition
                const cm = text.match(/(Brand new|Like new|Lightly used|Well used|Heavily used)/i);
                const condition = cm ? cm[0] : '';
                
                // Seller
                let seller = '', sellerId = '';
                const sl = document.querySelector('a[href*=\"/u/\"]');
                if (sl) {
                    seller = sl.innerText.trim();
                    const m = sl.href.match(/\\/u\\/([^/]+)/);
                    if (m) sellerId = m[1];
                }
                
                // Rating
                const rm = text.match(/([\\d.]+)\\s*\\(\\d+\\s*reviews?\\)/i) || text.match(/([\\d.]+)\\s*★/);
                const rating = rm ? rm[1] : '';
                
                // Location
                const lm = text.match(/Deal at\\s+(.+)/i) || text.match(/Location[:\\s]+(.+)/i);
                const location = lm ? lm[1].trim() : '';
                
                // Images
                const images = Array.from(new Set(
                    Array.from(document.querySelectorAll('img'))
                        .map(img => img.src)
                        .filter(src => src && src.includes('media.karousell.com'))
                ));
                
                // Time
                const te = document.querySelector('time');
                const timePosted = te ? (te.innerText.trim() || te.getAttribute('datetime') || '') : '';
                
                const hasProtection = text.toLowerCase().includes('buyer protection');
                
                return {
                    title, priceText, description: desc, condition,
                    seller, sellerId, rating, location, images,
                    timePosted, hasProtection
                };
            }""")
            
            result["id"] = re.search(r'/p/[^/]+-(\d+)', url).group(1) if re.search(r'/p/[^/]+-(\d+)', url) else ''
            result["href"] = url
            result["scraped_at"] = datetime.now().isoformat()
            return result
            
        except Exception as e:
            return None

    # ==================== FILTERS ====================
    def _apply_filters(self):
        """Apply user-configured filters."""
        if not any([self.cfg.min_price, self.cfg.max_price, self.cfg.conditions,
                    self.cfg.keywords, self.cfg.require_rating, self.cfg.require_protection]):
            return
        
        print("\n🔧 Applying filters...")
        before = len(self.data)
        filtered = []
        
        for d in self.data:
            # Price filter (junk prices are already None — never let them pass)
            price = d.get("price_numeric")
            if price is not None:
                if self.cfg.min_price is not None and price < self.cfg.min_price:
                    continue
                if self.cfg.max_price is not None and price > self.cfg.max_price:
                    continue
            
            # Condition filter
            if self.cfg.conditions:
                cond = d.get("condition", "")
                if cond and cond not in self.cfg.conditions:
                    continue
            
            # Keyword filter
            if self.cfg.keywords:
                text = (d.get("title", "") + " " + d.get("description", "")).lower()
                if not any(kw.lower() in text for kw in self.cfg.keywords):
                    continue
            
            # Rating filter (deep mode only)
            if self.cfg.require_rating and not d.get("rating"):
                continue
            
            # Protection filter
            if self.cfg.require_protection and not d.get("hasBuyerProtection"):
                continue
            
            filtered.append(d)
        
        self.data = filtered
        print(f"   Filtered: {before} → {len(self.data)} listings")

    # ==================== ANALYSIS & SAVE ====================
    # Placeholder prices sellers use to mean "make me an offer".
    JUNK_PRICES = {0.0, 1.0, 111.0, 999.0, 1111.0, 9999.0, 11111.0, 12345.0,
                   99999.0, 111111.0, 123456.0, 123466.0, 999999.0}

    def _clean_price(self, pt):
        """Return (price_or_None, flag). flag: 'ok' | 'junk' | 'unparsed'."""
        raw = self._parse_price(pt)
        if raw is None:
            return None, "unparsed"
        if raw in self.JUNK_PRICES or raw <= 0:
            return None, "junk"
        if raw >= self.cfg.max_sane_price:
            return None, "junk"
        # Repdigit / sequential placeholders: 88888, 1234567, 66666...
        s = str(int(raw))
        if len(s) >= 5 and (len(set(s)) == 1 or s in "1234567890"):
            return None, "junk"
        return raw, "ok"

    def _parse_time_ago(self, t):
        """'3 hours ago' -> 3.0 ; '2 days ago' -> 48.0 ; returns None if unknown."""
        if not t:
            return None
        m = re.search(r'(\d+)\s*(seconds?|minutes?|hours?|days?|weeks?|months?|years?|s|m|h|d|w|mo|y)\b',
                      str(t), re.I)
        if not m:
            return None
        n, unit = float(m.group(1)), m.group(2).lower()
        mult = {"s": 1/3600, "second": 1/3600, "seconds": 1/3600,
                "m": 1/60, "minute": 1/60, "minutes": 1/60,
                "h": 1, "hour": 1, "hours": 1,
                "d": 24, "day": 24, "days": 24,
                "w": 168, "week": 168, "weeks": 168,
                "mo": 720, "month": 720, "months": 720,
                "y": 8760, "year": 8760, "years": 8760}
        return round(n * mult.get(unit, 0), 2) if unit in mult else None

    def _parse_price(self, pt):
        if not pt:
            return None
        try:
            return float(pt.replace("RM", "").replace(",", "").replace(" ", "").strip())
        except:
            return None

    def _analyze_and_save(self):
        if not self.data:
            print("\n❌ No data collected!")
            return
        
        # Enrich / sanitize any records that missed it (deep mode)
        for d in self.data:
            if "price_flag" not in d:
                d["price_numeric"], d["price_flag"] = self._clean_price(d.get("priceText"))
            if "posted_hours_ago" not in d:
                d["posted_hours_ago"] = self._parse_time_ago(
                    d.get("timeAgo") or d.get("timePosted"))

        total = len(self.data)
        prices = [d["price_numeric"] for d in self.data if d.get("price_numeric")]
        junk = sum(1 for d in self.data if d.get("price_flag") == "junk")
        avg = sum(prices) / len(prices) if prices else 0
        med = sorted(prices)[len(prices)//2] if prices else 0

        print("\n" + "=" * 60)
        print(f"📊  FINAL REPORT ({'DEEP' if self.cfg.deep_scrape else 'SURFACE'} MODE)")
        print("=" * 60)
        print(f"🕐 Scraped at:         {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📦 Total Listings:     {total}")
        print(f"💰 Valid Prices:       {len(prices)}")
        print(f"🗑️  Junk/placeholder:   {junk}")
        print(f"💵 MEDIAN Price:       RM {med:,.2f}   <-- use this, not the mean")
        print(f"💵 Mean Price:         RM {avg:,.2f}")
        if prices:
            print(f"📉 Min Price:          RM {min(prices):,.2f}")
            print(f"📈 Max Price:          RM {max(prices):,.2f}")

        seller_n = sum(1 for d in self.data if str(d.get("seller", "")).strip())
        time_n = sum(1 for d in self.data if d.get("posted_hours_ago") is not None)
        print(f"\n📋 Data Quality:")
        print(f"   {'✅' if seller_n/max(total,1) > 0.8 else '❌'} Seller name:     {seller_n}/{total}")
        print(f"   {'✅' if time_n/max(total,1) > 0.8 else '❌'} Time posted:     {time_n}/{total}")
        good_titles = sum(1 for d in self.data if d.get("title") and not str(d["title"]).startswith("RM"))
        print(f"   ✅ Good titles:     {good_titles}/{total}")

        fresh = sum(1 for d in self.data
                    if d.get("posted_hours_ago") is not None and d["posted_hours_ago"] <= 24)
        print(f"   🆕 Posted <24h:     {fresh}/{total}")
        
        if self.cfg.deep_scrape:
            rated = sum(1 for d in self.data if d.get("rating"))
            with_desc = sum(1 for d in self.data if d.get("description"))
            print(f"   ⭐ Rated sellers:   {rated}/{total}")
            print(f"   📝 Descriptions:    {with_desc}/{total}")
        
        # Conditions breakdown
        conds = {}
        for d in self.data:
            c = d.get("condition", "Unknown")
            conds[c] = conds.get(c, 0) + 1
        print(f"\n📊 Condition Breakdown:")
        for c, n in sorted(conds.items(), key=lambda x: -x[1]):
            print(f"   • {c}: {n}")
        
        # Save JSON
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        mode = "deep" if self.cfg.deep_scrape else "surface"
        base = f"{self.cfg.output_dir}/carousell_pokemon_{mode}_{ts}"
        
        json_path = f"{base}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        print(f"\n💾 JSON saved: {json_path}")
        
        # Save CSV
        if self.cfg.export_csv and self.data:
            csv_path = f"{base}.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                fields = []
                for d in self.data:
                    for k in d.keys():
                        if k not in fields:
                            fields.append(k)
                writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(self.data)
            print(f"💾 CSV saved:  {csv_path}")
        
        print("=" * 60)


# ==================== SCHEDULER (Optional) ====================

async def scheduled_scrape(interval_hours=6, config=None):
    """Run scraper repeatedly. Press Ctrl+C to stop."""
    import schedule
    import time
    
    def job():
        print(f"\n{'='*60}")
        print(f"⏰ Scheduled run at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        scraper = CarousellPokemonScraper(config or ScrapeConfig())
        asyncio.run(scraper.run())
    
    schedule.every(interval_hours).hours.do(job)
    print(f"🤖 Scheduler running every {interval_hours} hours. Press Ctrl+C to stop.")
    
    # Run once immediately
    job()
    
    while True:
        schedule.run_pending()
        time.sleep(60)


# ==================== MAIN ====================

if __name__ == "__main__":
    # ===== EDIT YOUR CONFIG HERE =====
    
    cfg = ScrapeConfig(
        # MODE
        deep_scrape=False,           # True = click every listing (slow but detailed)
        max_listings=50,             # Deep mode: how many listings to visit
        max_clicks=200,              # Surface mode: 200 x 48 = ~9,600 ceiling.
                                     # Loop exits early when a batch returns
                                     # nothing new, so this is a cap, not a target.
        
        # FILTERS (optional)
        # min_price=50.0,            # Minimum RM price
        # max_price=1000.0,          # Maximum RM price
        # conditions=["Brand new", "Like new"],  # Only these conditions
        # keywords=["PSA", "Charizard", "holo"],  # Must contain one of these
        # require_rating=False,      # Deep mode only: skip unrated sellers
        # require_protection=False,  # Only listings with Buyer Protection
        
        # OUTPUT
        output_dir="./carousell_data",
        export_csv=True,

        # BROWSER
        headless=True,               # False if you want to watch the window
        autosave_every=10,           # Recovery file every 10 clicks

        # TROUBLESHOOTING
        block_resources=True,        # Set False if the page still won't load
        debug=True,                  # Prints failed requests + 4xx/5xx responses
    )
    
    # RUN ONCE
    scraper = CarousellPokemonScraper(cfg)
    asyncio.run(scraper.run())
    
    # OR RUN SCHEDULED (uncomment below, comment out the two lines above)
    # asyncio.run(scheduled_scrape(interval_hours=6, config=cfg))
