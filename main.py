#!/usr/bin/env python3
# ╔══════════════════════════════════════════════════════════╗
# ║              🎌  ANIME FINDER BOT  v2.0                  ║
# ║  • Koi bhi API Key NAHI chahiye — 100% Free              ║
# ║  • Sources : Jikan (MAL) + AniList GraphQL               ║
# ║  • Languages : Hindi, English, Japanese, Korean, + more  ║
# ║  • Features : Search, Top, Seasonal, Random, Genre       ║
# ╚══════════════════════════════════════════════════════════╝

import os, re, asyncio, logging, random, html
from functools import wraps
from typing import Optional

import aiohttp
from langdetect import detect as _detect
from deep_translator import GoogleTranslator

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter

# ══════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "8284660598:AAGNQDMtd3fBKv4vz08BIcATN2e_CjvpWmU")
JIKAN       = "https://api.jikan.moe/v4"
ANILIST     = "https://graphql.anilist.co"
TIMEOUT     = aiohttp.ClientTimeout(total=15)

WATCH_SITES = [
    ("🟠 Crunchyroll",  "https://crunchyroll.com"),
    ("🔵 AniWatch",     "https://aniwatch.to"),
    ("🟣 AnimePahe",    "https://animepahe.ru"),
    ("🟢 Gogoanime",    "https://gogoanime.llc"),
    ("⚫ Zoro.to",      "https://zoro.to"),
    ("🔴 9anime",       "https://9anime.to"),
]

SEASONS = ["winter", "spring", "summer", "fall"]

# ══════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("AnimeBot")

# ══════════════════════════════════════════════════════════
#  LANGUAGE UTILS
# ══════════════════════════════════════════════════════════
LANG_MAP = {
    "hi":"hi","en":"en","ja":"ja","ko":"ko","zh-cn":"zh-CN",
    "zh-tw":"zh-TW","es":"es","fr":"fr","de":"de","pt":"pt",
    "ar":"ar","ru":"ru","tr":"tr","id":"id","th":"th",
    "it":"it","vi":"vi","nl":"nl","pl":"pl","uk":"uk",
}

def detect_lang(text: str) -> str:
    try:
        return LANG_MAP.get(_detect(text), "en")
    except Exception:
        return "en"

def tr(text: str, dest: str) -> str:
    """Translate text → dest lang. Skip if already English."""
    if dest == "en" or not text:
        return text
    try:
        out = GoogleTranslator(source="auto", target=dest).translate(text)
        return out or text
    except Exception:
        return text

def to_english(text: str) -> str:
    """Translate any language → English for API search."""
    try:
        return GoogleTranslator(source="auto", target="en").translate(text) or text
    except Exception:
        return text

# ══════════════════════════════════════════════════════════
#  HTTP HELPERS
# ══════════════════════════════════════════════════════════
async def get_json(url: str, params: dict = None) -> Optional[dict]:
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            async with s.get(url, params=params) as r:
                if r.status == 200:
                    return await r.json()
                if r.status == 429:
                    log.warning("Jikan rate limit — waiting 1s")
                    await asyncio.sleep(1)
    except Exception as e:
        log.error(f"GET {url} failed: {e}")
    return None

async def post_json(url: str, payload: dict) -> Optional[dict]:
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            async with s.post(url, json=payload) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        log.error(f"POST {url} failed: {e}")
    return None

# ══════════════════════════════════════════════════════════
#  JIKAN  (MyAnimeList  –  free, no key)
# ══════════════════════════════════════════════════════════
async def jikan_search(query: str, limit: int = 6) -> list:
    data = await get_json(f"{JIKAN}/anime", {
        "q": query, "limit": limit,
        "order_by": "popularity", "sort": "asc",
    })
    return (data or {}).get("data", [])

async def jikan_detail(mal_id: int) -> Optional[dict]:
    data = await get_json(f"{JIKAN}/anime/{mal_id}/full")
    return (data or {}).get("data")

async def jikan_top(page: int = 1) -> list:
    data = await get_json(f"{JIKAN}/top/anime", {"page": page, "limit": 10})
    return (data or {}).get("data", [])

async def jikan_seasonal(year: int, season: str) -> list:
    data = await get_json(f"{JIKAN}/seasons/{year}/{season}", {"limit": 10})
    return (data or {}).get("data", [])

