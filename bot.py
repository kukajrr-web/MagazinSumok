# bot.py
# PTB (python-telegram-bot) async bot
# UseAI demo bot for bag shop: natural dialog + optional AI + RU/KZ + clean UX (no big keyboard spam)

import os
import re
import json
import time
import base64
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ---------------------------
# LOGGING
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("magazin-sumok-bot")

# ---------------------------
# ENV
# ---------------------------
TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()  # optional
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}  # optional

# Storage files (simple JSON for demo)
CATALOG_FILE = "catalog.json"
LEADS_FILE = "leads.json"

# ---------------------------
# STATES
# ---------------------------
STATE_NONE = "NONE"
STATE_WAIT_PHOTO_OR_MODEL = "WAIT_PHOTO_OR_MODEL"
STATE_ORDER_CITY = "ORDER_CITY"
STATE_ORDER_PHONE = "ORDER_PHONE"
STATE_ORDER_DETAILS = "ORDER_DETAILS"
STATE_WAIT_MANAGER_MSG = "WAIT_MANAGER_MSG"

# ---------------------------
# TEXTS RU/KZ
# ---------------------------
TXT = {
    "ru": {
        "start_hi": (
            "Здравствуйте! 👋 Я AI-менеджер магазина сумок.\n"
            "Чем могу помочь?\n\n"
            "• Узнать цену (можно фото)\n"
            "• Подобрать похожую модель\n"
            "• Оформить заказ / доставка\n\n"
            "Напишите запрос одним сообщением или отправьте фото."
        ),
        "choose_lang": "Выберите язык / Тілді таңдаңыз:",
        "menu_title": "Меню:",
        "menu_hint": "Если хотите — напишите запрос текстом (без кнопок тоже можно).",
        "ask_photo_or_model": "Ок 👍 Отправьте фото сумки или напишите *название модели* (например: “Sofia Mini”).",
        "ask_city": "Отлично. Напишите ваш *город*:",
        "ask_phone": "Спасибо. Напишите ваш номер телефона (пример: +7 777 123 45 67):",
        "ask_details": "Коротко уточните: модель/цвет/кол-во + адрес (если доставка) или “самовывоз”.",
        "lead_done": "Заявка принята ✅ Менеджер скоро ответит.\nХотите открыть меню?",
        "manager": "Напишите сообщение — я передам менеджеру.",
        "delivery": "Доставка: по городу 1–2 дня. Самовывоз — по адресу магазина. Хотите оформить заказ?",
        "catalog_empty": "Каталог пока пуст. Добавьте товары через /admin (для демо).",
        "catalog_list": "Каталог (демо):",
        "unknown": "Понял. Уточните, пожалуйста: вам *цена*, *подбор* или *заказ/доставка*? Можно фото.",
        "no_ai": "AI-режим сейчас выключен (нет ключа). Я всё равно могу помочь по каталогу и оформить заявку.",
        "ai_fail": "Я не смог корректно обработать запрос. Попробуйте: фото + коротко что нужно (цена/подбор/заказ).",
        "price_result": "Нашёл вариант:\n{card}\n\nХотите оформить заказ?",
        "not_found": "Пока не нашёл точное совпадение. Уточните модель/цвет/размер или пришлите фото ближе.",
        "confirm_menu": "Меню",
        "btn_price": "💰 Узнать цену",
        "btn_catalog": "📦 Каталог",
        "btn_delivery": "🚚 Доставка",
        "btn_order": "🧾 Оформить заказ",
        "btn_manager": "👤 Менеджер",
        "btn_lang": "🌐 Язык",
        "lang_set_ru": "Готово ✅ Язык: Русский",
        "lang_set_kz": "Дайын ✅ Тіл: Қазақша",
        "admin_only": "Только для админа.",
        "admin_help": (
            "Админ команды:\n"
            "/admin — подсказка\n"
            "/add — добавить товар (затем пришлите: название|цена|цвета через запятую|описание)\n"
            "/setphoto — затем пришлите фото (привяжется к последнему товару)\n"
            "/clear — очистить каталог (осторожно)\n"
        ),
        "admin_add_format": "Отправьте строку формата:\nНазвание|Цена|Цвета через запятую|Описание",
        "admin_added": "Товар добавлен ✅ Теперь можно /setphoto и отправить фото (по желанию).",
        "admin_photo_set": "Фото сохранено и привязано ✅",
        "admin_cleared": "Каталог очищен ✅",
    },
    "kz": {
        "start_hi": (
            "Сәлеметсіз бе! 👋 Мен сөмкелер дүкенінің AI-менеджерімін.\n"
            "Қалай көмектесейін?\n\n"
            "• Бағасын айту (фото жіберуге болады)\n"
            "• Ұқсас модель таңдау\n"
            "• Тапсырыс рәсімдеу / жеткізу\n\n"
            "Бір хабарлама жазыңыз немесе фото жіберіңіз."
        ),
        "choose_lang": "Тілді таңдаңыз / Выберите язык:",
        "menu_title": "Мәзір:",
        "menu_hint": "Қаласаңыз — мәтінмен жазыңыз (батырмасыз да болады).",
        "ask_photo_or_model": "Жақсы 👍 Сөмкенің фотосын жіберіңіз немесе *модель атауын* жазыңыз.",
        "ask_city": "Керемет. *Қалаңызды* жазыңыз:",
        "ask_phone": "Рақмет. Телефон нөміріңізді жазыңыз (мысалы: +7 777 123 45 67):",
        "ask_details": "Қысқаша: модель/түс/саны + мекенжай (жеткізу болса) немесе “самовывоз”.",
        "lead_done": "Өтінім қабылданды ✅ Менеджер жақында жауап береді.\nМәзір ашайық па?",
        "manager": "Хабарлама жазыңыз — менеджерге жіберемін.",
        "delivery": "Жеткізу: қала ішінде 1–2 күн. Самовывоз — дүкен мекенжайынан. Тапсырыс бересіз бе?",
        "catalog_empty": "Каталог әзірге бос. Демо үшін /admin арқылы қосыңыз.",
        "catalog_list": "Каталог (демо):",
        "unknown": "Түсіндім. Нақтылаңызшы: *баға*, *таңдау* немесе *тапсырыс/жеткізу* керек пе? Фото да болады.",
        "no_ai": "AI режимі өшірулі (кілт жоқ). Каталогпен және тапсырыспен көмектесемін.",
        "ai_fail": "Сұранысты дұрыс өңдей алмадым. Фото + қысқа түрде жазыңыз (баға/таңдау/тапсырыс).",
        "price_result": "Вариант таптым:\n{card}\n\nТапсырыс рәсімдейміз бе?",
        "not_found": "Дәл сәйкестік таппадым. Модель/түс/өлшемді нақтылаңыз немесе анық фото жіберіңіз.",
        "confirm_menu": "Мәзір",
        "btn_price": "💰 Бағасын білу",
        "btn_catalog": "📦 Каталог",
        "btn_delivery": "🚚 Жеткізу",
        "btn_order": "🧾 Тапсырыс",
        "btn_manager": "👤 Менеджер",
        "btn_lang": "🌐 Тіл",
        "lang_set_ru": "Готово ✅ Язык: Русский",
        "lang_set_kz": "Дайын ✅ Тіл: Қазақша",
        "admin_only": "Тек админге.",
        "admin_help": (
            "Админ командалар:\n"
            "/admin — көмек\n"
            "/add — тауар қосу (кейін: атауы|бағасы|түстер|сипаттама)\n"
            "/setphoto — кейін фото жіберіңіз (соңғы тауарға)\n"
            "/clear — каталогты тазалау\n"
        ),
        "admin_add_format": "Мына форматта жіберіңіз:\nАтауы|Бағасы|Түстер(үтір арқылы)|Сипаттама",
        "admin_added": "Тауар қосылды ✅ Қаласаңыз /setphoto жасап, фото жіберіңіз.",
        "admin_photo_set": "Фото сақталды ✅",
        "admin_cleared": "Каталог тазаланды ✅",
    }
}

