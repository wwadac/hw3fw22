import sqlite3
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

# Настройки
BOT_TOKEN = "8534057742:AAFfm2gswdz-b6STcrWcCdRfaToRDkPUu0A"
ADMIN_ID = 6893832048  # Замените на ваш ID в Telegram

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
logging.basicConfig(level=logging.INFO)

# Инициализация БД
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS records
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      username TEXT,
                      text TEXT,
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

# Состояние для команды /a
class AddRecord(StatesGroup):
    waiting_for_text = State()

# Команда /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.answer("Привет! Отправь /a чтобы добавить запись.")

# Команда /a
@dp.message_handler(commands=['a'])
async def cmd_a(message: types.Message):
    await AddRecord.waiting_for_text.set()
    await message.answer("Введите текст для сохранения в базу данных:")

# Обработчик текста для /a
@dp.message_handler(state=AddRecord.waiting_for_text)
async def process_text(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or "Без имени"
    text = message.text

    # Сохранение в БД
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO records (user_id, username, text) VALUES (?, ?, ?)",
                   (user_id, username, text))
    record_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Формируем сообщение админу
    admin_message = (
        f"📥 Новая запись в БД (ID: {record_id}):\n"
        f"👤 Пользователь: @{username} (ID: {user_id})\n"
        f"📝 Текст: {text}\n"
        f"🕐 Время: {message.date}"
    )

    # Отправляем админу
    try:
        await bot.send_message(ADMIN_ID, admin_message)
        await message.answer(f"✅ Данные сохранены и отправлены админу!")
    except Exception as e:
        await message.answer(f"✅ Данные сохранены, но админ не получил уведомление: {e}")

    await state.finish()

# Команда /getdb для админа (получение файла БД)
@dp.message_handler(commands=['getdb'], user_id=ADMIN_ID)
async def cmd_getdb(message: types.Message):
    try:
        with open('database.db', 'rb') as db_file:
            await message.answer_document(db_file, caption="📦 Файл базы данных")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

# Запуск бота
if __name__ == '__main__':
    init_db()
    print("Бот запущен...")
    executor.start_polling(dp, skip_updates=True)
