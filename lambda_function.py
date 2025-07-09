import json
import requests
from bs4 import BeautifulSoup
import boto3
import base64
import asyncio

polly_client = boto3.client('polly')
bedrock_client = boto3.client("bedrock-runtime", region_name="us-east-1")

# Max input size per Bedrock call
BEDROCK_MAX_INPUT_CHARS = 4000

def extract_raw_text_chunks(html_content):
    chunks = [html_content[i:i+BEDROCK_MAX_INPUT_CHARS] for i in range(0, len(html_content), BEDROCK_MAX_INPUT_CHARS)]
    return chunks

def is_spa(content):
    if len(content.strip()) < 100:
        return True
    spa_markers = ['id="app"', 'ng-app', 'react-root', 'data-reactroot', 'id="root"']
    return any(marker in content.lower() for marker in spa_markers)

import time
import random

def call_bedrock_claude(html_chunk):
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Take this raw HTML content of a webpage. Extract and structure the meaningful text for natural speech. "
                    "Add appropriate punctuation (commas, full stops, etc.). Remove navigation, footers, ads, and irrelevant content. "
                    "Output clean, plain text suitable for text-to-speech reading.\n\n"
                    f"{html_chunk}"
                )
            }
        ],
        "max_tokens": 2000,
        "temperature": 0.6
    })

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            response = bedrock_client.invoke_model(
                modelId="anthropic.claude-3-sonnet-20240229-v1:0",
                contentType="application/json",
                accept="application/json",
                body=body
            )
            response_body = json.loads(response['body'].read())
            return response_body.get("content", "")
        except bedrock_client.exceptions.ThrottlingException as e:
            if attempt == max_attempts:
                raise
            sleep_time = (2 ** attempt) + random.uniform(0, 1)
            print(f"Throttled. Attempt {attempt}/{max_attempts}. Sleeping for {sleep_time:.2f} seconds.")
            time.sleep(sleep_time)
        except Exception as e:
            raise e


async def process_with_bedrock(html_chunk):
    prompt = (
        "Take this raw HTML content of a webpage. Extract and structure the meaningful text for natural speech. "
        "Add appropriate punctuation (commas, full stops, etc.). Remove navigation, footers, ads, and irrelevant content. "
        "Output clean, plain text suitable for text-to-speech reading.\n\n"
        f"{html_chunk}"
    )
    # Run in a thread to not block event loop
    from asyncio import to_thread
    return await to_thread(call_bedrock_claude, prompt)

def synthesize_with_polly(text, voice_id, language_code):
    polly_response = polly_client.synthesize_speech(
        Text=text,
        OutputFormat='mp3',
        VoiceId=voice_id,
        LanguageCode=language_code
    )
    return polly_response['AudioStream'].read()

def lambda_handler(event, context):
    try:
        if event.get('body'):
            body = json.loads(event['body'])
        else:
            body = event
    except Exception:
        body = event

    url = body.get('url')
    language_code = body.get('language', 'en-US')
    voice_id = body.get('voiceId', 'Joanna')

    if not url:
        return {
            'statusCode': 400,
            'body': json.dumps('Missing URL parameter')
        }

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error fetching page: {str(e)}')
        }

    html_content = response.text

    if is_spa(html_content):
        return {
            'statusCode': 422,
            'body': json.dumps('The requested page appears to be a single-page application (SPA) or contains little readable text.')
        }

    html_chunks = extract_raw_text_chunks(html_content)

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bedrock_tasks = [process_with_bedrock(chunk) for chunk in html_chunks]
        cleaned_parts = loop.run_until_complete(asyncio.gather(*bedrock_tasks))
        cleaned_text = " ".join(cleaned_parts)
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps(f'Bedrock error: {str(e)}')
        }

    if not cleaned_text or len(cleaned_text.strip()) < 50:
        return {
            'statusCode': 422,
            'body': json.dumps('Unable to extract meaningful text from the page after AI processing.')
        }

    try:
        audio_data = synthesize_with_polly(cleaned_text, voice_id, language_code)
        audio_b64 = base64.b64encode(audio_data).decode('utf-8')
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps(f'Polly error: {str(e)}')
        }

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json'
        },
        'body': json.dumps({
            'audio': audio_b64
        })
    }
