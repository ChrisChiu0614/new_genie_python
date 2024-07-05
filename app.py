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

app = Flask(__name__)

# Line API 初始化
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
news_api_key = os.getenv('NEWS_API_KEY')
openai.api_key = os.getenv('OPENAI_API_KEY')

#Attribute
def get_dates():
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(1)).strftime('%Y-%m-%d')
    return yesterday, today

def fetch_news():
    try:
        yesterday, today = get_dates()
        app.logger.info(f"Fetching news from {yesterday} to {today}")
        url = f'https://newsapi.org/v2/top-headlines?sources=bbc-news&country=us&category=business&from={yesterday}&to={today}&sortBy=popularity&apiKey={news_api_key}'
        response = requests.get(url)
        response.raise_for_status()  # 如果請求返回錯誤狀態碼，則引發 HTTPError
        news_data = response.json()
        articles = news_data['articles'][:5]
        news_list = [{'title': article['title'], 'url': article['url'], 'content': article['description']} for article in articles]
        return news_list
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching news: {e}")
        return []

def summarize_news(articles):
    summaries = []
    for idx, article in enumerate(articles):
        #prompt = f"Summarize the following news article:\n\n{article['content']}"
        prompt = f"Summarize the following news article in 100 to 150 words, focusing on the main points:\n\n{article['content']}"
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=150
        )
        summary = response.choices[0].text.strip()
        summaries.append(f"{idx + 1}. {article['title']}\n{summary}")
    return '\n\n'.join(summaries)

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
    if msg == 'now':
        news = fetch_news()
        summaries = summarize_news(news)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=summaries))
    elif msg == 'summary':
        news = fetch_news()
        summaries = summarize_news(news)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=summaries))
    else:
        reply = f"你說了: {msg}"
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
    message = TextSendMessage(text=f'{name} 歡迎加入')
    line_bot_api.reply_message(event.reply_token, message)
    
def schedule_news_updates():
    # 設置調度時間為UTC 15:04 (台灣時間的23:04) 和 00:00 (台灣時間的08:00)
    schedule.every().day.at("00:00").do(send_daily_news)
    app.logger.info("Scheduler started")
    
    while True:
        schedule.run_pending()
        time.sleep(1)

# 啟動調度器
schedule_thread = Thread(target=schedule_news_updates)
schedule_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
