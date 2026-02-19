import os
import json
import base64
import logging
from typing import Dict, Any, Optional, List, Tuple

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

from openai import OpenAI

# -----------------------------
# НАСТРОЙКИ / ENV
# -----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

# Админы (через запятую): "123,456"
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = set()
if ADMIN_IDS_RAW:
    try:
        ADMIN_IDS = {int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip()}
    except Exception:
        ADMIN_IDS = set()

CATALOG_PATH = os.getenv("CATALOG_PATH", "catalog.json")
ORDERS_PATH = os.getenv("ORDERS_PATH", "orders.json")

# Модель для чата и для vision
OPENAI_MODEL_TEXT = os.getenv("OPENAI_MODEL_TEXT", "gpt-4o-mini")
OPENAI_MODEL_VISION = os.getenv("OPENAI_MODEL_VISION", "gpt-4o-mini")

# -----------------------------
# ЛОГИ
# -----------------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("magazin_sumok_bot")

# -----------------------------
# ИНИЦИАЛИЗАЦИЯ OpenAI
# -----------------------------
client = None
if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------
# СОСТОЯНИЯ ДЛЯ ОФОРМЛЕНИЯ ЗАКАЗА
# -----------------------------
ORDER_NAME, ORDER_PHONE, ORDER_CITY, ORDER_ADDRESS, ORDER_COMMENT = range(5)

# -----------------------------
# УТИЛИТЫ: JSON (каталог/заказы)
# -----------------------------
def load_json(path: str, default: Any) -> Any:
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.exception("Ошибка чтения JSON %s: %s", path, e)
        return default

def save_json(path: str, data: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Ошибка записи JSON %s: %s", path, e)

def load_catalog() -> Dict[str, Any]:
    return load_json(CATALOG_PATH, {"items": []})

def save_catalog(cat: Dict[str, Any]) -> None:
    save_json(CATALOG_PATH, cat)

def load_orders() -> Dict[str, Any]:
    return load_json(ORDERS_PATH, {"orders": []})

def save_orders(data: Dict[str, Any]) -> None:
    save_json(ORDERS_PATH, data)

def is_admin(user_id: int) -> bool:
    # Если ADMIN_IDS не задан — админом считаем НИКОГО (безопасно).
    return user_id in ADMIN_IDS

def normalize_text(s: str) -> str:
    return (s or "").strip().lower()

def catalog_brief(items: List[Dict[str, Any]]) -> str:
    # Короткое описание каталога для промпта
    lines = []
    for it in items[:80]:
        lines.append(
            f"- id: {it.get('id')} | name: {it.get('name')} | price_kzt: {it.get('price_kzt')} | "
            f"colors: {', '.join(it.get('colors', [])[:8])} | keywords: {', '.join(it.get('keywords', [])[:10])}"
        )
    return "\n".join(lines)

def find_item_by_id(items: List[Dict[str, Any]], item_id: str) -> Optional[Dict[str, Any]]:
    for it in items:
        if str(it.get("id", "")).strip() == str(item_id).strip():
            return it
    return None

def find_item_by_model_text(items: List[Dict[str, Any]], text: str) -> Optional[Dict[str, Any]]:
    t = normalize_text(text)
    if not t:
        return None
    # Сначала точные совпадения по имени/id
    for it in items:
        if normalize_text(it.get("id", "")) == t:
            return it
        if normalize_text(it.get("name", "")) == t:
            return it

    # Затем по ключевым словам
    for it in items:
        kws = [normalize_text(x) for x in it.get("keywords", [])]
        if any(k and k in t for k in kws):
            return it

    # Частичное совпадение имени
    for it in items:
        name = normalize_text(it.get("name", ""))
        if name and name in t:
            return it

    return None

def format_item_card(item: Dict[str, Any]) -> str:
    name = item.get("name", "—")
    price = item.get("price_kzt", "—")
    colors = item.get("colors", [])
    desc = item.get("description", "")

    colors_line = ""
    if colors:
        colors_line = f"\nЦвета: {', '.join(colors)}"

    desc_line = f"\nОписание: {desc}" if desc else ""

    return f"✅ Модель: {name}\n💰 Цена: {price} ₸{colors_line}{desc_line}"

# -----------------------------
# КНОПКИ / МЕНЮ
# -----------------------------
def menu_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("💰 Узнать цену", callback_data="menu_price")],
        [InlineKeyboardButton("📦 Каталог", callback_data="menu_catalog")],
        [InlineKeyboardButton("🚚 Доставка", callback_data="menu_delivery")],
        [InlineKeyboardButton("🧾 Оформить заказ", callback_data="menu_order")],
        [InlineKeyboardButton("👩‍💼 Менеджер", callback_data="menu_manager")],
    ]
    return InlineKeyboardMarkup(kb)