# ---------------------------
# SIMPLE STORAGE
# ---------------------------
def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def ensure_storage():
    if not os.path.exists(CATALOG_FILE):
        save_json(CATALOG_FILE, {"items": [], "last_id": 0})
    if not os.path.exists(LEADS_FILE):
        save_json(LEADS_FILE, {"leads": []})

# Catalog item structure:
# {id, name, price, colors[], desc, photo_file_id(optional)}
def catalog_add(name: str, price: str, colors: List[str], desc: str) -> Dict[str, Any]:
    db = load_json(CATALOG_FILE, {"items": [], "last_id": 0})
    db["last_id"] = int(db.get("last_id", 0)) + 1
    item = {
        "id": db["last_id"],
        "name": name.strip(),
        "price": price.strip(),
        "colors": [c.strip() for c in colors if c.strip()],
        "desc": desc.strip(),
        "photo_file_id": None,
    }
    db["items"].append(item)
    save_json(CATALOG_FILE, db)
    return item

def catalog_set_photo(item_id: int, file_id: str) -> bool:
    db = load_json(CATALOG_FILE, {"items": [], "last_id": 0})
    for it in db["items"]:
        if it["id"] == item_id:
            it["photo_file_id"] = file_id
            save_json(CATALOG_FILE, db)
            return True
    return False