async def jikan_random() -> Optional[dict]:
    data = await get_json(f"{JIKAN}/random/anime")
    return (data or {}).get("data")

async def jikan_genres() -> list:
    data = await get_json(f"{JIKAN}/genres/anime")
    return (data or {}).get("data", [])

async def jikan_genre_search(genre_id: int, limit: int = 6) -> list:
    data = await get_json(f"{JIKAN}/anime", {
        "genres": genre_id, "limit": limit,
        "order_by": "score", "sort": "desc",
    })
    return (data or {}).get("data", [])

# ══════════════════════════════════════════════════════════
#  ANILIST  (GraphQL  –  free, no key)
# ══════════════════════════════════════════════════════════
_AL_SEARCH = """
query($s:String){Page(page:1,perPage:5){media(search:$s,type:ANIME,sort:POPULARITY_DESC){
  id title{romaji english native}description(asHtml:false)
  episodes status averageScore genres
  coverImage{large} siteUrl
}}}
"""

async def anilist_search(query: str) -> list:
    data = await post_json(ANILIST, {"query": _AL_SEARCH, "variables": {"s": query}})
    return (data or {}).get("data", {}).get("Page", {}).get("media", [])

# ══════════════════════════════════════════════════════════
#  CARD BUILDER
# ══════════════════════════════════════════════════════════
def _star_bar(score) -> str:
    """Convert score/10 to emoji star bar."""
    try:
        s = float(score)
        filled = round(s / 2)
        return "⭐" * filled + "☆" * (5 - filled) + f"  {s}/10"
    except Exception:
        return "N/A"

def build_card(a: dict, lang: str) -> str:
    """Build beautiful formatted anime card, translated to user's language."""
    title_en  = a.get("title_english") or a.get("title") or "Unknown"
    title_jp  = a.get("title_japanese", "")
    a_type    = a.get("type", "?")
    eps       = a.get("episodes") or "?"
    status    = a.get("status", "?")
    score     = a.get("score") or "?"
    rank      = a.get("rank") or "?"
    pop       = a.get("popularity") or "?"
    year      = a.get("year") or "?"
    rating    = a.get("rating") or "?"
    duration  = a.get("duration") or "?"
    source    = a.get("source") or "?"
    mal_id    = a.get("mal_id", "")

    genres    = " · ".join(g["name"] for g in a.get("genres", []))        or "N/A"
    themes    = " · ".join(t["name"] for t in a.get("themes", []))        or ""
    studios   = " · ".join(s["name"] for s in a.get("studios", []))      or "N/A"
    producers = " · ".join(p["name"] for p in a.get("producers", [])[:3]) or "N/A"

    synopsis  = (a.get("synopsis") or "No synopsis available.")
    synopsis  = re.sub(r"\[Written by MAL Rewrite\]", "", synopsis).strip()
    if len(synopsis) > 700:
        synopsis = synopsis[:700] + "…"

    trailer   = (a.get("trailer") or {}).get("url") or ""

    # Translate dynamic content
    if lang != "en":
        synopsis = tr(synopsis, lang)
        status   = tr(status,   lang)
        a_type   = tr(a_type,   lang)
        source   = tr(source,   lang)

    mal_url   = f"https://myanimelist.net/anime/{mal_id}" if mal_id else "https://myanimelist.net"

    lines = [
        "╔══════════════════════════╗",
        f"║  🎌  *{title_en[:28]}*",
        "╚══════════════════════════╝",
        "",
    ]
    if title_jp:
        lines.append(f"🇯🇵 _{title_jp}_")
        lines.append("")

    lines += [
        f"📺 *{a_type}*  •  🎬 *{eps} eps*  •  📅 *{year}*",
        f"📡 {status}  •  ⏱ {duration}",
        f"⭐ {_star_bar(score)}",
        f"🏆 MAL Rank: *#{rank}*  •  🔥 Popularity: *#{pop}*",
        f"🔞 {rating}",
        "",
        f"🎭 *Genres:* `{genres}`",
    ]
    if themes:
        lines.append(f"🌸 *Themes:* `{themes}`")
    lines += [
        f"🏢 *Studio:* `{studios}`",
        f"🎬 *Source:* `{source}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📖 *Synopsis*",
        synopsis,
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "▶️ *Watch Online:*",
    ]
    for name, url in WATCH_SITES:
        lines.append(f"  {name}")

    if trailer:
        lines.append(f"\n🎞 [Watch Trailer]({trailer})")

    lines += [
        "",
        f"🔗 [Open on MyAnimeList]({mal_url})",
    ]
    return "\n".join(lines)

