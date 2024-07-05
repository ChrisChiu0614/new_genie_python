from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
import os
import requests
import logging
from datetime import datetime, timedelta
import schedule
import time
from threading import Thread
import pytz


app = Flask(__name__)

# Line API 初始化
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
news_api_key = os.getenv('NEWS_API_KEY')

#Attribute
def get_dates():
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now()- timedelta(1)).strftime('%Y-%m-%d')
    return yesterday, today

def fetch_news():
    try:
        yesterday, today = get_dates()
        url = f'https://newsapi.org/v2/top-headlines?country=us&category=business&from={yesterday}&to={today}&sortBy=popularity&apiKey={news_api_key}'
        response = requests.get(url)
        response.raise_for_status()  # 如果請求返回錯誤狀態碼，則引發 HTTPError
        news_data = response.json()
        articles = news_data['articles'][:5]
        news_list = [f"{article['title']}: {article['url']}" for article in articles]
        return '\n'.join(news_list)
    except requests.exceptions.RequestException as e:
        return "無法獲取新聞，請稍後再試。"
    

def send_daily_news():
    news = fetch_news()
    line_bot_api.broadcast(TextSendMessage(text=news))    

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

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text
    if msg == 'now':
        news = fetch_news()
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=news)) 
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
    taiwan_tz = pytz.timezone('Asia/Taipei')
    target_time = datetime.now(taiwan_tz).replace(hour=22, minute=15, second=0, microsecond=0)
    
    if datetime.now(taiwan_tz) > target_time:
        target_time += timedelta(days=1)

    delay = (target_time - datetime.now(taiwan_tz)).total_seconds()

    def job():
        send_daily_news()
        schedule_news_updates()  # 重新設置下一次調度

    time.sleep(delay)
    job()  # 第一次立即執行
    schedule.every().day.at("22:15").do(job)  # 之後每天固定時間執行

    while True:
        schedule.run_pending()
        time.sleep(1)

# 啟動調度器
schedule_thread = Thread(target=schedule_news_updates)
schedule_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
