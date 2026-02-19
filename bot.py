import os
import re
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# -------------------- ENV --------------------
load_dotenv()
TELEGRAM_TOKEN = (os.getenv("TELEGRAM_TOKEN") or "").strip()
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
ADMIN_ID = int((os.getenv("ADMIN_ID") or "0").strip() or "0")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set")

# -------------------- LOGGING --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("bags-ai-demo")

# -------------------- CATALOG (DEMO) --------------------
CATALOG: Dict[str, Dict[str, Any]] = {
    "luna_mini": {
        "name": "Luna Mini",
        "price": 32900,
        "colors": ["чёрный", "бежевый"],
        "desc": "Компактная структурированная сумка, золотая фурнитура, минимализм.",
    },
    "aura": {
        "name": "AURA",
        "price": 45900,
        "colors": ["чёрный", "молочный"],
        "desc": "Строгая форма, премиальный стиль, мягкая кожа.",
    },
    "vera": {
        "name": "Vera",
        "price": 38900,
        "colors": ["шоколад", "чёрный"],
        "desc": "Вместительная повседневная модель, универсальный дизайн.",
    },
    "nova": {
        "name": "NOVA Premium",
        "price": 51900,
        "colors": ["чёрный"],
        "desc": "Премиальная линейка, плотная форма, выглядит дороже остальных.",
    },
    "iris": {
        "name": "Iris",
        "price": 29900,
        "colors": ["серый", "чёрный"],
        "desc": "Лёгкая базовая сумка на каждый день, отличный вариант на подарок.",
    },
}

# -------------------- STORAGE: demo photo mapping --------------------
DEMO_PHOTOS_FILE = "demo_photos.json"
PHOTO_MODEL_MAP: Dict[str, str] = {}  # file_id -> model_key

def load_demo_map() -> None:
    global PHOTO_MODEL_MAP
    try:
        with open(DEMO_PHOTOS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            PHOTO_MODEL_MAP = {str(k): str(v) for k, v in data.items()}
            logger.info("Loaded demo photo map: %d entries", len(PHOTO_MODEL_MAP))
    except FileNotFoundError:
        PHOTO_MODEL_MAP = {}
    except Exception as e:
        logger.warning("Failed to load demo map: %s", e)
        PHOTO_MODEL_MAP = {}

def save_demo_map() -> None:
    try:
        with open(DEMO_PHOTOS_FILE, "w", encoding="utf-8") as f:
            json.dump(PHOTO_MODEL_MAP, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Failed to save demo map: %s", e)

# -------------------- UI --------------------
def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👜 Узнать цену", callback_data="price")],
        [InlineKeyboardButton("📦 Каталог", callback_data="catalog")],
        [InlineKeyboardButton("🚚 Доставка", callback_data="delivery")],
        [InlineKeyboardButton("📝 Оформить заказ", callback_data="order")],
        [InlineKeyboardButton("👩‍💼 Менеджер", callback_data="manager")],
    ])

def kb_catalog() -> InlineKeyboardMarkup:
    rows = []
    for k, item in CATALOG.items():
        rows.append([InlineKeyboardButton(f"{item['name']} — {item['price']} ₸", callback_data=f"item:{k}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def kb_item(model_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Оформить заказ", callback_data=f"order:{model_key}")],
        [InlineKeyboardButton("📦 Каталог", callback_data="catalog")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")],
    ])

def kb_demo_models() -> InlineKeyboardMarkup:
    rows = []
    for k, item in CATALOG.items():
        rows.append([InlineKeyboardButton(item["name"], callback_data=f"demo_set:{k}")])
    rows.append([InlineKeyboardButton("⬅️ Закрыть", callback_data="demo_cancel")])
    return InlineKeyboardMarkup(rows)

# -------------------- HELPERS --------------------
def is_admin(user_id: int) -> bool:
    return ADMIN_ID and user_id == ADMIN_ID

def normalize_phone(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^\d+]", "", s)
    return s

def digits_only(s: str) -> str:
    return re.sub(r"\D", "", s or "")

def find_model_from_text(text: str) -> Optional[str]:
    t = (text or "").lower().strip()
    if not t:
        return None
    # exact contains
    for k, item in CATALOG.items():
        if item["name"].lower() in t:
            return k
    # partial by words
    words = [w for w in re.split(r"\s+", t) if w]
    for k, item in CATALOG.items():
        name = item["name"].lower()
        if any(w in name for w in words):
            return k
    return None

