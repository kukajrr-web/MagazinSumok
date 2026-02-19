import os
import re
import json
import time
import base64
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Tuple
import requests
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ===================== LOGGING =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("useai-bags-bot")

# ===================== ENV =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is empty. Set environment variable BOT_TOKEN.")

# ===================== FILES =====================
CATALOG_FILE = "catalog.json"

# ===================== STATES =====================
(
    ST_MAIN,
    ST_ADD_NAME,
    ST_ADD_PRICE,
    ST_ADD_COLORS,
    ST_ADD_DESC,
    ST_ADD_PHOTO,
) = range(6)

# ===================== HELPERS =====================

def now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

def is_admin(uid: int) -> bool:
    return ADMIN_ID != 0 and uid == ADMIN_ID

def load_catalog() -> Dict[str, Any]:
    if not os.path.exists(CATALOG_FILE):
        with open(CATALOG_FILE, "w", encoding="utf-8") as f:
            json.dump({"items": {}, "photo_index": {}}, f, ensure_ascii=False, indent=2)
        return {"items": {}, "photo_index": {}}

    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "items" not in data:
            data["items"] = {}
        if "photo_index" not in data:
            data["photo_index"] = {}
        return data
    except Exception:
        # если файл битый — создаём новый бэкап
        backup = f"{CATALOG_FILE}.broken.{int(time.time())}"
        try:
            os.rename(CATALOG_FILE, backup)
        except Exception:
            pass
        with open(CATALOG_FILE, "w", encoding="utf-8") as f:
            json.dump({"items": {}, "photo_index": {}}, f, ensure_ascii=False, indent=2)
        return {"items": {}, "photo_index": {}}

