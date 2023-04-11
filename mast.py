import pymysql.cursors
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram import Bot, Dispatcher, executor, types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ContentType
from aiogram.utils.markdown import hbold, hitalic, hcode

from config import BOT_TOKEN, HOST, PORT, USER, PASSWORD, DB_NAME, DEFAULT_PARSE_MODE, SUPPORT_USERNAME, ADMIN_ID, \
    RULES, CATEGORIES, PAYMENTS

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())


def connect(db_name=None):
    try:
        connection_ = pymysql.connect(
            host=HOST,
            port=PORT,
            user=USER,
            password=PASSWORD,
            database=db_name,
            cursorclass=pymysql.cursors.DictCursor
        )

        print("Connection Successful")
        return connection_
    except Exception as err:
        print("Connection was failed")
        print(err)


connection = connect(DB_NAME)
cursor = connection.cursor()

main_keyboard = ReplyKeyboardMarkup(row_width=2, keyboard=[
    [
        KeyboardButton("🏧 Загрузить логи"),
    ],
    [
        KeyboardButton("💻 Профиль"),
    ],
    [
        KeyboardButton("📜 Прайс"),
        KeyboardButton("📖 Правила")
    ],
    [
        KeyboardButton("💰 Актуальные запросы")
    ]
], resize_keyboard=True)


class States(StatesGroup):
    upload_file = State()
    withdraw_payment = State()
    withdraw_payment_contacts = State()


@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    if cursor.execute(f"SELECT * FROM `users` WHERE user_id={message.from_user.id}") == 0:
        cursor.execute(f"INSERT INTO `users`(user_id, username, balance, total_earnings) VALUES (%s, %s, %s, %s)",
                       (message.from_user.id, message.from_user.username, 0, 0))
        connection.commit()
    text = f"Добро пожаловать, {hbold(message.from_user.first_name)}!\n\n" \
           f"{hitalic('Это телеграм бот для автоматического принятия логов!')}\n\n" \
           f"{hbold('Создатель')}: @dkhodos"
    await message.reply(text=text, reply_markup=main_keyboard, parse_mode=DEFAULT_PARSE_MODE)