# -----------------------------
# OpenAI: VISION MATCH
# -----------------------------
async def download_photo_bytes(update: Update) -> Optional[bytes]:
    if not update.message or not update.message.photo:
        return None
    photo = update.message.photo[-1]
    file = await photo.get_file()
    b = await file.download_as_bytearray()
    return bytes(b)

def b64_image(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")

def exact_match_by_file_id(items: List[Dict[str, Any]], telegram_file_id: str) -> Optional[Dict[str, Any]]:
    for it in items:
        fids = it.get("photo_file_ids", []) or []
        if telegram_file_id in fids:
            return it
    return None

def ensure_openai() -> None:
    if client is None:
        raise RuntimeError("OPENAI_API_KEY не задан. Добавь переменную OPENAI_API_KEY в Railway.")

async def match_bag_with_openai(items: List[Dict[str, Any]], image_bytes: bytes) -> Tuple[Optional[str], float, str]:
    """
    Возвращает: (item_id или None, confidence 0..1, короткое объяснение)
    """
    ensure_openai()

    brief = catalog_brief(items)
    img_b64 = b64_image(image_bytes)

    sys = (
        "Ты ассистент магазина сумок. Твоя задача — сопоставить фото сумки с одним товаром из каталога.\n"
        "ВАЖНО: если не уверен, верни NONE.\n"
        "Нельзя придумывать модель. Нельзя выбирать случайно.\n"
        "Верни строго JSON по схеме:\n"
        "{"
        '  "match_id": "ID_ИЛИ_NONE",'
        '  "confidence": 0.0,'
        '  "reason": "коротко почему"'
        "}\n"
        "confidence: 0..1. Выбирай match_id только если confidence >= 0.80.\n"
    )

    user_text = (
        "Каталог (кратко):\n"
        f"{brief}\n\n"
        "Сопоставь сумку на фото с одним из товаров. Если точного совпадения нет — match_id = NONE.\n"
        "Верни JSON."
    )

    resp = client.chat.completions.create(
        model=OPENAI_MODEL_VISION,
        messages=[
            {"role": "system", "content": sys},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    raw = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
        match_id = data.get("match_id")
        conf = float(data.get("confidence", 0.0))
        reason = str(data.get("reason", "")).strip()
        if not match_id or str(match_id).upper() == "NONE" or conf < 0.80:
            return None, conf, reason
        return str(match_id), conf, reason
    except Exception:
        return None, 0.0, "Не удалось распарсить ответ модели"

# -----------------------------
# OpenAI: ИИ-КОНСУЛЬТАНТ
# -----------------------------
async def ai_consultant_answer(items: List[Dict[str, Any]], user_text: str) -> str:
    ensure_openai()

    brief = catalog_brief(items)

    sys = (
        "Ты — вежливый виртуальный менеджер магазина сумок.\n"
        "Правила:\n"
        "1) Отвечай ТОЛЬКО по-русски.\n"
        "2) Не придумывай цены, модели и наличие. Используй только каталог.\n"
        "3) Если клиент спрашивает цену конкретной сумки, но не указал модель/не отправил фото — попроси модель или фото.\n"
        "4) Если клиент хочет подобрать сумку — задай 2-3 уточняющих вопроса (бюджет, размер, цвет, стиль) и предложи 1-3 варианта из каталога.\n"
        "5) Пиши коротко и по делу.\n"
    )

    user = (
        "Каталог (кратко):\n"
        f"{brief}\n\n"
        f"Сообщение клиента:\n{user_text}\n\n"
        "Ответь как менеджер. Если нужна модель/фото — попроси."
    )

    resp = client.chat.completions.create(
        model=OPENAI_MODEL_TEXT,
        messages=[
            {"role": "system", "content": sys},
            {"role": "user", "content": user},
        ],
        temperature=0.4,
    )
    return (resp.choices[0].message.content or "").strip()

# -----------------------------
# ХЕНДЛЕРЫ
# -----------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Здравствуйте! Я виртуальный менеджер магазина сумок 👜\n\n"
        "Напишите, что вам нужно:\n"
        "• «цена» / «сколько стоит?»\n"
        "• пришлите фото сумки — скажу модель и цену\n"
        "• или напишите название модели\n\n"
        "Если нужно меню — напишите «меню» или команду /menu."
    )
    await update.message.reply_text(text)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Команды:\n"
        "/start — начать\n"
        "/menu — показать меню\n"
        "/help — помощь\n\n"
        "Для админа:\n"
        "/add — добавить товар\n"
        "/bind — привязать фото к товару\n"
        "/list — список товаров\n"
    )
    await update.message.reply_text(text)

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Выберите действие:", reply_markup=menu_keyboard())

async def on_menu_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # если пользователь написал "меню"
    await update.message.reply_text("Выберите действие:", reply_markup=menu_keyboard())

async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    data = q.data
    cat = load_catalog()
    items = cat.get("items", [])

    if data == "menu_price":
        context.user_data["mode"] = "price"
        await q.message.reply_text(
            "Ок 👍\nПришлите фото сумки или напишите название модели — я назову точную цену."
        )
        return

    if data == "menu_catalog":
        if not items:
            await q.message.reply_text("Каталог пока пуст.")
            return
        lines = ["📦 Каталог:"]
        for it in items[:30]:
            lines.append(f"• {it.get('name')} — {it.get('price_kzt')} ₸")
        await q.message.reply_text("\n".join(lines))
        return

    if data == "menu_delivery":
        await q.message.reply_text(
            "🚚 Доставка:\n"
            "• По городу: 1–2 дня\n"
            "• По Казахстану: 2–5 дней\n\n"
            "Напишите ваш город — подскажу точнее."
        )
        return

    if data == "menu_order":
        await q.message.reply_text("Начинаем оформление заказа ✅")
        return await start_order(update, context)

    if data == "menu_manager":
        await q.message.reply_text(
            "👩‍💼 Менеджер:\n"
            "Напишите ваш вопрос. Если нужно — я передам менеджеру ваши контакты."
        )
        return

# -----------------------------
# ОФОРМЛЕНИЕ ЗАКАЗА (Conversation)
# -----------------------------
async def start_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # может прийти как callback_query, так и message
    if update.callback_query:
        msg = update.callback_query.message
    else:
        msg = update.message

    context.user_data["order"] = {}
    await msg.reply_text("Как вас зовут?")
    return ORDER_NAME

async def order_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["order"]["name"] = update.message.text.strip()
    await update.message.reply_text("Ваш номер телефона? (пример: +7 777 123 45 67)")
    return ORDER_PHONE

async def order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["order"]["phone"] = update.message.text.strip()
    await update.message.reply_text("Ваш город?")
    return ORDER_CITY

async def order_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["order"]["city"] = update.message.text.strip()
    await update.message.reply_text("Адрес доставки или удобный ориентир?")
    return ORDER_ADDRESS

async def order_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["order"]["address"] = update.message.text.strip()
    await update.message.reply_text("Комментарий к заказу (какая модель/цвет/пожелания)?")
    return ORDER_COMMENT

async def order_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["order"]["comment"] = update.message.text.strip()

    # сохраним заказ
    orders = load_orders()
    orders["orders"].append(
        {
            "user_id": update.effective_user.id,
            "username": update.effective_user.username,
            **context.user_data["order"],
        }
    )
    save_orders(orders)

    await update.message.reply_text(
        "✅ Заявка принята!\n"
        "Менеджер свяжется с вами в ближайшее время.\n\n"
        "Если хотите — можете отправить фото сумки или написать модель, чтобы я сразу уточнил цену."
    )
    context.user_data["mode"] = None
    return ConversationHandler.END

async def order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["order"] = {}
    await update.message.reply_text("Оформление заказа отменено. Напишите «меню», если нужно.")
    return ConversationHandler.END

# -----------------------------
# АДМИН: добавление товара и привязка фото
# -----------------------------
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Команда доступна только администратору.")
        return
    cat = load_catalog()
    items = cat.get("items", [])
    if not items:
        await update.message.reply_text("Каталог пуст.")
        return
    lines = ["Товары:"]
    for it in items[:80]:
        lines.append(f"- id: {it.get('id')} | {it.get('name')} | {it.get('price_kzt')} ₸")
    await update.message.reply_text("\n".join(lines))

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /add id|Название|цена|цвет1,цвет2|ключ1,ключ2|описание
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Команда доступна только администратору.")
        return

    text = update.message.text.replace("/add", "", 1).strip()
    if not text:
        await update.message.reply_text(
            "Формат:\n"
            "/add id|Название|цена|цвет1,цвет2|ключ1,ключ2|описание\n\n"
            "Пример:\n"
            "/add ArianaClassic|Ariana Classic|45000|чёрный,бежевый|ariana,classic,классика|Классическая сумка на плечо"
        )
        return

    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 3:
        await update.message.reply_text("Недостаточно данных. Нужно минимум: id|Название|цена ...")
        return

    item_id = parts[0]
    name = parts[1]
    try:
        price = int(parts[2])
    except Exception:
        await update.message.reply_text("Цена должна быть числом (в тенге).")
        return

    colors = []
    keywords = []
    desc = ""

    if len(parts) >= 4 and parts[3]:
        colors = [c.strip() for c in parts[3].split(",") if c.strip()]
    if len(parts) >= 5 and parts[4]:
        keywords = [k.strip() for k in parts[4].split(",") if k.strip()]
    if len(parts) >= 6:
        desc = parts[5].strip()

    cat = load_catalog()
    items = cat.get("items", [])

    if find_item_by_id(items, item_id):
        await update.message.reply_text("❌ Такой id уже существует. Возьми другой id.")
        return

    items.append(
        {
            "id": item_id,
            "name": name,
            "price_kzt": price,
            "colors": colors,
            "description": desc,
            "keywords": keywords,
            "photo_file_ids": [],
        }
    )
    cat["items"] = items
    save_catalog(cat)

    await update.message.reply_text(
        "✅ Товар добавлен.\n"
        f"{item_id} — {name} — {price} ₸\n\n"
        "Теперь можно привязать фото:\n"
        f"/bind {item_id}\n"
        "и затем отправить фото."
    )

async def cmd_bind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /bind ITEM_ID -> следующий присланный фото привяжется к товару
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Команда доступна только администратору.")
        return

    arg = update.message.text.replace("/bind", "", 1).strip()
    if not arg:
        await update.message.reply_text("Формат: /bind ITEM_ID\nПример: /bind ArianaClassic")
        return

    cat = load_catalog()
    items = cat.get("items", [])
    item = find_item_by_id(items, arg)
    if not item:
        await update.message.reply_text("❌ Не нашёл товар с таким id. Посмотри /list")
        return

    context.user_data["bind_item_id"] = arg
    await update.message.reply_text(
        f"Ок. Теперь отправь ОДНО фото этой модели — я привяжу его к {arg}.\n"
        "После привязки клиент с таким же фото будет получать точную модель и цену."
    )

# -----------------------------
# ОБРАБОТКА ФОТО
# -----------------------------
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cat = load_catalog()
    items = cat.get("items", [])

    # 1) Если админ в режиме привязки
    bind_item_id = context.user_data.get("bind_item_id")
    if bind_item_id and is_admin(update.effective_user.id):
        if not update.message.photo:
            return
        file_id = update.message.photo[-1].file_id
        item = find_item_by_id(items, bind_item_id)
        if not item:
            context.user_data["bind_item_id"] = None
            await update.message.reply_text("❌ Ошибка: товар не найден. Отмени /bind и попробуй снова.")
            return

        fids = item.get("photo_file_ids", []) or []
        if file_id not in fids:
            fids.append(file_id)
        item["photo_file_ids"] = fids
        save_catalog(cat)

        context.user_data["bind_item_id"] = None
        await update.message.reply_text(f"✅ Фото привязано к модели {item.get('name')} ({bind_item_id}).")
        return

    # 2) Обычный пользователь: узнать модель/цену
    # Сначала пробуем точное совпадение по file_id
    telegram_file_id = update.message.photo[-1].file_id
    exact = exact_match_by_file_id(items, telegram_file_id)
    if exact:
        await update.message.reply_text(format_item_card(exact))
        return

    # Если каталог пуст
    if not items:
        await update.message.reply_text("Каталог пока пуст. Напишите менеджеру.")
        return

    # 3) Если OpenAI не подключён — честно скажем
    if client is None:
        await update.message.reply_text(
            "Я получил фото ✅\n"
            "Но ИИ-распознавание сейчас не настроено (нет ключа OPENAI_API_KEY).\n"
            "Напишите название модели, и я подскажу цену."
        )
        return

    await update.message.reply_text("Секунду… распознаю модель по фото 🔎")

    try:
        image_bytes = await download_photo_bytes(update)
        if not image_bytes:
            await update.message.reply_text("Не удалось скачать фото. Попробуйте ещё раз.")
            return

        match_id, conf, reason = await match_bag_with_openai(items, image_bytes)
        if not match_id:
            await update.message.reply_text(
                "Я не могу уверенно определить модель по этому фото.\n"
                "Пожалуйста, отправьте фото ближе (логотип/фурнитура) или напишите название модели."
            )
            return

        item = find_item_by_id(items, match_id)
        if not item:
            await update.message.reply_text(
                "Я нашёл похожую модель, но в каталоге её нет.\n"
                "Пожалуйста, уточните модель или напишите менеджеру."
            )
            return

        # Важно: говорим уверенно, только если conf>=0.80 (мы это уже проверили)
        await update.message.reply_text(format_item_card(item))

    except Exception as e:
        logger.exception("Ошибка распознавания: %s", e)
        await update.message.reply_text(
            "Произошла ошибка при распознавании фото. Попробуйте ещё раз или напишите модель текстом."
        )

# -----------------------------
# ОБРАБОТКА ТЕКСТА (ИИ-консультант + поиск по модели)
# -----------------------------
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    t = normalize_text(text)

    # слово "меню"
    if t == "меню":
        await on_menu_word(update, context)
        return

    # короткие триггеры "цена/сколько стоит"
    if any(x in t for x in ["цена", "сколько стоит", "сколько стоит?", "бағасы", "скока стоит"]):
        context.user_data["mode"] = "price"
        await update.message.reply_text("Ок 👍 Пришлите фото сумки или напишите название модели — я назову цену.")
        return

    cat = load_catalog()
    items = cat.get("items", [])

    # Если пользователь в режиме "price" — попробуем найти по тексту модель
    if context.user_data.get("mode") == "price":
        item = find_item_by_model_text(items, text)
        if item:
            await update.message.reply_text(format_item_card(item))
            context.user_data["mode"] = None
            return
        # Если не нашли — попросим фото/модель точнее
        await update.message.reply_text(
            "Чтобы назвать точную цену, мне нужна модель или фото.\n"
            "Напишите название модели (как в каталоге) или пришлите фото сумки."
        )
        return

    # По умолчанию — ИИ-консультант
    if not items:
        await update.message.reply_text(
            "Пока каталог пуст, но я могу ответить на вопросы по доставке/оформлению.\n"
            "Напишите, что вас интересует."
        )
        return

    if client is None:
        # Без OpenAI — простой режим
        item = find_item_by_model_text(items, text)
        if item:
            await update.message.reply_text(format_item_card(item))
            return
        await update.message.reply_text(
            "Понял 👍\n"
            "Напишите название модели или пришлите фото сумки — я подскажу цену и наличие цветов.\n"
            "Если хотите меню — напишите «меню»."
        )
        return

    try:
        answer = await ai_consultant_answer(items, text)
        if not answer:
            answer = "Понял 👍 Уточните, пожалуйста, модель или пришлите фото сумки."
        await update.message.reply_text(answer)
    except Exception as e:
        logger.exception("Ошибка AI-консультанта: %s", e)
        await update.message.reply_text(
            "Я понял ваш запрос, но сейчас не могу ответить автоматически.\n"
            "Пришлите фото сумки или напишите модель — я уточню цену."
        )

# -----------------------------
# ERROR HANDLER
# -----------------------------
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Ошибка в обработчике: %s", context.error)

# -----------------------------
# MAIN
# -----------------------------
def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty. Set environment variable BOT_TOKEN.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Conversation: оформление заказа
    order_conv = ConversationHandler(
        entry_points=[
            CommandHandler("order", start_order),
            CallbackQueryHandler(on_menu_click, pattern="^menu_order$"),
        ],
        states={
            ORDER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_name)],
            ORDER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
            ORDER_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_city)],
            ORDER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_address)],
            ORDER_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_comment)],
        },
        fallbacks=[CommandHandler("cancel", order_cancel)],
        allow_reentry=True,
        per_message=True,
    )

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("menu", cmd_menu))

    # Админ-команды
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("bind", cmd_bind))
    app.add_handler(CommandHandler("list", cmd_list))

    # Заказы
    app.add_handler(order_conv)

    # Меню-кнопки
    app.add_handler(CallbackQueryHandler(on_menu_click, pattern="^menu_"))

    # Фото
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))

    # Текст (в конце)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # Ошибки
    app.add_error_handler(on_error)

    logger.info("Bot started.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