def catalog_clear():
    save_json(CATALOG_FILE, {"items": [], "last_id": 0})

def catalog_list() -> List[Dict[str, Any]]:
    db = load_json(CATALOG_FILE, {"items": [], "last_id": 0})
    return db.get("items", [])

def add_lead(data: Dict[str, Any]):
    db = load_json(LEADS_FILE, {"leads": []})
    db["leads"].append(data)
    save_json(LEADS_FILE, db)

# ---------------------------
# UI
# ---------------------------
def kb_lang() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Русский 🇷🇺", callback_data="lang:ru"),
         InlineKeyboardButton("Қазақша 🇰🇿", callback_data="lang:kz")]
    ])

def kb_main(lang: str) -> InlineKeyboardMarkup:
    t = TXT[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t["btn_price"], callback_data="act:price")],
        [InlineKeyboardButton(t["btn_catalog"], callback_data="act:catalog"),
         InlineKeyboardButton(t["btn_delivery"], callback_data="act:delivery")],
        [InlineKeyboardButton(t["btn_order"], callback_data="act:order")],
        [InlineKeyboardButton(t["btn_manager"], callback_data="act:manager"),
         InlineKeyboardButton(t["btn_lang"], callback_data="act:lang")],
    ])

def kb_small_menu(lang: str) -> InlineKeyboardMarkup:
    t = TXT[lang]
    return InlineKeyboardMarkup([[InlineKeyboardButton(t["confirm_menu"], callback_data="act:menu")]])

def user_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang") or "ru"

def set_state(context: ContextTypes.DEFAULT_TYPE, st: str):
    context.user_data["state"] = st

