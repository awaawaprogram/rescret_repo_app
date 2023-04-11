import base64
import hashlib
import hmac
import json
import requests
import boto3
import os
import time

LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_COMPLETIONS_ENDPOINT = os.getenv('OPENAI_COMPLETIONS_ENDPOINT')
LINE_REPLY_ENDPOINT = os.getenv('LINE_REPLY_ENDPOINT')

STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
PLAN_580_JPY = os.getenv('PLAN_580_JPY')
PLAN_1080_JPY = os.getenv('PLAN_1080_JPY')

CHAT_HISTORY_TABLE_NAME = 'chat_history'
USER_DATA_TABLE_NAME = 'user_data'
CHAT_ARCHIVE_TABLE_NAME = 'chat_archive'
PROMPT_ARCHIVE_TABLE_NAME = 'prompt_archive'


AWS_REGION = os.getenv('AWS_DB_REGION')  # 環境変数からリージョンを取得
dynamo = boto3.resource('dynamodb', region_name=AWS_REGION)

# ----- Validation Functions -----

def validate_type(event):
    event_type = json.loads(event['body'])['events'][0]['type']
    if event_type != 'message':
        raise Exception('Invalid LINE event type')

def validate_signature(event):
    body = event['body']
    hash = hmac.new(LINE_CHANNEL_SECRET.encode('utf-8'),
                    body.encode('utf-8'), hashlib.sha256).digest()
    signature = base64.b64encode(hash)
    if signature != event['headers']['x-line-signature']:
        raise Exception('Invalid signature')

# ----- Helper Functions -----

def populate_conversation(user_id, message, user_data):
    try:
        # Get conversation history
        convo_list = dynamo.scan(
            TableName=CHAT_HISTORY_TABLE_NAME,
            FilterExpression="user_id = :user_id",
            ExpressionAttributeValues={":user_id": {"S": user_id}}
        )["Items"]

        # Get the prompt with the maximum prompt_id
        max_prompt_id = dynamo.query(
            TableName=PROMPT_HISTORY_TABLE,
            KeyConditionExpression="user_id = :user_id",
            ExpressionAttributeValues={":user_id": {"S": user_id}},
            ScanIndexForward=False,
            Limit=1
        )["Items"][0]["prompt"]["S"]

        # Calculate token count and sort the conversations
        for convo in convo_list:
            convo["token_count"] = sum(
                len(msg["content"]) for msg in json.loads(convo["conversation"]["S"])
            )

        convo_list.sort(key=lambda x: (-x["message_count"]["N"], x["token_count"]))

        # Filter conversations to keep token count below 2000
        filtered_convo_list = []
        total_tokens = 0
        for convo in convo_list:
            if total_tokens + convo["token_count"] <= 2000:
                filtered_convo_list.append(convo)
                total_tokens += convo["token_count"]

        # Combine the conversations
        combined_convo = [{"role": "system", "content": max_prompt_id}]
        for convo in reversed(filtered_convo_list):
            combined_convo.extend(json.loads(convo["conversation"]["S"]))

        combined_convo.append({"role": "user", "content": message})
    except Exception as e:
        print(e)
        combined_convo = [
            {"role": "system", "content": max_prompt_id},
            {"role": "user", "content": message},
        ]

    return combined_convo




def openai_completions(prompt):
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer {}'.format(OPENAI_API_KEY)
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": prompt,
        "max_tokens": 1000,
    }
    try:
        openai_response = requests.post(OPENAI_COMPLETIONS_ENDPOINT, headers=headers, data=json.dumps(data))
        message = openai_response.json()['choices'][0]['message']['content']
        if message is None:
            raise Exception('OpenAI response is empty')
        return openai_response
    except Exception as e:
        print(e)
        raise Exception('OpenAIが壊れてました😢')


def format_openai_response(openai_response):
    message = openai_response.json()['choices'][0]['message']['content'].split("AI: ")[-1]
    return message

def get_openai_cost_jpy(openai_response):
    cost_jpy = openai_response.json()['usage']['total_tokens'] * 0.000002 * 135
    return cost_jpy

def store_conversation(user_id, query, openai_response):
    conversation = query + [{"role": "assistant", "content": openai_response.json()['choices'][0]['message']['content']}]
    token_count = sum(len(msg["content"]) for msg in conversation)
    message_count = len(conversation) // 2
    dynamo.put_item(
        TableName=CHAT_HISTORY_TABLE_NAME,
        Item={
            'user_id': {
                'S': user_id,
            },
            'conversation': {
                'S': json.dumps(conversation),
            },
            'token_count': {
                'N': str(token_count),
            },
            'message_count': {
                'N': str(message_count),
            }
        }
    )



def line_reply(reply_token, response, cost_jpy):
    headers = {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer {}'.format(LINE_CHANNEL_ACCESS_TOKEN)
    }
    data = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": response
            },
            {
                "type": "template",
                "altText": response,
                "template": {
                    "type": "buttons",
                    "text": 'AI利用料は{} 円でした💰\n会話をリセットしますか？'.format(round(cost_jpy, 3)),
                    "actions": [
                        {
                            "type": "message",
                            "label": "リセットする",
                            "text": "reset"
                        }
                    ]
                }
            }
        ]
    }
    r = requests.post(LINE_REPLY_ENDPOINT, headers=headers, data=json.dumps(data))
    print('LINE response: {}'.format(r.json()))


