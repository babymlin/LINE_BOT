from flask import Flask, abort, request, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (ImagemapSendMessage, TextSendMessage, ImageSendMessage,
    LocationSendMessage, FlexSendMessage, VideoSendMessage,
    AudioSendMessage, TemplateSendMessage, StickerSendMessage)
from linebot.models.template import (ButtonsTemplate, CarouselTemplate,
    ConfirmTemplate, ImageCarouselTemplate)
from linebot.models.events import FollowEvent
import google.cloud.logging
from google.cloud import storage
from google.cloud import firestore
from google.cloud.logging.handlers import CloudLoggingHandler
import json
import urllib.request
import os
import logging
import glob
import face_recognition

client = google.cloud.logging.Client()

#設定專案路徑
project_path = "./"
json_path = project_path + "json/"
catch_path = project_path + "catch/"

# 建立line event log，用來記錄line event
bot_event_handler = CloudLoggingHandler(client , name="輸入你的GCP專案名")
bot_event_logger = logging.getLogger('輸入你的GCP專案名')
bot_event_logger.setLevel(logging.INFO)
bot_event_logger.addHandler(bot_event_handler)

#啟動Flask Server
app = Flask(__name__)

#物件化LineBotApi(LineServer溝通)，Webhookhandler(確認用戶訊息)
line_bot_api = LineBotApi("輸入你的token:")
handler = WebhookHandler("輸入你的Channel secret")

#啟動server對外接口route，讓Line丟資料進來，並記錄event.log。
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text = True)
    print(body)
    
    bot_event_logger.info(body)
        
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)
    
    return "OK"

# 讀取line bot designer設計的json格式，轉換成為各類SendMessage
# 務必在json檔案前後加上[]，下方程式碼會去拆list，才能1個json檔案寫入2個以上動作

def detect_json_array_to_new_message_array(fileName):
    #開啟檔案，轉成json
    with open(fileName, encoding="utf-8-sig") as f:
        jsonArray = json.load(f)
    # 解析json
    returnArray = []
    # 拆json裡頭list所涵蓋的動作，依type做分類後給line-bot-sdk讀取json_dict
    for jsonObject in jsonArray:
        # 讀取其用來判斷的元件
        message_type = jsonObject.get('type')
        # 轉換
        if message_type == 'text':
            returnArray.append(TextSendMessage.new_from_json_dict(jsonObject))
        elif message_type == 'imagemap':
            returnArray.append(ImagemapSendMessage.new_from_json_dict(jsonObject))
        elif message_type == 'template':
            returnArray.append(TemplateSendMessage.new_from_json_dict(jsonObject))
        elif message_type == 'image':
            returnArray.append(ImageSendMessage.new_from_json_dict(jsonObject))
        elif message_type == 'sticker':
            returnArray.append(StickerSendMessage.new_from_json_dict(jsonObject))  
        elif message_type == 'audio':
            returnArray.append(AudioSendMessage.new_from_json_dict(jsonObject))  
        elif message_type == 'location':
            returnArray.append(LocationSendMessage.new_from_json_dict(jsonObject))
        elif message_type == 'flex':
            returnArray.append(FlexSendMessage.new_from_json_dict(jsonObject))  
        elif message_type == 'video':
            returnArray.append(VideoSendMessage.new_from_json_dict(jsonObject))    
    # 回傳
    return returnArray

#FollowEvent，取user_profile。
result_message_array = detect_json_array_to_new_message_array(json_path + "welcome.json")

@handler.add(FollowEvent)
def reply_text_and_get_user_profile(event):
    # 取個資
    line_user_profile= line_bot_api.get_profile(event.source.user_id)

    # 跟line 取回照片，並放置在本地端
    file_name = line_user_profile.user_id+'.jpg'
    urllib.request.urlretrieve(line_user_profile.picture_url, file_name)

    # 設定內容
    storage_client = storage.Client()
    bucket_name = "linebot-user-info"
    destination_blob_name = f"{line_user_profile.user_id}/user_pic.png"
    source_file_name = file_name
       
    # 進行上傳
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_name)

    # 設定用戶資料json
    user_dict={
	"user_id":line_user_profile.user_id,
	"picture_url": f"https://storage.googleapis.com/{bucket_name}/{destination_blob_name}",
	"display_name": line_user_profile.display_name,
	"status_message": line_user_profile.status_message
      }
    # 插入firestore
    db = firestore.Client()
    doc_ref = db.collection(u"line-user").document(user_dict.get("user_id"))
    doc_ref.set(user_dict)
    
    #回覆+好友的消息與圖片
    line_bot_api.reply_message(
        event.reply_token,
        result_message_array
    )

