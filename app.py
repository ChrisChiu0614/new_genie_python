from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
import requests
import os
from datetime import datetime, timedelta
import schedule
import time
from threading import Thread
import openai
import aiohttp
import asyncio

app = Flask(__name__)

# Line API 初始化
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
news_api_key = os.getenv('NEWS_API_KEY')
openai.api_key = os.getenv('OPENAI_API_KEY')

user_context = {}

# Attribute
def get_dates():
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(1)).strftime('%Y-%m-%d')
    return yesterday, today

def fetch_news():
    try:
        yesterday, today = get_dates()
        url = f'https://newsapi.org/v2/top-headlines?country=us&category=business&from={yesterday}&to={today}&apiKey={news_api_key}'
        response = requests.get(url)
        response.raise_for_status()  # 如果请求返回错误状态码，则引发 HTTPError
        news_data = response.json()
        if 'articles' not in news_data:
            app.logger.error(f"Unexpected response format: {news_data}")
            return []
        articles = news_data['articles'][:5]
        news_list = [{'title': article['title'], 'url': article['url'], 'content': article.get('description', 'No description available')} for article in articles]
        return news_list
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching news: {e}")
        return []

async def gpt_response(user_id, text):
    try:
        if user_id not in user_context:
            user_context[user_id] = [{"role": "system", "content": "You are a professional news summarization expert. Your task is to provide concise and accurate summaries of news articles. Ensure the summaries capture the key points and are easy to understand."}]
        
        user_context[user_id].append({"role": "user", "content": text})
        
        async with aiohttp.ClientSession() as session:
            headers = {
                'Authorization': f'Bearer {openai.api_key}',
                'Content-Type': 'application/json'
            }
            json_data = {
                "model": "gpt-3.5-turbo",
                "messages": user_context[user_id],
                "temperature": 0.7,
                "max_tokens": 300  # 减少最大token数量
            }
            async with session.post('https://api.openai.com/v1/chat/completions', headers=headers, json=json_data) as resp:
                response = await resp.json()
                if 'choices' not in response or len(response['choices']) == 0:
                    app.logger.error(f"Unexpected response format from GPT-3: {response}")
                    return "Error in GPT response."
                answer = response['choices'][0]['message']['content']
                user_context[user_id].append({"role": "assistant", "content": answer})
                return answer
    except Exception as e:
        app.logger.error(f"Error in GPT_response: {str(e)}")
        return "Error in GPT response."

def summarize_news(articles):
    summaries = []
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for idx, article in enumerate(articles):
        #prompt = f"Summarize the following news article:\n\n{article['content']}"
        prompt = f"Summarize the following news article in approximately 150 words. Make sure to include the main events, key figures, dates, locations, and any significant outcomes or implications. Provide enough detail to give a clear and comprehensive overview of the article:\n\n{article['content']}"
        summary = loop.run_until_complete(gpt_response("summary_user", prompt))
        summaries.append(f"{idx + 1}. {article['title']}\n{summary}")
    loop.close()
    return '\n\n'.join(summaries)

def format_news(articles):
    formatted_news = []
    for idx, article in enumerate(articles):
        formatted_news.append(f"{idx + 1}. {article['title']}\n{article['url']}")
    return '\n\n'.join(formatted_news)

def send_daily_news():
    news = fetch_news()
    if news:
        summaries = summarize_news(news)
        line_bot_api.broadcast(TextSendMessage(text=summaries))

@app.route("/", methods=['GET'])
def index():
    return "Hello, this is the Line bot application."

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@app.route("/time", methods=['GET'])
def get_server_time():
    server_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return f"Current server time: {server_time}"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text
    if msg.lower() == 'news':
        news = fetch_news()
        formatted_news = format_news(news)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=formatted_news))
    elif msg.lower() == 'summary':
        news = fetch_news()
        summaries = summarize_news(news)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=summaries))
    else:
        reply = (
        "Welcome to The News Genie. \n"
        "1. Every morning at 8 AM, you'll receive the latest 5 US business news articles.\n"
        "2. Type 'news' to manually fetch the latest 5 US business news articles.\n"
        "3. Type 'summary' to get a summary of these 5 news articles."
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

@handler.add(PostbackEvent)
def handle_postback(event):
    print(event.postback.data)

@handler.add(MemberJoinedEvent)
def welcome(event):
    uid = event.joined.members[0].user_id
    gid = event.source.group_id
    profile = line_bot_api.get_group_member_profile(gid, uid)
    name = profile.display_name
    message = TextSendMessage(text=f'{name} 欢迎加入')
    line_bot_api.reply_message(event.reply_token, message)

def schedule_news_updates():
    # 设置调度时间为UTC 15:04 (台湾时间的23:04) 和 00:00 (台湾时间的08:00)
    schedule.every().day.at("00:00").do(send_daily_news)
    app.logger.info("Scheduler started")

    while True:
        schedule.run_pending()
        time.sleep(1)

# 启动调度器
schedule_thread = Thread(target=schedule_news_updates)
schedule_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