def get_state(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("state", STATE_NONE)

# ---------------------------
# INTENT DETECTION (no-AI fallback)
# ---------------------------
def detect_intent(text: str) -> str:
    t = (text or "").lower().strip()
    if not t:
        return "CHAT"
    if any(x in t for x in ["меню", "menu", "мәзір"]):
        return "MENU"
    if any(x in t for x in ["цена", "сколько", "стоимость", "почем", "баға", "қанша"]):
        return "PRICE"
    if any(x in t for x in ["каталог", "модели", "ассортимент", "catalog"]):
        return "CATALOG"
    if any(x in t for x in ["доставка", "привез", "курьер", "жеткіз", "delivery"]):
        return "DELIVERY"
    if any(x in t for x in ["заказ", "купить", "оформ", "тапсырыс", "сатып"]):
        return "ORDER"
    if any(x in t for x in ["менеджер", "оператор", "адам", "manager"]):
        return "MANAGER"
    return "CHAT"

def normalize_phone(s: str) -> Optional[str]:
    digits = re.sub(r"[^\d+]", "", s.strip())
    # simple accept +7 / 7 / 8 formats
    d = re.sub(r"[^\d]", "", digits)
    if len(d) < 10:
        return None
    # format to +7XXXXXXXXXX if looks like KZ/RU
    if d.startswith("8") and len(d) == 11:
        d = "7" + d[1:]
    if d.startswith("7") and len(d) == 11:
        return "+" + d
    if len(d) == 10:
        return "+7" + d
    return "+" + d

def find_by_text(query: str) -> Optional[Dict[str, Any]]:
    q = (query or "").lower().strip()
    if not q:
        return None
    items = catalog_list()
    # direct contains
    for it in items:
        if it["name"].lower() in q or q in it["name"].lower():
            return it
    # token overlap
    q_tokens = set(re.findall(r"[a-zа-я0-9]+", q))
    best = None
    best_score = 0
    for it in items:
        it_tokens = set(re.findall(r"[a-zа-я0-9]+", it["name"].lower()))
        score = len(q_tokens & it_tokens)
        if score > best_score:
            best_score = score
            best = it
    if best_score >= 1:
        return best
    return None

def format_item_card(it: Dict[str, Any], lang: str) -> str:
    if lang == "kz":
        colors = ", ".join(it.get("colors") or []) or "—"
        return f"👜 {it['name']}\n💰 Бағасы: {it['price']}\n🎨 Түстер: {colors}\nℹ️ {it.get('desc','')}"
    colors = ", ".join(it.get("colors") or []) or "—"
    return f"👜 {it['name']}\n💰 Цена: {it['price']}\n🎨 Цвета: {colors}\nℹ️ {it.get('desc','')}"

# ---------------------------
# OPTIONAL AI (OpenAI) — safe concierge + matching by photo/text
# ---------------------------
async def ai_answer_text(prompt: str) -> Optional[str]:
    """
    Minimal OpenAI call without extra deps.
    Uses requests-like via urllib to avoid requirements changes.
    Works on Railway/Beget if outbound allowed.
    """
    if not OPENAI_API_KEY:
        return None
    try:
        import urllib.request

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a helpful sales assistant for a bag shop. Reply briefly and politely."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }

        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8")
        j = json.loads(raw)
        return j["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning("AI text call failed: %s", e)
        return None

async def ai_match_by_photo_or_text(lang: str, text_query: str, image_b64: Optional[str]) -> Dict[str, Any]:
    """
    Returns dict:
      {type: "match", item: {...}, confidence: float, notes: str}
      or {type: "clarify", questions: "..."}
      or {type: "no_match"}
    """
    items = catalog_list()
    if not items:
        return {"type": "no_match"}

    # If no AI, fallback to text match only
    if not OPENAI_API_KEY:
        it = find_by_text(text_query)
        if it:
            return {"type": "match", "item": it, "confidence": 0.75, "notes": "text"}
        return {"type": "no_match"}

    # Build compact catalog context (names, prices, colors)
    catalog_context = []
    for it in items[:30]:
        catalog_context.append({
            "id": it["id"],
            "name": it["name"],
            "price": it["price"],
            "colors": it.get("colors", []),
            "desc": it.get("desc", ""),
        })

    # Prompt: force choose best match only if sure, else clarify
    if lang == "kz":
        user_inst = (
            "Сен сөмке дүкенінің менеджерісің. Мақсат: клиенттің мәтіні/фотосы бойынша каталогтағы нақты модельді табу.\n"
            "Ережелер:\n"
            "1) Егер сенімділік >= 0.85 болса — тек бір модельді таңда.\n"
            "2) Егер сенімділік төмен болса — нақтылау сұрақтарын қой (2-3 сұрақ).\n"
            "3) Ойдан шығарма. Каталогта жоқ модельді 'бар' деп айтпа.\n"
            "Жауапты қатаң JSON түрінде бер:\n"
            '{"action":"match|clarify|no_match","id":number|null,"confidence":0..1,"questions":"string","reason":"string"}'
        )
    else:
        user_inst = (
            "You are a bag shop manager. Goal: match customer's text/photo to an exact model from our catalog.\n"
            "Rules:\n"
            "1) If confidence >= 0.85 — choose exactly one model.\n"
            "2) If lower — ask 2-3 clarifying questions.\n"
            "3) Never invent. If not in catalog, say no_match.\n"
            "Return STRICT JSON only:\n"
            '{"action":"match|clarify|no_match","id":number|null,"confidence":0..1,"questions":"string","reason":"string"}'
        )

    # Use OpenAI with image if provided (vision capable model)
    try:
        import urllib.request

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

        user_content = [{"type": "text", "text": f"Catalog: {json.dumps(catalog_context, ensure_ascii=False)}\n\nCustomer text: {text_query or ''}"}]
        if image_b64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})

        body = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": user_inst},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
        j = json.loads(raw)
        content = j["choices"][0]["message"]["content"]
        out = json.loads(content)

        action = out.get("action")
        if action == "match":
            _id = out.get("id")
            conf = float(out.get("confidence", 0))
            chosen = next((x for x in items if x["id"] == _id), None)
            if chosen and conf >= 0.85:
                return {"type": "match", "item": chosen, "confidence": conf, "notes": out.get("reason", "")}
            # if not enough confidence, clarify
            return {"type": "clarify", "questions": out.get("questions", "") or "Уточните цвет/размер/фурнитуру?"}
        if action == "clarify":
            return {"type": "clarify", "questions": out.get("questions", "") or "Уточните модель/цвет/размер?"}
        return {"type": "no_match"}
    except Exception as e:
        log.warning("AI match failed: %s", e)
        # fallback text
        it = find_by_text(text_query)
        if it:
            return {"type": "match", "item": it, "confidence": 0.75, "notes": "fallback"}
        return {"type": "no_match"}

