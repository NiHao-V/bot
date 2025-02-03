import telebot
your_user_id = "462094943"
token = "5559613669:AAFJhz-O4vlGO2z-WaoVZVPUexdGkpwEd54"
bot = telebot.TeleBot(token)

def send_to_user(user_id, text):
    try:
        bot.send_message(user_id, text)

    except Exception as e:
        print("Ошибка при отправке сообщения:", e)

