import os
from openai import OpenAI
from catalog import CATALOG

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
Ты — AI-менеджер магазина сумок.
Твоя задача — помочь выбрать модель, назвать цену из каталога и довести до оформления заказа.

Правила:
- Никогда не придумывай цену или наличие.
- Используй только данные из каталога.
- Пиши коротко и уверенно.
- Всегда предлагай следующий шаг.
"""

def build_catalog_context():
    context = ""
    for key, item in CATALOG.items():
        context += f"{item['name']} — {item['price']} ₸. {item['desc']}\n"
    return context

def ask_ai(user_message):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + "\n\nКаталог:\n" + build_catalog_context()},
            {"role": "user", "content": user_message}
        ],
        temperature=0.4,
    )

    return response.choices[0].message.content.strip()
