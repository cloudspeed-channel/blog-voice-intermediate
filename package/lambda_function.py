import json
import requests
import boto3
import base64
import time
import random

polly_client = boto3.client('polly')
bedrock_client = boto3.client("bedrock-runtime", region_name="us-east-1")

BEDROCK_MAX_INPUT_CHARS = 10000  # Keep within safe prompt size

def is_spa(content):
    if len(content.strip()) < 100:
        return True
    spa_markers = ['id="app"', 'ng-app', 'react-root', 'data-reactroot', 'id="root"']
    return any(marker in content.lower() for marker in spa_markers)

def call_bedrock_claude(html_content):
    safe_html = html_content[:BEDROCK_MAX_INPUT_CHARS]
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are given raw HTML content of a webpage. Your task is to extract and structure only the meaningful visible text content suitable for natural speech reading. "
                    "Ensure proper punctuation (commas, periods, etc.). Remove any navigation, footer, ads, or irrelevant elements. "
                    "⚠ IMPORTANT: Your response must contain ONLY the cleaned text of the webpage. Do not include any explanations, descriptions, or notes about what you did. "
                    "Do not say things like 'Here is the extracted text' or anything similar. Just output the plain cleaned text — nothing else.\n\n"
                    f"{safe_html}"
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

            # Extract text from the list of content
            content_list = response_body.get("content", [])
            cleaned_text = " ".join(part["text"] for part in content_list if part["type"] == "text")
            
            if not cleaned_text:
                raise Exception("Bedrock response missing usable text")
            
            return cleaned_text

        except bedrock_client.exceptions.ThrottlingException:
            if attempt == max_attempts:
                raise
            sleep_time = (2 ** attempt) + random.uniform(0, 1)
            print(f"Throttled attempt {attempt}/{max_attempts}. Sleeping {sleep_time:.2f}s.")
            time.sleep(sleep_time)
        except Exception as e:
            raise Exception(f"Bedrock error on attempt {attempt}: {str(e)}")

def synthesize_with_polly(text, voice_id, language_code):
    response = polly_client.synthesize_speech(
        Text=text,
        OutputFormat='mp3',
        VoiceId=voice_id,
        LanguageCode=language_code
    )
    return response['AudioStream'].read()

def lambda_handler(event, context):
    try:
        # Parse body (support API Gateway or Lambda URL)
        if event.get('body'):
            body = json.loads(event['body'])
        else:
            body = event

        url = body.get('url')
        language_code = body.get('language', 'en-US')
        voice_id = body.get('voiceId', 'Joanna')

        if not url:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing URL parameter'})
            }

        # Fetch page
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        html_content = response.text

        if is_spa(html_content):
            return {
                'statusCode': 422,
                'body': json.dumps({'error': 'Page is SPA or has little readable text'})
            }

        # Bedrock
        cleaned_text = call_bedrock_claude(html_content)
        if not cleaned_text or len(cleaned_text.strip()) < 50:
            return {
                'statusCode': 422,
                'body': json.dumps({'error': 'AI could not extract meaningful text'})
            }

        # Polly
        audio_data = synthesize_with_polly(cleaned_text, voice_id, language_code)
        audio_b64 = base64.b64encode(audio_data).decode('utf-8')

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'audio': audio_b64})
        }

    except requests.exceptions.RequestException as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'Error fetching page: {str(e)}'})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'Unhandled error: {str(e)}'})
        }