def catalog_brief() -> str:
    lines = []
    for k, item in CATALOG.items():
        lines.append(f"- {item['name']}: {item['price']} ₸ (цвета: {', '.join(item['colors'])})")
    return "\n".join(lines)

# -------------------- AI (OpenAI) --------------------
# Мы используем ИИ для консультаций по тексту, но НЕ для цен и фактов из каталога.
# Если ИИ не доступен, бот работает как обычный менеджер.
SYSTEM_PROMPT = (
    "Ты — AI-менеджер магазина сумок. Пиши по-русски.\n"
    "Цель: помочь выбрать модель, назвать цену/цвета из каталога и довести до заявки.\n"
    "ЖЁСТКИЕ ПРАВИЛА:\n"
    "1) Никогда не придумывай цену/наличие/скидки/условия доставки. Используй только данные каталога.\n"
    "2) Если модель не ясна — попроси уточнить или предложи выбрать из каталога.\n"
    "3) На странные сообщения отвечай спокойно и возвращай к делу.\n"
    "4) Пиши коротко: 1–5 строк, без Markdown и без спецсимволов форматирования.\n"
    "5) Всегда предлагай следующий шаг: выбрать модель, прислать фото, оформить заказ.\n"
)

async def ask_ai(text: str) -> str:
    if not OPENAI_API_KEY:
        # Фолбэк без ИИ
        return (
            "Могу подсказать цену и помочь с выбором.\n"
            "Напишите модель или отправьте фото, либо откройте каталог."
        )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        user_msg = (
            f"Сообщение клиента: {text}\n\n"
            f"Каталог:\n{catalog_brief()}\n\n"
            "Ответь как менеджер. Если клиент спрашивает цену — назови цену только если модель ясна."
        )

        # “typing…”
        # (действие показываем в обработчике, здесь не трогаем update)

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.4,
        )
        out = (resp.choices[0].message.content or "").strip()
        # страховка от пустого ответа
        if not out:
            out = "Уточните, пожалуйста, модель или пришлите фото — назову точную цену."
        # убираем возможные лишние тройные кавычки/кодблоки
        out = out.replace("```", "").strip()
        return out
    except Exception as e:
        logger.warning("AI error: %s", e)
        return (
            "Сейчас могу подсказать цену и помочь с выбором.\n"
            "Напишите модель или отправьте фото, либо откройте каталог."
        )

# -------------------- STATE (manual, stable) --------------------
# Мы не используем ConversationHandler — поэтому НЕ будет зависаний.
# Всё держим в context.user_data["state"].
STATE_NONE = "NONE"
STATE_WAIT_MODEL = "WAIT_MODEL"
STATE_WAIT_CITY = "WAIT_CITY"
STATE_WAIT_PHONE = "WAIT_PHONE"
STATE_DEMO_WAIT_PHOTO = "DEMO_WAIT_PHOTO"

def set_state(context: ContextTypes.DEFAULT_TYPE, st: str) -> None:
    context.user_data["state"] = st

