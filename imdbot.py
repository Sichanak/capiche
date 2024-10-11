from uuid import uuid4
from datetime import datetime, timedelta
from telegram import InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, InlineQueryHandler, CallbackQueryHandler, ChosenInlineResultHandler, MessageHandler, filters
import asyncio
import movie
import os
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv('TOKEN')

# Global vars
DATABASE = os.path.join(os.path.dirname(__file__), 'database', 'imdbot_db.sqlite3')
JOB_TIME = (9, 30)  # time at which notifications are sent (UTC)



def notify_users(context):
    """
    Notify users upon title release
    """
    alert = movie.Alert(DATABASE)
    results = alert.notify()
    for result in results:
        user_id, message = result[0], result[1]
        context.bot.send_message(chat_id=user_id, text=message, parse_mode=ParseMode.HTML)

def result_id(title_id):
    """
    Generate UUID containing IMDb title ID
    """
    uuid4_str = str(uuid4())
    my_uuid = uuid4_str + '-' + str(title_id)
    return my_uuid

async def help_cmd(update, context):
    """
    Reply with help message when the command /help is issued.
    """
    bot_name = (await context.bot.get_me()).username
    await update.message.reply_text(text='Search for a title by typing @{0} "movie name", pick a result from the list and set an alert to receive a notification when the movie or series episode is out!\n\nType /alerts to view your active alerts.'.format(bot_name))

async def alerts_cmd(update, context):
    """
    Reply with list of enabled alerts when the command /alerts is issued
    """
    user_id = update.message.from_user.id
    alert = movie.Alert(DATABASE)
    message = alert.title_name(user_id)
    await update.message.reply_html(message)

async def unknown_cmd(update, context):
    """
    Unsupported command message handler
    """
    chatid = update.effective_chat.id
    is_bot = update.effective_user.is_bot
    if not is_bot:
        await context.bot.send_message(chat_id=chatid, text='Unrecognized command, type /help or /alerts')

async def chosen_result(update, context):
    """
    Get chosen inline result
    """
    result = update.chosen_inline_result
    resultid = result.result_id
    title_id = resultid.split('-')[-1]
    user_id = result.from_user.id
    context.user_data[user_id] = title_id

def imdb_url_button(title_id, message):
    """
    After choosing enable/disable alert create IMDb URL button
    """
    imdb_url = 'https://www.imdb.com/title/tt' + str(title_id)
    message = str(message) + ' (IMDb link)'
    keyboard = [[InlineKeyboardButton(text=str(message), url=imdb_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    return reply_markup

async def enable_alert(update, context):
    """
    Enable Alert for chosen inline result.
    """
    query = update.callback_query
    query.answer(text='Searching release date...')
    user = ['id', 'first_name', 'last_name', 'username']
    user_info = [query.from_user[i] for i in user if query.from_user[i]]
    user_name = ' '.join(user_info[1:])
    title_id = context.user_data[user_info[0]]
    alert = movie.Alert(DATABASE)
    result = alert.enable(user_info[0], user_name, title_id)
    query.edit_message_reply_markup(reply_markup=None)
    new_reply_markup = imdb_url_button(title_id, result)
    query.edit_message_reply_markup(reply_markup=new_reply_markup)

async def disable_alert(update, context):
    """
    Disable alert for chosen inline result.
    """
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    title_id = context.user_data[user_id]
    alert = movie.Alert(DATABASE)
    result = alert.disable(user_id, title_id)
    query.edit_message_reply_markup(reply_markup=None)
    new_reply_markup = imdb_url_button(title_id, result)
    query.edit_message_reply_markup(reply_markup=new_reply_markup)

async def dismiss(update, context):
    """
    Dismiss chosen inline result
    """
    query = update.callback_query
    query.answer()
    query.edit_message_reply_markup(reply_markup=None)

def create_reply_markup(title, current_year, user_titles):
    """
    Create reply markup for result based on title and user alerts
    """
    keyboard = [[InlineKeyboardButton("Enable alert", callback_data=str(enable_alert)),
                 InlineKeyboardButton("Disable alert", callback_data=str(disable_alert )),
                 InlineKeyboardButton("Dismiss", callback_data=str(dismiss))]]
    if 'series' in title['kind']:
        if title['end_year']:
            message = 'Series ended in {0}'.format(title['end_year'])
            reply_markup = imdb_url_button(title['id'], message)
            return reply_markup
    elif title['year']:
        if current_year > title['year']:
            message = 'Movie released in {0}'.format(title['year'])
            reply_markup = imdb_url_button(title['id'], message)
            return reply_markup
    if str(title['id']) in user_titles:
        del keyboard[0][0]
    else:
        del keyboard[0][1]
    reply_markup = InlineKeyboardMarkup(keyboard)
    return reply_markup

async def in_line_query(update, context):
    """
    Handle the inline query.
    """
    query = update.inline_query.query
    is_bot = update.inline_query.from_user.is_bot
    if not is_bot:
        current_year = int(datetime.now().strftime('%Y'))
        user_id = update.inline_query.from_user.id
        user_titles = movie.Alert(DATABASE).title_id(user_id)
        titles = movie.search(query)
        results = []
        for title in titles:
            reply_markup = create_reply_markup(title, current_year, user_titles)
            result = InlineQueryResultArticle(id=result_id(title['id']),
                                              title=title['long imdb title'],
                                              input_message_content=InputTextMessageContent(message_text=movie.reply_message(title), parse_mode=ParseMode.HTML),
                                              description=title['plot'],
                                              thumb_url=title['cover url'],
                                              reply_markup=reply_markup)
            results.append(result)
        await update.inline_query.answer(results, cache_time=4)

if __name__ == '__main__':
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", help_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("alerts", alerts_cmd))
    application.add_handler(InlineQueryHandler(in_line_query))
    application.add_handler(ChosenInlineResultHandler(chosen_result))
    application.add_handler(CallbackQueryHandler(enable_alert, pattern='^enable_alert$'))
    application.add_handler(CallbackQueryHandler(disable_alert, pattern='^disable_alert$'))
    application.add_handler(CallbackQueryHandler(dismiss, pattern='^dismiss$'))
    application.add_handler(MessageHandler((~ filters.Entity('url')) & (~ filters.Entity('text_link')), unknown_cmd))

    application.run_polling()