def build_anilist_card(a: dict, lang: str) -> str:
    t         = a.get("title", {})
    title_en  = t.get("english") or t.get("romaji") or "Unknown"
    title_jp  = t.get("native", "")
    score     = (a.get("averageScore") or 0) / 10
    eps       = a.get("episodes") or "?"
    status    = a.get("status", "?")
    genres    = " · ".join(a.get("genres", []))
    synopsis  = re.sub(r"<[^>]+>", "", a.get("description") or "")[:700]
    site_url  = a.get("siteUrl", "https://anilist.co")

    if lang != "en":
        synopsis = tr(synopsis, lang)
        status   = tr(status, lang)

    lines = [
        "╔══════════════════════════╗",
        f"║  🎌  *{title_en[:28]}*",
        "╚══════════════════════════╝\n",
    ]
    if title_jp:
        lines.append(f"🇯🇵 _{title_jp}_\n")
    lines += [
        f"📺 *Anime*  •  🎬 *{eps} eps*  •  📡 {status}",
        f"⭐ {_star_bar(score)}",
        f"🎭 *Genres:* `{genres}`\n",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📖 *Synopsis*",
        synopsis,
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n",
        "▶️ *Watch Online:*",
    ]
    for name, url in WATCH_SITES:
        lines.append(f"  {name}")
    lines.append(f"\n🔗 [Open on AniList]({site_url})")
    return "\n".join(lines)

def watch_keyboard(mal_id=None) -> InlineKeyboardMarkup:
    """Inline buttons for watch sites + MAL link."""
    rows = []
    row  = []
    for i, (name, url) in enumerate(WATCH_SITES):
        row.append(InlineKeyboardButton(name, url=url))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    if mal_id:
        rows.append([InlineKeyboardButton(
            "📊 MyAnimeList Page",
            url=f"https://myanimelist.net/anime/{mal_id}"
        )])
    rows.append([InlineKeyboardButton("🔍 Search Another", switch_inline_query_current_chat="")])
    return InlineKeyboardMarkup(rows)