@dp.message_handler(commands=["init"])
async def init(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        if cursor.execute(f"SELECT * FROM `categories`") == 0:
            for category, price_ in CATEGORIES:
                cursor.execute(f"INSERT INTO `categories`(category, price) VALUES (%s, %s)",
                               (category, price_))
                connection.commit()
            await message.reply(text=hbold("Проект инициализирован!"), parse_mode=DEFAULT_PARSE_MODE)
        else:
            await message.reply(f"{hbold('Проект уже инициализирован!')}", parse_mode=DEFAULT_PARSE_MODE)
    else:
        await message.reply(f"{hbold('Данная команда вам недоступна!')}", parse_mode=DEFAULT_PARSE_MODE)


@dp.callback_query_handler(text_startswith="category_")
async def send_logs(callback_data: types.CallbackQuery):
    _, category = callback_data.data.split("_")
    await callback_data.message.edit_text(text=hbold("Отправьте мне архив с логами:"),
                                          parse_mode=DEFAULT_PARSE_MODE)
    state = Dispatcher.get_current().current_state()
    await state.update_data(category=category)
    await States.upload_file.set()


@dp.message_handler(state=States.upload_file, content_types=[ContentType.DOCUMENT])
async def upload_logs_state(message: types.Message, state: FSMContext):
    await state.update_data(file_id=message.document["file_id"])
    data = await state.get_data()
    category = data["category"]
    file_id = data["file_id"]
    cursor.execute(f"INSERT INTO `logs`(sender_id, log, is_checked, category) VALUES (%s, %s, %s, %s)",
                   (message.from_user.id, file_id, False, category))
    connection.commit()
    cursor.execute(f"SELECT id FROM `logs` WHERE sender_id = {message.from_user.id} AND log = '{file_id}'")
    id_ = dict(cursor.fetchone())['id']
    admin_text = f"{hbold('Новый запрос на отработку')} {hcode('#' + str(id_))}\n\n" \
                 f"{hbold('ID:')} {hcode(message.from_user.id)}\n" \
                 f"{hbold('Username:')} {hcode(message.from_user.username)}\n" \
                 f"{hbold('Запрос:')} {hcode(category)}"
    admin_keyboard = InlineKeyboardMarkup(row_width=2, inline_keyboard=[
        [
            InlineKeyboardButton(text="✔️ Начислить",
                                 callback_data=f"admin_answer_allow_{message.from_user.id}_{id_}_{category}"),
            InlineKeyboardButton(text="❌ Пусто",
                                 callback_data=f"admin_answer_empty_{message.from_user.id}_{id_}_{category}")
        ]
    ])
    await message.reply(text=hbold(f"Ваш файл успешно зарегестрирован под номером #{id_}!"),
                        parse_mode=DEFAULT_PARSE_MODE)

    await bot.send_document(chat_id=ADMIN_ID, document=file_id, caption=admin_text, parse_mode=DEFAULT_PARSE_MODE,
                            reply_markup=admin_keyboard)
    await state.finish()


@dp.callback_query_handler(text_startswith="admin_answer_")
async def admin_answer(callback_data: types.CallbackQuery):
    _, _, answer, user_id, log_id, category = callback_data.data.split("_")

    if answer == "allow":
        cursor.execute(
            f"UPDATE `logs` SET is_checked=True WHERE sender_id={user_id} AND id={log_id}")
        connection.commit()
        cursor.execute(f"SELECT price FROM `categories` WHERE category = '{category}'")
        price_ = dict(cursor.fetchone())['price']
        cursor.execute(f"SELECT balance FROM `users` WHERE user_id = {user_id}")
        user_balance = dict(cursor.fetchone())['balance']
        cursor.execute(f"SELECT total_earnings FROM `users` WHERE user_id = {user_id}")
        user_total_earnings = dict(cursor.fetchone())['total_earnings']

        cursor.execute(
            f"UPDATE `users` SET balance={user_balance + price_} WHERE user_id={user_id}")
        connection.commit()
        cursor.execute(
            f"UPDATE `users` SET total_earnings={user_total_earnings + price_} WHERE user_id={user_id}")
        connection.commit()
        await bot.send_message(chat_id=user_id,
                               text=hbold(f"Ваш лог #{log_id} прошёл валид!\n\nВам начислено: {price_} руб."),
                               parse_mode=DEFAULT_PARSE_MODE)
        await callback_data.message.delete_reply_markup()
    else:
        cursor.execute(
            f"UPDATE `logs` SET is_checked=True WHERE sender_id={user_id} AND id={log_id}")
        connection.commit()
        await bot.send_message(chat_id=user_id, text=hbold(f"В базе #{log_id} не нашли валида!"),
                               parse_mode=DEFAULT_PARSE_MODE)
        await callback_data.message.delete_reply_markup()


@dp.message_handler(text="🏧 Загрузить логи")
async def upload_logs(message: types.Message):
    keyboard = InlineKeyboardMarkup(row_width=1, inline_keyboard=[
        [InlineKeyboardButton(text=category, callback_data=f"category_{category}")] for category, _ in CATEGORIES
    ])
    keyboard.add(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    await message.reply(text=hbold("Выберите запрос: "), reply_markup=keyboard, parse_mode=DEFAULT_PARSE_MODE)


@dp.callback_query_handler(text="cancel")
async def cancel(callback_data: types.CallbackQuery):
    await callback_data.message.edit_text(text=hbold("❌ Действие отменено!"), parse_mode=DEFAULT_PARSE_MODE)


@dp.message_handler(text="💻 Профиль")
async def profile(message: types.Message):
    cursor.execute(f"SELECT balance FROM `users` WHERE user_id={message.from_user.id}")
    balance = dict(cursor.fetchone())["balance"]
    cursor.execute(f"SELECT total_earnings FROM `users` WHERE user_id={message.from_user.id}")
    total_earnings = dict(cursor.fetchone())["total_earnings"]
    text = f"📔 {hbold('Личный кабинет')}\n\n" \
           f"💎 {hbold('Уникальный ID: ')}{hcode(message.from_user.id)}\n" \
           f"👤 {hbold('Никнейм: ')} {hcode(message.from_user.username)}\n" \
           f"💸 {hbold('Баланс: ')}{hcode(balance)} руб.\n\n" \
           f"💲 {hbold('Вы заработали с нами: ')}{hcode(total_earnings)} руб."

    keyboard = InlineKeyboardMarkup(row_width=1, inline_keyboard=[
        [InlineKeyboardButton("💸 Вывести", callback_data="withdraw")],
        [InlineKeyboardButton("⌚ Непроверенные логи", callback_data="uncheked_logs")],
        [InlineKeyboardButton("📞 Поддержка", url=f"t.me/{SUPPORT_USERNAME[1::]}")]
    ])

    await message.reply(text, reply_markup=keyboard, parse_mode=DEFAULT_PARSE_MODE)


@dp.callback_query_handler(text="withdraw")
async def withdraw(callback_data: types.CallbackQuery):
    cursor.execute(f"SELECT balance FROM `users` WHERE user_id={callback_data.from_user.id}")
    user_balance = dict(cursor.fetchone())["balance"]
    if user_balance <= 0:
        await callback_data.message.reply(text=hbold("❌ Недостаточно средств!"), parse_mode=DEFAULT_PARSE_MODE)
    else:
        keyboard = InlineKeyboardMarkup(row_width=1, inline_keyboard=[
            [InlineKeyboardButton(text=payment, callback_data=f"payment_{payment}")] for payment in PAYMENTS
        ])
        keyboard.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel"))
        await callback_data.message.edit_text(text=hbold("Выберите куда выводить:"), reply_markup=keyboard,
                                              parse_mode=DEFAULT_PARSE_MODE)


@dp.callback_query_handler(text_startswith="payment_")
async def withdraw_payment(callback_data: types.CallbackQuery):
    _, payment = callback_data.data.split("_")

    if payment in PAYMENTS:
        await callback_data.message.edit_text(text=hbold("Напишите сумму вывода:"), parse_mode=DEFAULT_PARSE_MODE)
        state = Dispatcher.get_current().current_state()
        await state.update_data(payment_method=payment)
        await States.withdraw_payment.set()
    else:
        await callback_data.message.answer(text=hbold("❌ Произошла ошибка"), parse_mode=DEFAULT_PARSE_MODE)


@dp.message_handler(state=States.withdraw_payment)
async def withdraw_payment_state(message: types.Message, state: FSMContext):
    cursor.execute(f"SELECT balance from `users` WHERE user_id={message.from_user.id}")
    balance = dict(cursor.fetchone())["balance"]
    if int(message.text) > balance:
        await message.reply(text=hbold("❌ Недостаточно баланса!"), parse_mode=DEFAULT_PARSE_MODE)
    else:
        await state.update_data(payment_amount=message.text)
        await message.reply(text=hbold("Напишите данные для вывода: "), parse_mode=DEFAULT_PARSE_MODE)
        await States.withdraw_payment_contacts.set()


@dp.message_handler(state=States.withdraw_payment_contacts)
async def withdraw_payment_contacts(message: types.Message, state: FSMContext):
    await state.update_data(payment_contacts=message.text)
    data = await state.get_data()
    payment_method = data["payment_method"]
    payment_amount = data["payment_amount"]
    payment_contacts = data["payment_contacts"]

    text = f"{hbold('Новый запрос на вывод!')}\n\n" \
           f"{hbold('Способ оплаты:')} {hcode(payment_method)}\n" \
           f"{hbold('Сумма:')} {hcode(payment_amount)} руб.\n" \
           f"{hbold('Контакт:')} {hcode(payment_contacts)}\n" \
           f"{hbold('Username:')} {hcode('@' + message.from_user.username)} "
    keyboard = InlineKeyboardMarkup(row_width=2, inline_keyboard=[
        [
            InlineKeyboardButton(text="✔️Одобрить",
                                 callback_data=f"withdrawreq_accept_{payment_amount}_{message.from_user.id}"),
            InlineKeyboardButton(text="❌ Отклонить",
                                 callback_data=f"withdrawreq_decline_{payment_amount}_{message.from_user.id}"),
        ]
    ])
    await bot.send_message(chat_id=ADMIN_ID, text=text, reply_markup=keyboard, parse_mode=DEFAULT_PARSE_MODE)
    await state.finish()


@dp.callback_query_handler(text_startswith="withdrawreq_")
async def withdraw_admin(callback_data: types.CallbackQuery):
    _, answer, amount, user_id = callback_data.data.split("_")

    if answer == "accept":
        cursor.execute(f"SELECT balance from `users` WHERE user_id={user_id}")
        balance = dict(cursor.fetchone())["balance"]

        cursor.execute(f"UPDATE `users` SET balance={balance - int(amount)} WHERE user_id={user_id}")
        connection.commit()

        await bot.send_message(chat_id=user_id, text=hbold(f"Ваш запрос, на вывод {amount} руб., был выполнен!"),
                               parse_mode=DEFAULT_PARSE_MODE)
        await callback_data.message.delete_reply_markup()
    else:
        await bot.send_message(chat_id=user_id, text=hbold(f"Заявка на вывод была отклонена!\n\n"
                                                           f"Сумма: {amount} руб.\n"
                                                           f"Для уточнения деталей обращаться к {SUPPORT_USERNAME}"),
                               parse_mode=DEFAULT_PARSE_MODE
                               )
        await callback_data.message.delete_reply_markup()


@dp.callback_query_handler(text="uncheked_logs")
async def uncheked_logs(callback_data: types.CallbackQuery):
    cursor.execute(f"SELECT * FROM `logs` WHERE sender_id={callback_data.from_user.id} AND is_checked=False")
    logs = cursor.fetchall()
    if len(logs) <= 0:
        await callback_data.message.reply(
            text=hbold("❌ Вы еще не отправляли логи на проверку или все логи были проверены!"),
            parse_mode=DEFAULT_PARSE_MODE)
    else:
        text = f"⌚ {hbold('У вас')} {hcode(len(logs))} {hbold('непроверенных логов :(')}\n\n"
        output = []
        for log in logs:
            dict_log = dict(log)
            output.append(
                f"ID {hcode('#' + str(dict_log['id']))} {hbold('Непроверенный запрос')} -- {hcode(dict_log['category'])}")

        text = text + "\n".join(output)
        await callback_data.message.reply(text=text, parse_mode=DEFAULT_PARSE_MODE)


@dp.message_handler(text="📖 Правила")
async def rules(message: types.Message):
    await message.reply(f"{hbold('📖 Правила:')}\n\n{hbold(RULES)}", parse_mode=DEFAULT_PARSE_MODE)


@dp.message_handler(text="💰 Актуальные запросы")
async def shop_requests(message: types.Message):
    categories = [f"{category}\n" for category, _ in CATEGORIES]
    await message.reply(f"{hbold('🔎 Актуальные запросы которые мы скупаем:')}\n\n{hcode(''.join(categories))}",
                        parse_mode=DEFAULT_PARSE_MODE)


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
