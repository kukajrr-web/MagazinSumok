import os
import re
import logging
from datetime import datetime
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ----------------- Настройки -----------------
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")  # твой Telegram user_id

if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set")

# ----------------- Логи -----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("bags-demo-bot")

# ----------------- Демо-каталог -----------------
CATALOG = {
    "luna_mini": {
        "name": "Luna Mini",
        "price": 32900,
        "colors": ["чёрный", "бежевый"],
        "desc": "Компактная сумка на каждый день. Фурнитура премиум.",
    },
    "aura": {
        "name": "AURA",
        "price": 45900,
        "colors": ["чёрный", "молочный"],
        "desc": "Новая коллекция. Строгая форма, мягкая кожа.",
    },
    "vera": {
        "name": "Vera",
        "price": 38900,
        "colors": ["шоколад", "чёрный"],
        "desc": "Вместительная модель, отлично под офис и поездки.",
    },
    "iris": {
        "name": "Iris",
        "price": 29900,
        "colors": ["серый", "чёрный"],
        "desc": "Лёгкая базовая сумка. Хороший вариант на подарок.",
    },
    "nova": {
        "name": "Nova",
        "price": 51900,
        "colors": ["чёрный"],
        "desc": "Премиум-линейка. Максимум деталей и качества.",
    },
}

# ----------------- Демо-заявки -----------------
ORDERS = []

# ----------------- Состояния -----------------
WAIT_MODEL_OR_PHOTO, WAIT_CITY, WAIT_PHONE = range(3)


# ----------------- UI -----------------
def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👜 Узнать цену", callback_data="price")],
        [InlineKeyboardButton("📦 Каталог", callback_data="catalog")],
        [InlineKeyboardButton("🚚 Доставка", callback_data="delivery")],
        [InlineKeyboardButton("👩‍💼 Менеджер", callback_data="manager")],
    ])


def catalog_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, item in CATALOG.items():
        rows.append([InlineKeyboardButton(f"{item['name']} — {item['price']} ₸", callback_data=f"item:{key}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(rows)


def item_keyboard(item_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Оформить заказ", callback_data=f"order:{item_key}")],
        [InlineKeyboardButton("📦 Каталог", callback_data="catalog")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")],
    ])


# ----------------- Helpers -----------------
def normalize_phone(s: str) -> str:
    s = s.strip()
    s = re.sub(r"[^\d+]", "", s)  # оставим + и цифры
    return s


def find_item_by_text(text: str):
    t = (text or "").strip().lower()
    # точное вхождение названия
    for key, item in CATALOG.items():
        if item["name"].lower() in t:
            return key
    # частичное совпадение по словам
    words = [w for w in re.split(r"\s+", t) if w]
    for key, item in CATALOG.items():
        name = item["name"].lower()
        if any(w in name for w in words):
            return key
    return None


def is_admin(user_id: int) -> bool:
    return ADMIN_ID and user_id == ADMIN_ID


# ----------------- Handlers -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Здравствуйте! Я виртуальный менеджер магазина сумок 👜\n\n"
        "Могу:\n"
        "• подсказать цену и наличие\n"
        "• помочь выбрать модель\n"
        "• оформить заявку менеджеру\n\n"
        "Выберите действие:"
    )
    await update.message.reply_text(text, reply_markup=main_menu())


async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "back":
        await q.message.reply_text("Главное меню:", reply_markup=main_menu())
        return ConversationHandler.END

    if data == "catalog":
        await q.message.reply_text("Выберите модель:", reply_markup=catalog_keyboard())
        return ConversationHandler.END

    if data == "delivery":
        await q.message.reply_text(
            "🚚 Доставка:\n"
            "• По городу: 1–2 дня\n"
            "• По Казахстану: 2–5 дней\n"
            "• Условия уточнит менеджер после заявки.\n\n"
            "Хотите узнать цену или оформить заказ?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👜 Узнать цену", callback_data="price")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="back")],
            ])
        )
        return ConversationHandler.END

    if data == "manager":
        await q.message.reply_text(
            "👩‍💼 Менеджер подключится после заявки.\n"
            "Нажмите «Узнать цену» → выберите модель → «Оформить заказ».",
            reply_markup=main_menu()
        )
        return ConversationHandler.END

    # показать товар
    if data.startswith("item:"):
        key = data.split(":", 1)[1]
        item = CATALOG.get(key)
        if not item:
            await q.message.reply_text("Не нашёл модель в каталоге.", reply_markup=main_menu())
            return ConversationHandler.END

        text = (
            f"👜 {item['name']}\n"
            f"💰 Цена: {item['price']} ₸\n"
            f"🎨 Цвета: {', '.join(item['colors'])}\n"
            f"📝 Описание: {item['desc']}\n\n"
            "Оформляем заказ?"
        )
        await q.message.reply_text(text, reply_markup=item_keyboard(key))
        return ConversationHandler.END

    # начать оформление
    if data.startswith("order:"):
        key = data.split(":", 1)[1]
        item = CATALOG.get(key)
        if not item:
            await q.message.reply_text("Не нашёл модель в каталоге.", reply_markup=main_menu())
            return ConversationHandler.END

        context.user_data["order_item_key"] = key
        await q.message.reply_text("Отлично! Напишите, пожалуйста, ваш город:")
        return WAIT_CITY

    return ConversationHandler.END