def save_catalog(data: Dict[str, Any]) -> None:
    with open(CATALOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def normalize_price(text: str) -> Optional[int]:
    t = (text or "").strip()
    t = t.replace("₸", "").replace("тенге", "").replace("тг", "")
    t = re.sub(r"[^\d]", "", t)
    if not t:
        return None
    try:
        return int(t)
    except Exception:
        return None

def parse_colors(text: str) -> List[str]:
    t = (text or "").strip()
    if not t:
        return []
    parts = re.split(r"[,;/]+|\s{2,}", t)
    cleaned = []
    for p in parts:
        p = p.strip().lower()
        if p:
            cleaned.append(p)
    # уникальные
    res = []
    for c in cleaned:
        if c not in res:
            res.append(c)
    return res

def make_item_key(name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]+", "_", name.strip().lower())
    base = base.strip("_")
    if not base:
        base = f"item_{int(time.time())}"
    return base

def format_item_ru_kz(item: Dict[str, Any]) -> str:
    name = item.get("name", "—")
    price = item.get("price", 0)
    colors = item.get("colors", [])
    desc = item.get("desc", "")

    ru = (
        f"👜 Модель: {name}\n"
        f"💰 Цена: {price} ₸\n"
        f"🎨 Цвета: {', '.join(colors) if colors else 'уточняйте'}\n"
        f"📝 Описание: {desc if desc else '—'}\n"
    )
    kz = (
        f"👜 Модель: {name}\n"
        f"💰 Бағасы: {price} ₸\n"
        f"🎨 Түстері: {', '.join(colors) if colors else 'нақтылау керек'}\n"
        f"📝 Сипаттама: {desc if desc else '—'}\n"
    )
    return ru + "\n———\n" + kz

def short_welcome() -> str:
    return (
        "Здравствуйте! Я виртуальный менеджер магазина сумок 👜\n"
        "Мен сенің виртуалды менеджеріңмін 👜\n\n"
        "Напишите, что вам нужно:\n"
        "• «Цена» / «Сколько стоит?»\n"
        "• пришлите фото сумки — я скажу модель и цену\n"
        "• или напишите название модели\n\n"
        "Жазыңыз:\n"
        "• «Бағасы қанша?»\n"
        "• немесе сөмкенің фотосын жіберіңіз\n"
        "• немесе модель атауын жазыңыз\n\n"
        "Команды (тех): /start /help\n"
    )

def help_text() -> str:
    return (
        "ℹ️ Помощь / Көмек\n\n"
        "Как пользоваться:\n"
        "1) Напишите вопрос текстом или пришлите фото сумки\n"
        "2) Я отвечу модель/цену и помогу с выбором\n\n"
        "Админ:\n"
        "/add — добавить товар (название/цена/цвета/описание + фото)\n"
        "/catalog — показать список товаров\n"
    )

# ===================== AI (optional) =====================

AI_MODEL = "gpt-4o-mini"

def ai_enabled() -> bool:
    return bool(OPENAI_API_KEY)

def openai_chat(messages: list, max_tokens: int = 600, temperature: float = 0.2) -> str:
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": AI_MODEL,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=90)
    if r.status_code != 200:
        try:
            return f"AI error ({r.status_code}): {r.json()}"
        except Exception:
            return f"AI error ({r.status_code}): {r.text}"
    data = r.json()
    return data["choices"][0]["message"]["content"]

def build_consultant_prompt_ru_kz(catalog_items: Dict[str, Any], user_text: str) -> str:
    # ВАЖНО: ИИ не должен выдумывать наличие товара — только из каталога.
    # Делаем строгую инструкцию.
    items_list = []
    for k, it in catalog_items.items():
        items_list.append({
            "key": k,
            "name": it.get("name", ""),
            "price": it.get("price", 0),
            "colors": it.get("colors", []),
            "desc": it.get("desc", "")
        })

    return (
        "Ты — менеджер-консультант магазина сумок. Отвечай дружелюбно и уверенно.\n"
        "КРИТИЧЕСКИ ВАЖНО:\n"
        "1) НЕЛЬЗЯ выдумывать товары, цены, наличие, цвета. Используй ТОЛЬКО каталог ниже.\n"
        "2) Если точно не уверен — скажи, что нужно фото/уточнение модели.\n"
        "3) Отвечай СРАЗУ на двух языках: сначала RU, затем разделитель '———', затем KZ.\n"
        "4) Если пользователь спрашивает цену по фото/названию — дай точную цену из каталога.\n\n"
        f"КАТАЛОГ(JSON): {json.dumps(items_list, ensure_ascii=False)}\n\n"
        f"Сообщение клиента: {user_text}\n\n"
        "Сформируй ответ.\n"
    )

def build_vision_match_prompt(catalog_items: Dict[str, Any]) -> str:
    # Модель должна выбрать один item_key или 'unknown'
    items = []
    for k, it in catalog_items.items():
        items.append({
            "key": k,
            "name": it.get("name", ""),
            "desc": it.get("desc", ""),
            "colors": it.get("colors", []),
        })

    return (
        "Ты видишь фото сумки. Твоя задача — сопоставить фото с одним из товаров каталога.\n"
        "Правила:\n"
        "1) Выбери один key из каталога, только если уверен.\n"
        "2) Если не уверен — верни unknown.\n"
        "3) Ответ строго в JSON: {\"match\":\"<key|unknown>\",\"confidence\":0-100,\"reason\":\"коротко\"}\n\n"
        f"Каталог(JSON): {json.dumps(items, ensure_ascii=False)}\n"
    )

def ai_match_photo_to_catalog(img_b64: str, catalog_items: Dict[str, Any]) -> Tuple[str, int, str]:
    system = "Ты аккуратный ассистент. Никаких фантазий. Строго JSON."
    prompt = build_vision_match_prompt(catalog_items)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
        ]}
    ]
    text = openai_chat(messages, max_tokens=300, temperature=0.1)

    # попробуем вытащить JSON безопасно
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return ("unknown", 0, "no_json")
    try:
        obj = json.loads(m.group(0))
        match = str(obj.get("match", "unknown"))
        conf = int(obj.get("confidence", 0))
        reason = str(obj.get("reason", ""))
        return (match, conf, reason)
    except Exception:
        return ("unknown", 0, "bad_json")