# ---------------------------
# HANDLERS
# ---------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(context)
    set_state(context, STATE_NONE)
    context.user_data["last_admin_item_id"] = None
    await update.message.reply_text(TXT[lang]["choose_lang"], reply_markup=kb_lang())
    # Important: remove big keyboards
    await update.message.reply_text(" ", reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text(TXT[lang]["start_hi"], reply_markup=kb_small_menu(lang))

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(context)
    set_state(context, STATE_NONE)
    await update.message.reply_text(TXT[lang]["menu_title"], reply_markup=kb_main(lang))
    await update.message.reply_text(TXT[lang]["menu_hint"])

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        lang = user_lang(context)
        await update.message.reply_text(TXT[lang]["admin_only"])
        return
    lang = user_lang(context)
    await update.message.reply_text(TXT[lang]["admin_help"])

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        lang = user_lang(context)
        await update.message.reply_text(TXT[lang]["admin_only"])
        return
    lang = user_lang(context)
    context.user_data["admin_wait_add"] = True
    await update.message.reply_text(TXT[lang]["admin_add_format"])

async def cmd_setphoto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        lang = user_lang(context)
        await update.message.reply_text(TXT[lang]["admin_only"])
        return
    context.user_data["admin_wait_photo"] = True
    lang = user_lang(context)
    await update.message.reply_text("Ок. Теперь пришлите фото товара одним сообщением.")

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        lang = user_lang(context)
        await update.message.reply_text(TXT[lang]["admin_only"])
        return
    catalog_clear()
    lang = user_lang(context)
    await update.message.reply_text(TXT[lang]["admin_cleared"])

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    if data.startswith("lang:"):
        lang = data.split(":", 1)[1]
        context.user_data["lang"] = "kz" if lang == "kz" else "ru"
        if lang == "kz":
            await q.message.reply_text(TXT["kz"]["lang_set_kz"], reply_markup=kb_small_menu("kz"))
        else:
            await q.message.reply_text(TXT["ru"]["lang_set_ru"], reply_markup=kb_small_menu("ru"))
        return

    lang = user_lang(context)

    if data == "act:menu":
        set_state(context, STATE_NONE)
        await q.message.reply_text(TXT[lang]["menu_title"], reply_markup=kb_main(lang))
        return

    if data == "act:lang":
        await q.message.reply_text(TXT[lang]["choose_lang"], reply_markup=kb_lang())
        return

    if data == "act:price":
        set_state(context, STATE_WAIT_PHOTO_OR_MODEL)
        await q.message.reply_text(TXT[lang]["ask_photo_or_model"])
        return

    if data == "act:catalog":
        items = catalog_list()
        if not items:
            await q.message.reply_text(TXT[lang]["catalog_empty"], reply_markup=kb_small_menu(lang))
            return
        lines = [TXT[lang]["catalog_list"]]
        for it in items[:12]:
            lines.append(f"• {it['name']} — {it['price']}")
        await q.message.reply_text("\n".join(lines), reply_markup=kb_small_menu(lang))
        return

    if data == "act:delivery":
        set_state(context, STATE_NONE)
        await q.message.reply_text(TXT[lang]["delivery"], reply_markup=kb_small_menu(lang))
        return

    if data == "act:order":
        set_state(context, STATE_ORDER_CITY)
        await q.message.reply_text(TXT[lang]["ask_city"])
        return

    if data == "act:manager":
        set_state(context, STATE_WAIT_MANAGER_MSG)
        await q.message.reply_text(TXT[lang]["manager"])
        return

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(context)
    text = (update.message.text or "").strip()
    st = get_state(context)

    # Admin add flow
    if update.effective_user.id in ADMIN_IDS and context.user_data.get("admin_wait_add"):
        # parse: name|price|colors|desc
        parts = [p.strip() for p in text.split("|")]
        if len(parts) >= 4:
            name, price, colors, desc = parts[0], parts[1], parts[2], "|".join(parts[3:])
            item = catalog_add(name, price, [c.strip() for c in colors.split(",")], desc)
            context.user_data["admin_wait_add"] = False
            context.user_data["last_admin_item_id"] = item["id"]
            await update.message.reply_text(TXT[lang]["admin_added"])
        else:
            await update.message.reply_text(TXT[lang]["admin_add_format"])
        return

    # State machine
    if st == STATE_ORDER_CITY:
        context.user_data["order_city"] = text
        set_state(context, STATE_ORDER_PHONE)
        await update.message.reply_text(TXT[lang]["ask_phone"])
        return

    if st == STATE_ORDER_PHONE:
        phone = normalize_phone(text)
        if not phone:
            await update.message.reply_text(TXT[lang]["ask_phone"])
            return
        context.user_data["order_phone"] = phone
        set_state(context, STATE_ORDER_DETAILS)
        await update.message.reply_text(TXT[lang]["ask_details"])
        return

    if st == STATE_ORDER_DETAILS:
        # save lead
        lead = {
            "ts": int(time.time()),
            "user_id": update.effective_user.id,
            "username": update.effective_user.username,
            "name": update.effective_user.full_name,
            "city": context.user_data.get("order_city"),
            "phone": context.user_data.get("order_phone"),
            "details": text,
        }
        add_lead(lead)
        set_state(context, STATE_NONE)
        await update.message.reply_text(TXT[lang]["lead_done"], reply_markup=kb_small_menu(lang))
        return

    if st == STATE_WAIT_MANAGER_MSG:
        # Here you can forward to admin chat if you want (needs ADMIN_CHAT_ID)
        lead = {
            "ts": int(time.time()),
            "user_id": update.effective_user.id,
            "username": update.effective_user.username,
            "name": update.effective_user.full_name,
            "message_to_manager": text,
        }
        add_lead(lead)
        set_state(context, STATE_NONE)
        await update.message.reply_text(TXT[lang]["lead_done"], reply_markup=kb_small_menu(lang))
        return

    # No active scenario → detect intent
    intent = detect_intent(text)

    if intent == "MENU":
        await update.message.reply_text(TXT[lang]["menu_title"], reply_markup=kb_main(lang))
        return

    if intent == "PRICE":
        set_state(context, STATE_WAIT_PHOTO_OR_MODEL)
        await update.message.reply_text(TXT[lang]["ask_photo_or_model"])
        return

    if intent == "CATALOG":
        items = catalog_list()
        if not items:
            await update.message.reply_text(TXT[lang]["catalog_empty"], reply_markup=kb_small_menu(lang))
            return
        lines = [TXT[lang]["catalog_list"]]
        for it in items[:12]:
            lines.append(f"• {it['name']} — {it['price']}")
        await update.message.reply_text("\n".join(lines), reply_markup=kb_small_menu(lang))
        return

    if intent == "DELIVERY":
        await update.message.reply_text(TXT[lang]["delivery"], reply_markup=kb_small_menu(lang))
        return

    if intent == "ORDER":
        set_state(context, STATE_ORDER_CITY)
        await update.message.reply_text(TXT[lang]["ask_city"])
        return

    if intent == "MANAGER":
        set_state(context, STATE_WAIT_MANAGER_MSG)
        await update.message.reply_text(TXT[lang]["manager"])
        return

    # Smart chat mode:
    # If AI exists → answer gracefully as manager, but don't invent price/models.
    if OPENAI_API_KEY:
        prompt = (
            "You are a store assistant for a bag shop.\n"
            "If user asks for price/model, ask for photo or model name.\n"
            "If user is rude or writes nonsense, reply calm and guide to next step.\n"
            f"User message: {text}\n"
            "Reply short in the user's language (Russian or Kazakh depending on the message)."
        )
        ans = await ai_answer_text(prompt)
        if ans:
            await update.message.reply_text(ans, reply_markup=kb_small_menu(lang))
            return

    await update.message.reply_text(TXT[lang]["unknown"], reply_markup=kb_small_menu(lang))

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(context)
    st = get_state(context)

    # Admin photo attach flow
    if update.effective_user.id in ADMIN_IDS and context.user_data.get("admin_wait_photo"):
        item_id = context.user_data.get("last_admin_item_id")
        if not item_id:
            await update.message.reply_text("Нет последнего товара. Сначала /add")
            return
        file_id = update.message.photo[-1].file_id
        ok = catalog_set_photo(item_id, file_id)
        context.user_data["admin_wait_photo"] = False
        if ok:
            await update.message.reply_text(TXT[lang]["admin_photo_set"])
        else:
            await update.message.reply_text("Не удалось привязать фото.")
        return

    # Client: photo for price/model
    # We'll attempt AI match if possible, else ask for model name
    if st not in [STATE_WAIT_PHOTO_OR_MODEL, STATE_NONE]:
        # If in order flow, just accept photo as part of details
        await update.message.reply_text(TXT[lang]["ask_details"])
        return

    # Download photo as bytes → base64 for AI
    image_b64 = None
    try:
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        b = await file.download_as_bytearray()
        image_b64 = base64.b64encode(bytes(b)).decode("utf-8")
    except Exception as e:
        log.warning("Could not download photo: %s", e)

    # AI match attempt
    res = await ai_match_by_photo_or_text(lang=lang, text_query="", image_b64=image_b64)

    if res["type"] == "match":
        it = res["item"]
        conf = float(res.get("confidence", 0))
        card = format_item_card(it, lang)
        # If confidence high → speak confidently; else ask confirm
        if conf >= 0.90:
            await update.message.reply_text(TXT[lang]["price_result"].format(card=card), reply_markup=kb_small_menu(lang))
        else:
            # Not "точно", ask confirmation
            if lang == "kz":
                msg = f"Мына модель болуы мүмкін (сенімділік {int(conf*100)}%):\n{card}\n\nДұрыс па? Дұрыстасаңыз — түсін/өлшемін жазыңыз."
            else:
                msg = f"Похоже на эту модель (уверенность {int(conf*100)}%):\n{card}\n\nЭто она? Если да — напишите цвет/размер."
            await update.message.reply_text(msg, reply_markup=kb_small_menu(lang))
        set_state(context, STATE_NONE)
        return

    if res["type"] == "clarify":
        q = res.get("questions") or TXT[lang]["ask_photo_or_model"]
        await update.message.reply_text(q, reply_markup=kb_small_menu(lang))
        set_state(context, STATE_WAIT_PHOTO_OR_MODEL)
        return

    await update.message.reply_text(TXT[lang]["not_found"], reply_markup=kb_small_menu(lang))
    set_state(context, STATE_WAIT_PHOTO_OR_MODEL)

async def on_any_model_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    When we're explicitly waiting for model name, treat text as query.
    """
    lang = user_lang(context)
    st = get_state(context)
    if st != STATE_WAIT_PHOTO_OR_MODEL:
        return

    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text(TXT[lang]["ask_photo_or_model"])
        return

    # AI match by text (or fallback)
    res = await ai_match_by_photo_or_text(lang=lang, text_query=text, image_b64=None)
    if res["type"] == "match":
        it = res["item"]
        card = format_item_card(it, lang)
        await update.message.reply_text(TXT[lang]["price_result"].format(card=card), reply_markup=kb_small_menu(lang))
        set_state(context, STATE_NONE)
        return

    if res["type"] == "clarify":
        await update.message.reply_text(res.get("questions") or TXT[lang]["ask_photo_or_model"], reply_markup=kb_small_menu(lang))
        return

    await update.message.reply_text(TXT[lang]["not_found"], reply_markup=kb_small_menu(lang))

# ---------------------------
# ERROR HANDLER
# ---------------------------
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error: %s", context.error)

# ---------------------------
# MAIN
# ---------------------------
def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is empty. Set environment variable BOT_TOKEN.")

    ensure_storage()

    app = ApplicationBuilder().token(TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))

    # admin
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("setphoto", cmd_setphoto))
    app.add_handler(CommandHandler("clear", cmd_clear))

    # callbacks
    app.add_handler(CallbackQueryHandler(on_callback))

    # photos
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))

    # If waiting for model name → prioritize this handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_any_model_text), group=0)
    # General text
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text), group=1)

    app.add_error_handler(on_error)

    log.info("Bot started. AI=%s", "ON" if bool(OPENAI_API_KEY) else "OFF")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