# ---- Диалог "Узнать цену" ----
async def entry_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    await q.message.reply_text(
        "Напишите название модели (например: Luna Mini) или выберите в «Каталоге».\n"
        "Можно прислать фото — в демо я предложу выбрать модель из списка.",
        reply_markup=catalog_keyboard()
    )
    return WAIT_MODEL_OR_PHOTO


async def on_model_or_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        await update.message.reply_text(
            "Спасибо за фото! Чтобы назвать точную цену, выберите модель из каталога 👇",
            reply_markup=catalog_keyboard()
        )
        return ConversationHandler.END

    text = update.message.text or ""
    key = find_item_by_text(text)
    if not key:
        await update.message.reply_text(
            "Не понял модель 😅\nВыберите из каталога или напишите название точнее:",
            reply_markup=catalog_keyboard()
        )
        return WAIT_MODEL_OR_PHOTO

    item = CATALOG[key]
    msg = (
        f"Похоже на модель: {item['name']} ✅\n"
        f"Цена: {item['price']} ₸\n"
        f"В наличии цвета: {', '.join(item['colors'])}\n\n"
        "Оформляем заказ?"
    )
    await update.message.reply_text(msg, reply_markup=item_keyboard(key))
    return ConversationHandler.END


# ---- Оформление ----
async def on_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = (update.message.text or "").strip()
    if len(city) < 2:
        await update.message.reply_text("Напишите город текстом (например: Алматы):")
        return WAIT_CITY

    context.user_data["order_city"] = city
    await update.message.reply_text("Теперь отправьте номер телефона (пример: +7 777 123 45 67):")
    return WAIT_PHONE


async def on_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_raw = update.message.text or ""
    phone = normalize_phone(phone_raw)
    digits = re.sub(r"\D", "", phone)

    if len(digits) < 10:
        await update.message.reply_text("Похоже, номер короткий. Отправьте ещё раз (пример: +7 777 123 45 67):")
        return WAIT_PHONE

    item_key = context.user_data.get("order_item_key")
    city = context.user_data.get("order_city", "—")
    item = CATALOG.get(item_key, {"name": "—", "price": 0})

    user = update.effective_user

    order = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": user.id,
        "username": user.username or "",
        "name": user.full_name or "",
        "city": city,
        "phone": phone,
        "item_key": item_key,
        "item_name": item.get("name"),
        "price": item.get("price"),
    }
    ORDERS.append(order)

    await update.message.reply_text(
        "✅ Заявка принята!\nМенеджер скоро свяжется с вами.\n\nХотите узнать цену другой модели?",
        reply_markup=main_menu()
    )

    # Уведомление админу
    if ADMIN_ID:
        admin_text = (
            "🆕 НОВАЯ ЗАЯВКА\n"
            f"Время: {order['ts']}\n"
            f"Клиент: {order['name']} (@{order['username']})\n"
            f"Город: {order['city']}\n"
            f"Телефон: {order['phone']}\n"
            f"Товар: {order['item_name']} — {order['price']} ₸\n"
            f"UserID: {order['user_id']}"
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text)
        except Exception as e:
            logger.warning("Failed to notify admin: %s", e)

    context.user_data.pop("order_item_key", None)
    context.user_data.pop("order_city", None)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ок, отменил. Главное меню:", reply_markup=main_menu())
    return ConversationHandler.END


# ---- Админ команды (демо) ----
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "🛠 Админ-панель (демо)\n\n"
        "/orders — последние заявки\n"
        "/reset — очистить заявки\n"
    )


async def orders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ORDERS:
        await update.message.reply_text("Заявок пока нет.")
        return

    last = ORDERS[-10:]
    lines = ["📌 Последние заявки:"]
    for o in last:
        lines.append(f"- {o['ts']} | {o['item_name']} | {o['city']} | {o['phone']} | {o['name']}")
    await update.message.reply_text("\n".join(lines))


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    ORDERS.clear()
    await update.message.reply_text("Ок, заявки очищены (демо).")


# ---- Error handler ----
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled error", exc_info=context.error)


# ---- Startup: убираем webhook, чтобы НЕ было Conflict ----
async def post_init(app: Application):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted (drop_pending_updates=True)")
    except Exception as e:
        logger.warning("delete_webhook failed: %s", e)


# ----------------- Запуск -----------------
def build_app() -> Application:
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    # Conversation "price" must be above general callback handler
    price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(entry_price, pattern="^price$")],
        states={
            WAIT_MODEL_OR_PHOTO: [
                MessageHandler(filters.TEXT | filters.PHOTO, on_model_or_photo),
                CallbackQueryHandler(on_menu_click, pattern="^(catalog|back|item:.*|order:.*|delivery|manager)$"),
            ],
            WAIT_CITY: [MessageHandler(filters.TEXT, on_city)],
            WAIT_PHONE: [MessageHandler(filters.TEXT, on_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        per_message=True,  # чтобы не было предупреждения про per_message
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))

    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("orders", orders_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))

    app.add_handler(price_conv)
    app.add_handler(CallbackQueryHandler(on_menu_click))  # остальной клик-меню

    app.add_error_handler(error_handler)
    return app


if __name__ == "__main__":
    application = build_app()
    application.run_polling(drop_pending_updates=True)