# ===================== BOT CORE =====================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # НЕ показываем кнопки сразу — как ты просил
    await update.message.reply_text(short_welcome())
    return ST_MAIN

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(help_text())

async def cmd_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_catalog()
    items = data.get("items", {})
    if not items:
        await update.message.reply_text("Каталог пуст. Админ добавит товары через /add.")
        return
    lines = ["📦 Каталог / Каталог:\n"]
    for k, it in items.items():
        lines.append(f"• {it.get('name','—')} — {it.get('price',0)} ₸")
    await update.message.reply_text("\n".join(lines))

# ---------- ADD FLOW (admin) ----------
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("Эта команда только для администратора.")
        return ConversationHandler.END

    context.user_data["add_item"] = {}
    await update.message.reply_text("➕ Добавление товара\n\nШаг 1/5: Напишите НАЗВАНИЕ модели (например: Luna Mini)")
    return ST_ADD_NAME

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if len(name) < 2:
        await update.message.reply_text("Название слишком короткое. Напишите ещё раз.")
        return ST_ADD_NAME
    context.user_data["add_item"]["name"] = name
    await update.message.reply_text("Шаг 2/5: Напишите ЦЕНУ в тенге (например: 32900)")
    return ST_ADD_PRICE

async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price = normalize_price(update.message.text or "")
    if price is None or price <= 0:
        await update.message.reply_text("Не понял цену. Пример: 32900")
        return ST_ADD_PRICE
    context.user_data["add_item"]["price"] = price
    await update.message.reply_text("Шаг 3/5: Напишите ЦВЕТА через запятую (например: чёрный, бежевый). Можно пропустить: '-'")
    return ST_ADD_COLORS

async def add_colors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    colors = []
    if t != "-":
        colors = parse_colors(t)
    context.user_data["add_item"]["colors"] = colors
    await update.message.reply_text("Шаг 4/5: Напишите короткое ОПИСАНИЕ (или '-' чтобы пропустить)")
    return ST_ADD_DESC

async def add_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    desc = "" if t == "-" else t
    context.user_data["add_item"]["desc"] = desc
    await update.message.reply_text("Шаг 5/5: Отправьте ФОТО этой модели (как фото, не документ).")
    return ST_ADD_PHOTO

async def add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Нужно именно фото. Пришлите фото модели.")
        return ST_ADD_PHOTO

    photo = update.message.photo[-1]
    file_unique_id = photo.file_unique_id  # ✅ ключ для узнавания у всех пользователей
    file_id = photo.file_id

    data = load_catalog()
    items = data.get("items", {})
    photo_index = data.get("photo_index", {})

    item = context.user_data.get("add_item", {})
    name = item.get("name", "—")
    key = make_item_key(name)

    # если key занят — делаем уникальный
    if key in items:
        key = f"{key}_{int(time.time())}"

    items[key] = {
        "name": name,
        "price": int(item.get("price", 0)),
        "colors": item.get("colors", []),
        "desc": item.get("desc", ""),
        "photo_file_id": file_id,          # удобно показать фото потом
        "photo_unique_id": file_unique_id  # главное для поиска
    }
    photo_index[file_unique_id] = key

    data["items"] = items
    data["photo_index"] = photo_index
    save_catalog(data)

    context.user_data.pop("add_item", None)

    await update.message.reply_text(
        "✅ Товар добавлен!\n\n"
        f"Ключ: {key}\n"
        f"Модель: {name}\n"
        f"Фото привязано (узнается у любых пользователей)."
    )
    return ConversationHandler.END

async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("add_item", None)
    await update.message.reply_text("Ок, отменил добавление товара.")
    return ConversationHandler.END