#依據用戶輸入的文字消息，回復用戶並判斷用戶輸入是否正確。
from linebot.models import MessageEvent, TextMessage
@handler.add(MessageEvent, message=TextMessage)
def process_text_message(event):
    #用戶輸入正確關鍵字，就在資料夾找對應同檔名json檔
    replyJsonPath = json_path + event.message.text + ".json"
    #判斷是否跑postbackevent
    if event.message.text.find("讓我們開始挑戰吧！") == 0:
        count = 0
        shutdown = 0
        if os.path.exists(catch_path + event.source.user_id + ".txt"):
            #讀取user_id檔案中紀錄，來確認已經回答過幾次。
            with open(catch_path + event.source.user_id + ".txt", "r") as fanswer:
                for line in fanswer:
                    if "答對了" in line:
                        shutdown = 1
                    count += 1
                if count <3 and shutdown == 0:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(
                            text = "傅采林說道：請問幫會成員「面目全非的醜八怪」共有幾位", quick_reply = quickReplyList
                        )
                    )
                elif shutdown == 1:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(
                            text = "傅采林說道：您已經答對了，無須再次挑戰！"
                        )
                    )
                else:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextMessage(
                            text = f"傅采林說道：很遺憾，您的機會已全數用罄。\n感謝您加入Line好友，仍可於6/5後憑Line好友名稱，至210.59.236.38:7788，chat索取節日EQ或丹藥。"
                        )
                    )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text = "傅采林說道：請問幫會成員「面目全非的醜八怪」共有幾位", quick_reply = quickReplyList
                )
            )
    else:
        #判斷json指令是否存在
        if os.path.exists(replyJsonPath):
            result_message_array = detect_json_array_to_new_message_array(replyJsonPath)
            line_bot_api.reply_message(
                event.reply_token,
                result_message_array)
        elif len(event.message.text)<16:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text = "請輸入「關鍵字」，或點擊圖片「關鍵字」位置"))


# 準備quickreply按鍵，quickreplybutton使用後會消失，避免用戶重複選擇。
# 引入相關套件
from linebot.models import (MessageAction, URIAction, PostbackAction,
    DatetimePickerAction, CameraAction, CameraRollAction, LocationAction,
    QuickReply, QuickReplyButton)
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
# 創建QuickReplyButton 
## 點擊後，以Postback事件回應Server 
postbackQRB0 = QuickReplyButton(
    action=PostbackAction(label="27", data="27位")
)
postbackQRB1 = QuickReplyButton(
    action=PostbackAction(label="28", data="28位")
)
postbackQRB2 = QuickReplyButton(
    action=PostbackAction(label="29", data="29位")
)
postbackQRB3 = QuickReplyButton(
    action=PostbackAction(label="30", data="30位")
)

## 設計QuickReplyButton的List
quickReplyList = QuickReply(
    items = [postbackQRB0, postbackQRB1, postbackQRB2, postbackQRB3]
)