def archive_conversation(user_id):
    try:
        history = dynamo.get_item(
            TableName=CHAT_HISTORY_TABLE_NAME,
            Key={
                'user_id': {
                    'S': user_id,
                }
            }
        ).get('Item').get('conversation').get('S')

        dynamo.put_item(
            TableName=CHAT_HISTORY_TABLE_NAME,
            Item={
                'user_id': {
                    'S': user_id + "-" + str(int(time.time())),
                },
                'conversation': {
                    'S': history,
                }
            }
        )
    except Exception as e:
        print('failed to archive conversation: {}'.format(e))

    dynamo.delete_item(
        TableName=CHAT_HISTORY_TABLE_NAME,
        Key={
            'user_id': {
                'S': user_id,
            }
        }
    )


def send_upgrade_link(reply_token):
    headers = {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer {}'.format(LINE_CHANNEL_ACCESS_TOKEN)
    }
    data = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "template",
                "altText": "Upgrade to a paid plan",
                "template": {
                    "type": "buttons",
                    "text": "料金プランにアップグレードしましょう",
                    "actions": [
                        {
                            "type": "uri",
                            "label": "580円プラン",
                            "uri": "https://your_website.com/upgrade?plan_id={}".format(PLAN_580_JPY)
                        },
                        {
                            "type": "uri",
                            "label": "1080円プラン",
                            "uri": "https://your_website.com/upgrade?plan_id={}".format(PLAN_1080_JPY)
                        }
                    ]
                }
            }
        ]
    }
    r = requests.post(LINE_REPLY_ENDPOINT, headers=headers, data=json.dumps(data))
    print('LINE response: {}'.format(r.json()))




def can_use_more_tokens(cost_jpy, user_data):
    try:
        if 'tokens_used' not in user_data:
            return True

        tokens_used = float(user_data['tokens_used']['N'])
        plan_id = user_data.get('plan_id', {}).get('S', '')

        token_limits = {
            PLAN_580_JPY: 1000000,
            PLAN_1080_JPY: float('inf'),
        }
        return tokens_used + cost_jpy <= token_limits.get(plan_id, 5)
    except:
        return False



def update_tokens_used(user_id, cost_jpy):
    dynamo.update_item(
        TableName=USER_DATA_TABLE_NAME,
        Key={
            'user_id': {
                'S': user_id,
            }
        },
        UpdateExpression="SET tokens_used = tokens_used + :t",
        ExpressionAttributeValues={
            ':t': {
                'N': str(cost_jpy)
            }
        }
    )


def update_message_count(user_id):
    dynamo.update_item(
        TableName=USER_DATA_TABLE_NAME,
        Key={
            'user_id': {
                'S': user_id,
            }
        },
        UpdateExpression="ADD message_count :mc",
        ExpressionAttributeValues={
            ':mc': {
                'N': '1'
            }
        }
    )


PROMPT_HISTORY_TABLE = 'prompt_history'

def store_prompt(user_id, prompt_text):
    try:
        user_data = dynamo.get_item(
            TableName=USER_DATA_TABLE_NAME,
            Key={
                'user_id': {
                    'S': user_id,
                }
            }
        ).get('Item')
        prompt_count = int(user_data.get('prompt_count', {}).get('N', '0'))
        prompt_count += 1
        dynamo.put_item(
            TableName=PROMPT_HISTORY_TABLE,
            Item={
                'user_id': {
                    'S': user_id,
                },
                'prompt_id': {
                    'N': str(prompt_count)
                },
                'prompt': {
                    'S': prompt_text,
                }
            }
        )
        update_prompt_count(user_id)
    except Exception as e:
        print('Failed to store prompt: {}'.format(e))

def update_prompt_count(user_id):
    dynamo.update_item(
        TableName=USER_DATA_TABLE_NAME,
        Key={
            'user_id': {
                'S': user_id,
            }
        },
        UpdateExpression="ADD prompt_count :pc",
        ExpressionAttributeValues={
            ':pc': {
                'N': '1'
            }
        }
    )


def lambda_handler(event, context):
    print(event)

    try:
        validate_type(event)
        validate_signature(event)
        user_id = json.loads(event['body'])['events'][0]['source']['userId']
        message = json.loads(event['body'])['events'][0]['message']['text']
        reply_token = json.loads(event['body'])['events'][0]['replyToken']
        if user_id is None or message is None or reply_token is None:
            raise Exception('Empty request')

    except:
        return {
            'statusCode': 400
        }

    user_data = dynamo.get_item(
        TableName=USER_DATA_TABLE_NAME,
        Key={
            'user_id': {
                'S': user_id,
            }
        }
    ).get('Item')

    if message == 'reset':
        archive_conversation(user_id)
        return {
            'statusCode': 200
        }
    
    if message.startswith('system:'):
        prompt_text = message[7:]
        store_prompt(user_id, prompt_text)
        return {
            'statusCode': 200
        }


    message_count = int(user_data.get('message_count', {}).get('N', '0'))
    paid_user = 'plan_id' in user_data
    if message_count > 5 and not paid_user:
        send_upgrade_link(reply_token)
        return {
            'statusCode': 200
        }

    try:
        query = populate_conversation(user_id, message, user_data)
        openai_response = openai_completions(query)
        response = format_openai_response(openai_response)
        cost_jpy = get_openai_cost_jpy(openai_response)

        if not can_use_more_tokens(cost_jpy, user_data):
            send_upgrade_link(reply_token)
            return {
                'statusCode': 200
            }

        store_conversation(user_id, query, openai_response)
        update_tokens_used(user_id, cost_jpy)
        update_message_count(user_id)

    except Exception as e:
        cost_jpy = 0
        response = 'OpenAIが壊れてました😢'
        print(e)

    line_reply(reply_token, response, cost_jpy)

    return {
        'statusCode': 200,
    }