# ---------- MAIN HANDLER ----------
async def handle_text_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return ST_MAIN

    data = load_catalog()
    items = data.get("items", {})

    # Если ИИ есть — используем консультанта (строго по каталогу)
    if ai_enabled() and items:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        prompt = build_consultant_prompt_ru_kz(items, text)
        answer = openai_chat([{"role": "system", "content": "Ты полезный ассистент."},
                              {"role": "user", "content": prompt}],
                             max_tokens=500,
                             temperature=0.2)
        await update.message.reply_text(answer)
        return ST_MAIN

    # Без ИИ — простая логика
    # Попытка найти по названию
    t = text.lower()
    found = None
    for k, it in items.items():
        if it.get("name", "").lower() in t:
            found = it
            break
    if found:
        await update.message.reply_text(format_item_ru_kz(found))
        return ST_MAIN

    await update.message.reply_text(
        "Понял 👍\n"
        "Чтобы я дал точный ответ — пришлите фото сумки или напишите название модели.\n\n"
        "Түсіндім 👍\n"
        "Дәл жауап беру үшін — сөмкенің фотосын жіберіңіз немесе модель атауын жазыңыз."
    )
    return ST_MAIN

async def handle_photo_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        return ST_MAIN

    data = load_catalog()
    items = data.get("items", {})
    photo_index = data.get("photo_index", {})

    photo = update.message.photo[-1]
    uniq = photo.file_unique_id

    # 1) Сначала точное узнавание по photo_unique_id
    if uniq in photo_index:
        key = photo_index[uniq]
        item = items.get(key)
        if item:
            # “точно эта модель” — как ты просил
            await update.message.reply_text(
                "✅ Узнал модель (точное совпадение по базе).\n\n" + format_item_ru_kz(item)
            )
            return ST_MAIN

    # 2) Если не нашли — ИИ сопоставление (если включен)
    if ai_enabled() and items:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

        # скачиваем фото как base64 (через Telegram file)
        f = await context.bot.get_file(photo.file_id)
        b = await f.download_as_bytearray()
        img_b64 = base64.b64encode(bytes(b)).decode("utf-8")

        match, conf, reason = ai_match_photo_to_catalog(img_b64, items)

        if match != "unknown" and match in items and conf >= 70:
            item = items[match]
            await update.message.reply_text(
                f"✅ Предположительно это: {item.get('name','—')} (уверенность {conf}%)\n"
                f"Причина: {reason}\n\n"
                + format_item_ru_kz(item)
                + "\nЕсли хотите 100% — пришлите фото под другим углом / логотип / бирку.\n"
                + "100% болу үшін — басқа ракурстан фото жіберіңіз / логотип / бирка."
            )
            return ST_MAIN

        await update.message.reply_text(
            "Не нашёл точного совпадения по базе.\n"
            "Пожалуйста, напишите название модели или пришлите ещё фото (другой ракурс).\n\n"
            "База бойынша дәл сәйкестік таппадым.\n"
            "Модель атауын жазыңыз немесе тағы фото жіберіңіз (басқа ракурс)."
        )
        return ST_MAIN

    # 3) Без ИИ — просто просим уточнение
    await update.message.reply_text(
        "Пока не могу точно узнать модель по фото.\n"
        "Пришлите название модели или админ должен добавить эту модель в базу через /add.\n\n"
        "Әзірге фото бойынша дәл танымай тұрмын.\n"
        "Модель атауын жазыңыз немесе админ /add арқылы базаға қосуы керек."
    )
    return ST_MAIN

# ===================== APP BUILD =====================

def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("catalog", cmd_catalog))

    # /add (admin) — диалог
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            ST_ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ST_ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)],
            ST_ADD_COLORS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_colors)],
            ST_ADD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_desc)],
            ST_ADD_PHOTO: [MessageHandler(filters.PHOTO, add_photo)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        allow_reentry=True,
    )
    app.add_handler(add_conv)

    # Основной “человечный” режим без кнопок
    main_handlers = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            ST_MAIN: [
                MessageHandler(filters.PHOTO, handle_photo_main),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_main),
            ]
        },
        fallbacks=[CommandHandler("help", cmd_help)],
        allow_reentry=True,
    )
    app.add_handler(main_handlers)

    # на всякий случай: фото даже если не в диалоге
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_main))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_main))

    return app

def main():
    app = build_app()
    log.info("Bot started at %s", now_ts())
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