# 依據用戶點選按鍵後回傳的PostbackEvent做邏輯處理
from linebot.models import PostbackEvent
@handler.add(PostbackEvent)
def handle_post_message(event):
    count = 0
    if os.path.exists(catch_path + event.source.user_id + ".txt"):
        #讀取user_id檔案中紀錄，來確認已經回答過幾次。
        with open(catch_path + event.source.user_id + ".txt", "r") as fanswer:
            for _ in fanswer:
                count += 1
    if (event.postback.data.find('29位')== 0):
        with open(catch_path + event.source.user_id + ".txt", "a") as fanswer:
            fanswer.write(str(event.timestamp) + "答對了\n")
            count += 1
        line_bot_api.reply_message(
        event.reply_token,
            TextMessage(
                text = f"傅采林說道：恭喜您，答對了，正確答案就是{event.postback.data}。\n感謝您加入Line好友，可於6/5後憑Line好友名稱，至210.59.236.38:7788，chat索取節日EQ或丹藥。"
            )
        )
    else:
        with open(catch_path + event.source.user_id + ".txt", "a") as fanswer:
            fanswer.write(str(event.timestamp) + "答錯了\n")
            count += 1
        if 3-count > 0:
            line_bot_api.reply_message(
            event.reply_token,
                TextMessage(
                    text = f"傅采林說道：很遺憾，答案不是{event.postback.data}。\n這是您第{count}次回答，剩下{3-count}次機會。\n如需挑戰，請再次輸入「challenge」。\n請把握3次回答機會。"
                )
            )
        else:
            line_bot_api.reply_message(
            event.reply_token,
                TextMessage(
                    text = f"傅采林說道：很遺憾，您的機會已全數用罄。\n感謝您加入Line好友，仍可於6/5後憑Line好友名稱，至210.59.236.38:7788，chat索取節日EQ或丹藥。"
                )
            )

# 紀錄用戶 => chatbot的圖片、聲音、影片資料
from linebot.models import MessageEvent, ImageMessage, VideoMessage, AudioMessage, TextSendMessage

# 用戶告訴handler，當收到圖片消息時，執行下面的方法。
@handler.add(MessageEvent, message = ImageMessage)
def handle_image_message(event):      
    #依據消息ID(event.message.id)向Line索取檔案回來
    message_content = line_bot_api.get_message_content(event.message.id)
    with open(event.message.id + ".png", "wb") as fd:
        for chunk in message_content.iter_content():
            fd.write(chunk)

    storage_client = storage.Client()
    bucket_name = "linebot-user-info"
    destination_blob_name = f'{event.source.user_id}/image/{event.message.id}.png'
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(f"{event.message.id}.png")

    known_list = glob.glob("./known_person/*")
    encodinglist = list()
    inp_img = face_recognition.load_image_file(f"{event.message.id}.png")
    inp_img_encoding = face_recognition.face_encodings(inp_img)[0]
    for known in known_list:
        img = face_recognition.load_image_file(known)
        img_encoding = face_recognition.face_encodings(img)[0]
        encodinglist.append(img_encoding)
    results = face_recognition.face_distance(encodinglist, inp_img_encoding)
    text_result = f"經過人臉辨識，您與：\n劉德華相似度{(1-results[0]+0.2)*100:.2f}%\n梁朝偉相似度{(1-results[1]+0.2)*100:.2f}%\n林志玲相似度{(1-results[2]+0.2)*100:.2f}%\n宋慧喬相似度{(1-results[3]+0.2)*100:.2f}%"

    if 1-min(results) <= 0.4:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text = "無法辨識，請重新選擇照片"))
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text = text_result))
            
@handler.add(MessageEvent, message = VideoMessage)
def handle_Video_message(event): 
    #先回應用戶圖片上傳的ID
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text = "影片標示功能開發中…"))

    #依據消息ID(event.message.id)向Line索取檔案回來
    message_content = line_bot_api.get_message_content(event.message.id)
    with open(event.message.id + ".mp4", "wb") as fd:
        for chunk in message_content.iter_content():
            fd.write(chunk)
    
    storage_client = storage.Client()
    bucket_name = "linebot-user-info"
    destination_blob_name = f'{event.source.user_id}/video/{event.message.id}.mp4'
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(f"{event.message.id}.mp4")

@handler.add(MessageEvent, message = AudioMessage)
def handle_Audio_message(event):    
    #先回應用戶圖片上傳的ID
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text = "語音翻譯功能開發中…"))

    #依據消息ID(event.message.id)向Line索取檔案回來
    message_content = line_bot_api.get_message_content(event.message.id)
    with open(event.message.id + ".mp3", "wb") as fd:
        for chunk in message_content.iter_content():
            fd.write(chunk)            
    
    storage_client = storage.Client()
    bucket_name = "linebot-user-info"
    destination_blob_name = f'{event.source.user_id}/audio/{event.message.id}.mp3'
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(f"{event.message.id}.mp3")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