def get_state(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("state", STATE_NONE)

# -------------------- HANDLERS --------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_state(context, STATE_NONE)
    context.user_data.pop("selected_model", None)
    context.user_data.pop("order_city", None)

    await update.message.reply_text(
        "Здравствуйте! Я AI-менеджер магазина сумок 👜\n"
        "Отправьте фото сумки или напишите, что вас интересует.\n\n"
        "Можно выбрать действия кнопками:",
        reply_markup=kb_main()
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/start — начать\n"
        "/demo — привязать демо-фото к модели (только админ)\n"
        "/reset — сбросить состояние\n"
    )

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_state(context, STATE_NONE)
    context.user_data.pop("selected_model", None)
    context.user_data.pop("order_city", None)
    context.user_data.pop("demo_model_key", None)
    await update.message.reply_text("Сбросил. Открываю меню:", reply_markup=kb_main())

async def cmd_demo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Команда доступна только администратору.")
        return
    set_state(context, STATE_NONE)
    context.user_data.pop("demo_model_key", None)

    await update.message.reply_text(
        "ДЕМО: выберите модель, к которой привяжем следующее фото:",
        reply_markup=kb_demo_models()
    )

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    if data == "back":
        set_state(context, STATE_NONE)
        await q.message.reply_text("Главное меню:", reply_markup=kb_main())
        return

    if data == "price":
        set_state(context, STATE_WAIT_MODEL)
        await q.message.reply_text(
            "Напишите название модели или отправьте фото.\n"
            "Если удобнее — откройте каталог и выберите модель.",
            reply_markup=kb_catalog()
        )
        return

    if data == "catalog":
        set_state(context, STATE_NONE)
        await q.message.reply_text("Каталог:", reply_markup=kb_catalog())
        return

    if data == "delivery":
        set_state(context, STATE_NONE)
        await q.message.reply_text(
            "Доставка:\n"
            "• По городу: 1–2 дня\n"
            "• По Казахстану: 2–5 дней\n"
            "Точные условия уточнит менеджер после заявки.",
            reply_markup=kb_main()
        )
        return

    if data == "manager":
        set_state(context, STATE_NONE)
        await q.message.reply_text(
            "Могу подключить менеджера.\n"
            "Оформите заявку: выберите модель → город → телефон.",
            reply_markup=kb_main()
        )
        return

    if data == "order":
        # заказ без модели — попросим выбрать
        set_state(context, STATE_WAIT_MODEL)
        await q.message.reply_text(
            "Чтобы оформить заказ, сначала выберите модель из каталога или отправьте фото:",
            reply_markup=kb_catalog()
        )
        return

    if data.startswith("item:"):
        model_key = data.split(":", 1)[1]
        item = CATALOG.get(model_key)
        if not item:
            await q.message.reply_text("Модель не найдена.", reply_markup=kb_main())
            return

        context.user_data["selected_model"] = model_key
        set_state(context, STATE_NONE)

        await q.message.reply_text(
            f"Модель: {item['name']} 👜\n"
            f"Цена: {item['price']} ₸\n"
            f"Цвета: {', '.join(item['colors'])}\n"
            f"Описание: {item['desc']}\n\n"
            "Оформляем заказ?",
            reply_markup=kb_item(model_key)
        )
        return

    if data.startswith("order:"):
        model_key = data.split(":", 1)[1]
        if model_key not in CATALOG:
            await q.message.reply_text("Модель не найдена.", reply_markup=kb_main())
            return
        context.user_data["selected_model"] = model_key
        set_state(context, STATE_WAIT_CITY)
        await q.message.reply_text("Отлично! Напишите ваш город:")
        return

    # DEMO buttons
    if data == "demo_cancel":
        set_state(context, STATE_NONE)
        context.user_data.pop("demo_model_key", None)
        await q.message.reply_text("Ок, закрыл демо-режим.", reply_markup=kb_main())
        return

    if data.startswith("demo_set:"):
        if not is_admin(update.effective_user.id):
            await q.message.reply_text("Доступно только администратору.")
            return
        model_key = data.split(":", 1)[1]
        if model_key not in CATALOG:
            await q.message.reply_text("Не нашёл модель.")
            return

        context.user_data["demo_model_key"] = model_key
        set_state(context, STATE_DEMO_WAIT_PHOTO)

        await q.message.reply_text(
            f"Теперь отправьте фото модели {CATALOG[model_key]['name']} 📸\n"
            "Я привяжу фото к этой модели."
        )
        return

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    file_id = update.message.photo[-1].file_id

    # 1) DEMO привязка (только админ)
    if get_state(context) == STATE_DEMO_WAIT_PHOTO and is_admin(user_id):
        model_key = context.user_data.get("demo_model_key")
        if model_key and model_key in CATALOG:
            PHOTO_MODEL_MAP[file_id] = model_key
            save_demo_map()

            set_state(context, STATE_NONE)
            context.user_data.pop("demo_model_key", None)

            await update.message.reply_text(
                f"Готово ✅ Фото привязано к модели: {CATALOG[model_key]['name']}\n"
                f"Всего привязок: {len(PHOTO_MODEL_MAP)}",
                reply_markup=kb_main()
            )
            return

    # 2) Распознавание (демо по file_id)
    mapped_key = PHOTO_MODEL_MAP.get(file_id)
    if mapped_key and mapped_key in CATALOG:
        item = CATALOG[mapped_key]
        context.user_data["selected_model"] = mapped_key

        await update.message.reply_text(
            f"Это модель {item['name']} 👜\n"
            f"Цена: {item['price']} ₸\n"
            f"В наличии цвета: {', '.join(item['colors'])}\n\n"
            "Оформляем заказ?",
            reply_markup=kb_item(mapped_key)
        )
        return

    # 3) Неизвестное фото — ведём в каталог (без “похоже”)
    set_state(context, STATE_WAIT_MODEL)
    await update.message.reply_text(
        "Эта модель есть в нашем каталоге.\n"
        "Чтобы назвать точную цену, выберите модель из списка ниже или напишите название:",
        reply_markup=kb_catalog()
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return

    st = get_state(context)

    # Состояние: ждём город
    if st == STATE_WAIT_CITY:
        city = text.strip()
        if len(city) < 2:
            await update.message.reply_text("Напишите город текстом (например: Алматы):")
            return
        context.user_data["order_city"] = city
        set_state(context, STATE_WAIT_PHONE)
        await update.message.reply_text("Теперь отправьте номер телефона (пример: +7 777 123 45 67):")
        return

    # Состояние: ждём телефон
    if st == STATE_WAIT_PHONE:
        phone = normalize_phone(text)
        d = digits_only(phone)
        if len(d) < 10:
            await update.message.reply_text("Номер выглядит коротким. Отправьте ещё раз (пример: +7 777 123 45 67):")
            return

        model_key = context.user_data.get("selected_model")
        city = context.user_data.get("order_city", "—")
        item = CATALOG.get(model_key)

        if not item:
            # если вдруг модель не выбрана — вернём к каталогу
            set_state(context, STATE_WAIT_MODEL)
            await update.message.reply_text(
                "Почти готово. Сначала выберите модель из каталога:",
                reply_markup=kb_catalog()
            )
            return

        # фиксируем заявку
        order = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": update.effective_user.id,
            "name": update.effective_user.full_name,
            "username": update.effective_user.username or "",
            "city": city,
            "phone": phone,
            "model_key": model_key,
            "model_name": item["name"],
            "price": item["price"],
        }

        set_state(context, STATE_NONE)
        context.user_data.pop("order_city", None)

        await update.message.reply_text(
            "Заявка принята ✅\n"
            "Менеджер скоро свяжется с вами.\n\n"
            "Хотите посмотреть другие модели?",
            reply_markup=kb_main()
        )

        # админу
        if ADMIN_ID:
            admin_text = (
                "НОВАЯ ЗАЯВКА\n"
                f"Время: {order['ts']}\n"
                f"Клиент: {order['name']} (@{order['username']})\n"
                f"Город: {order['city']}\n"
                f"Телефон: {order['phone']}\n"
                f"Товар: {order['model_name']} — {order['price']} ₸\n"
                f"UserID: {order['user_id']}"
            )
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text)
            except Exception as e:
                logger.warning("Admin notify failed: %s", e)
        return

    # Состояние: ждём модель (по тексту)
    if st == STATE_WAIT_MODEL:
        key = find_model_from_text(text)
        if key and key in CATALOG:
            item = CATALOG[key]
            context.user_data["selected_model"] = key
            set_state(context, STATE_NONE)

            await update.message.reply_text(
                f"Модель: {item['name']} 👜\n"
                f"Цена: {item['price']} ₸\n"
                f"Цвета: {', '.join(item['colors'])}\n\n"
                "Оформляем заказ?",
                reply_markup=kb_item(key)
            )
            return

        # если не нашли модель — подключаем ИИ (внутри ИИ тоже будет “выбери из каталога”)
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        ai_reply = await ask_ai(text)
        await update.message.reply_text(ai_reply, reply_markup=kb_main())
        return

    # Обычный режим: любой текст -> ИИ (или фолбэк)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    ai_reply = await ask_ai(text)
    await update.message.reply_text(ai_reply, reply_markup=kb_main())

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled error", exc_info=context.error)

async def post_init(app):
    # убираем webhook, чтобы не было Conflict
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted (drop_pending_updates=True)")
    except Exception as e:
        logger.warning("delete_webhook failed: %s", e)

# -------------------- MAIN --------------------
def main():
    load_demo_map()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("demo", cmd_demo))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.add_error_handler(error_handler)

    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