# ══════════════════════════════════════════════════════════
#  SEND HELPERS
# ══════════════════════════════════════════════════════════
async def safe_send(update: Update, text: str, markup=None, photo: str = None):
    """Send message with photo or text, fallback to plain if markdown fails."""
    kw = dict(parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    try:
        if photo:
            await update.message.reply_photo(photo=photo, caption=text, **kw)
        else:
            await update.message.reply_text(text, **kw)
    except BadRequest:
        clean = re.sub(r"[*_`\[\]()]", "", text)
        if photo:
            await update.message.reply_photo(photo=photo, caption=clean, reply_markup=markup)
        else:
            await update.message.reply_text(clean, reply_markup=markup)

async def safe_edit(query, text: str, markup=None, photo: str = None):
    kw = dict(parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    try:
        if photo:
            await query.message.reply_photo(photo=photo, caption=text, **kw)
        else:
            await query.message.edit_text(text, **kw)
    except BadRequest:
        clean = re.sub(r"[*_`\[\]()]", "", text)
        await query.message.reply_text(clean, reply_markup=markup)

def get_image(a: dict) -> Optional[str]:
    return (a.get("images") or {}).get("jpg", {}).get("large_image_url") or \
           (a.get("images") or {}).get("jpg", {}).get("image_url")

# ══════════════════════════════════════════════════════════
#  RESULT LIST BUILDER
# ══════════════════════════════════════════════════════════
def result_list(results: list, lang: str, header_key: str = "results") -> tuple[str, InlineKeyboardMarkup]:
    headers = {
        "results":  "🔍 Multiple results found! Choose one:",
        "top":      "🏆 Top Anime List",
        "seasonal": "🌸 This Season's Anime",
        "genre":    "🎭 Anime by Genre",
    }
    head = tr(headers.get(header_key, headers["results"]), lang)
    text = f"*{head}*\n\n"
    btns = []
    for i, a in enumerate(results[:6], 1):
        title = a.get("title_english") or a.get("title") or "Unknown"
        year  = a.get("year") or "?"
        score = a.get("score") or "?"
        text += f"`{i}.` *{title}* ({year}) — ⭐{score}\n"
        btns.append([InlineKeyboardButton(
            f"{i}. {title[:35]}",
            callback_data=f"pick_{a['mal_id']}"
        )])
    btns.append([InlineKeyboardButton(
        tr("🔍 New Search", lang),
        switch_inline_query_current_chat=""
    )])
    return text, InlineKeyboardMarkup(btns)

# ══════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ══════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🎌 *Anime Finder Bot* — v2.0\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kisi bhi anime ka naam type karo!\n"
        "Hindi, English, Japanese — *koi bhi language!*\n\n"
        "📌 *Commands:*\n"
        "/search `<naam>` — anime dhundo\n"
        "/top — top 10 anime (MAL)\n"
        "/seasonal — is season ke anime\n"
        "/random — random anime\n"
        "/genre — genre se dhundo\n"
        "/help — help\n\n"
        "💡 *Examples:*\n"
        "`नारुतो`  `Naruto`  `進撃の巨人`\n"
        "`원피스`  `Dragon Ball`  `ड्रैगन बॉल`\n\n"
        "✅ *Koi bhi API key nahi chahiye!*"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)

async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = detect_lang(update.message.text)
    await update.message.chat.send_action("typing")
    wait = await update.message.reply_text(tr("🏆 Fetching top anime...", lang))
    results = await jikan_top()
    await wait.delete()
    if not results:
        await update.message.reply_text(tr("❌ Could not fetch top anime. Try again.", lang))
        return
    ctx.user_data["lang"]    = lang
    ctx.user_data["results"] = {str(a["mal_id"]): a for a in results}
    text, markup = result_list(results, lang, "top")
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def cmd_seasonal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = detect_lang(update.message.text)
    await update.message.chat.send_action("typing")

    import datetime
    now    = datetime.datetime.now()
    year   = now.year
    month  = now.month
    season = SEASONS[(month - 1) // 3]

    wait = await update.message.reply_text(
        tr(f"🌸 Fetching {season.capitalize()} {year} anime...", lang)
    )
    results = await jikan_seasonal(year, season)
    await wait.delete()
    if not results:
        await update.message.reply_text(
            tr("❌ Could not fetch seasonal anime. Try again.", lang)
        )
        return
    ctx.user_data["lang"]    = lang
    ctx.user_data["results"] = {str(a["mal_id"]): a for a in results}
    text, markup = result_list(results, lang, "seasonal")
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def cmd_random(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = detect_lang(update.message.text)
    await update.message.chat.send_action("typing")
    wait = await update.message.reply_text(tr("🎲 Finding a random anime for you...", lang))
    anime = await jikan_random()
    await wait.delete()
    if not anime:
        await update.message.reply_text(tr("❌ Could not fetch random anime. Try again.", lang))
        return
    card  = build_card(anime, lang)
    img   = get_image(anime)
    await safe_send(update, card, watch_keyboard(anime.get("mal_id")), img)

async def cmd_genre(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = detect_lang(update.message.text)
    await update.message.chat.send_action("typing")
    genres = await jikan_genres()
    if not genres:
        await update.message.reply_text(tr("❌ Could not fetch genres. Try again.", lang))
        return

    # Show top 20 genres as buttons
    ctx.user_data["lang"] = lang
    popular_genres = genres[:20]
    buttons = []
    row = []
    for g in popular_genres:
        row.append(InlineKeyboardButton(g["name"], callback_data=f"genre_{g['mal_id']}"))
        if len(row) == 3:
            buttons.append(row); row = []
    if row:
        buttons.append(row)

    head = tr("🎭 *Choose a Genre:*", lang)
    await update.message.reply_text(
        head,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /search <query>"""
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Usage: `/search <anime naam>`\nExample: `/search Naruto`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    query = " ".join(args)
    # Simulate as regular message
    update.message.text = query
    await text_search(update, ctx)

# ══════════════════════════════════════════════════════════
#  MAIN SEARCH  (plain text message)
# ══════════════════════════════════════════════════════════
async def text_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query    = update.message.text.strip()
    if not query or query.startswith("/"):
        return

    lang     = detect_lang(query)
    log.info(f"Search: '{query}' | Lang: {lang}")

    # Translate query to English for better search
    eng_query = query if lang == "en" else to_english(query)
    log.info(f"EN query: '{eng_query}'")

    await update.message.chat.send_action("typing")
    wait = await update.message.reply_text(tr("🔍 Searching for anime...", lang))

    # ── Try Jikan first ──
    results = await jikan_search(eng_query)
    if not results and eng_query != query:
        results = await jikan_search(query)          # fallback: original query

    # ── Fallback to AniList ──
    if not results:
        al = await anilist_search(eng_query)
        if al:
            await wait.delete()
            anime  = al[0]
            card   = build_anilist_card(anime, lang)
            img    = (anime.get("coverImage") or {}).get("large")
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔗 AniList", url=anime.get("siteUrl","https://anilist.co")),
                InlineKeyboardButton("🔍 New Search", switch_inline_query_current_chat=""),
            ]])
            await safe_send(update, card, markup, img)
            return

    await wait.delete()

    if not results:
        msg = tr(f"❌ *'{query}'* ke liye koi anime nahi mila.\n\nDusra naam try karo ya English mein likhkar try karo.", lang)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return

    ctx.user_data["lang"]    = lang
    ctx.user_data["results"] = {str(a["mal_id"]): a for a in results}

    if len(results) == 1:
        await _send_jikan(update, results[0], lang)
    else:
        text, markup = result_list(results, lang, "results")
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def _send_jikan(update_or_query, anime: dict, lang: str):
    """Fetch full detail and send as card. Works for both Update and CallbackQuery context."""
    mal_id = anime.get("mal_id")
    detail = await jikan_detail(mal_id) if mal_id else None
    a      = detail or anime
    card   = build_card(a, lang)
    img    = get_image(a)

    if hasattr(update_or_query, "message") and hasattr(update_or_query.message, "reply_photo"):
        await safe_send(update_or_query, card, watch_keyboard(mal_id), img)
    else:
        # It's a callback query's update
        await safe_send(update_or_query, card, watch_keyboard(mal_id), img)

# ══════════════════════════════════════════════════════════
#  CALLBACK HANDLER  (Inline buttons)
# ══════════════════════════════════════════════════════════
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data or ""
    await q.answer()

    lang = ctx.user_data.get("lang", "en")

    # ── Anime pick from list ──
    if data.startswith("pick_"):
        mal_id  = int(data[5:])
        cached  = (ctx.user_data.get("results") or {}).get(str(mal_id), {})
        detail  = await jikan_detail(mal_id) or cached
        card    = build_card(detail, lang)
        img     = get_image(detail)
        markup  = watch_keyboard(mal_id)
        if img:
            try:
                await q.message.reply_photo(photo=img, caption=card,
                    parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            except BadRequest:
                clean = re.sub(r"[*_`\[\]()]", "", card)
                await q.message.reply_photo(photo=img, caption=clean, reply_markup=markup)
        else:
            try:
                await q.message.edit_text(card,
                    parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            except BadRequest:
                clean = re.sub(r"[*_`\[\]()]", "", card)
                await q.message.edit_text(clean, reply_markup=markup)
        return

    # ── Genre selection ──
    if data.startswith("genre_"):
        genre_id = int(data[6:])
        await q.message.chat.send_action("typing")
        results  = await jikan_genre_search(genre_id)
        if not results:
            await q.message.reply_text(tr("❌ No results for this genre.", lang))
            return
        ctx.user_data["results"] = {str(a["mal_id"]): a for a in results}
        text, markup = result_list(results, lang, "genre")
        try:
            await q.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
        except BadRequest:
            await q.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
        return

# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════
async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start",    "Bot ke baare mein jaano"),
        BotCommand("search",   "Anime search karo — /search Naruto"),
        BotCommand("top",      "Top 10 anime dekho"),
        BotCommand("seasonal", "Is season ke anime"),
        BotCommand("random",   "Random anime"),
        BotCommand("genre",    "Genre se dhundo"),
        BotCommand("help",     "Help"),
    ])
    log.info("✅ Bot commands registered")

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        log.error("❌  BOT_TOKEN set nahi hai!")
        log.error("    Run: export BOT_TOKEN='your_token'  phir  python3 main.py")
        return

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("top",      cmd_top))
    app.add_handler(CommandHandler("seasonal", cmd_seasonal))
    app.add_handler(CommandHandler("random",   cmd_random))
    app.add_handler(CommandHandler("genre",    cmd_genre))
    app.add_handler(CommandHandler("search",   cmd_search))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_search))

    log.info("🎌 Anime Finder Bot v2.0 — Running!")
    log.info("   Ctrl+C se band karo")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
