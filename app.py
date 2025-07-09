import streamlit as st
import requests
import base64
import time

# Your Lambda URL
LAMBDA_URL = 'https://x47db2o5c7dlbd4uyhpbkyenwa0lztct.lambda-url.us-east-1.on.aws/'

VOICE_OPTIONS = {
    "Joanna (English US)": ("Joanna", "en-US"),
    "Matthew (English US)": ("Matthew", "en-US"),
    "Lucia (Spanish Spain)": ("Lucia", "es-ES"),
    "Celine (French)": ("Celine", "fr-FR")
}

st.set_page_config(page_title="Web Page to Speech", page_icon="🔊")

st.title("🌐 Web Page to Speech (via AWS Lambda + Polly)")

url_input = st.text_input("Enter webpage URL:", placeholder="https://example.com")
voice_label = st.selectbox("Select voice:", list(VOICE_OPTIONS.keys()))

# Placeholder containers for dynamic clearing
msg_placeholder = st.empty()
audio_placeholder = st.empty()
remove_audio_button_placeholder = st.empty()

if st.button("Generate Speech"):
    msg_placeholder.empty()
    audio_placeholder.empty()
    remove_audio_button_placeholder.empty()

    if not url_input:
        msg_placeholder.error("Please provide a URL.")
        time.sleep(3)
        msg_placeholder.empty()
    else:
        with st.spinner("Processing..."):
            voice_id, language_code = VOICE_OPTIONS[voice_label]
            payload = {
                "url": url_input,
                "voiceId": voice_id,
                "language": language_code
            }

            try:
                response = requests.post(
                    LAMBDA_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=60
                )

                if response.status_code == 200:
                    try:
                        lambda_result = response.json()
                        audio_b64 = lambda_result.get("audio")
                        if not audio_b64:
                            msg_placeholder.error("No audio data returned.")
                            time.sleep(8)
                            msg_placeholder.empty()
                        else:
                            audio_bytes = base64.b64decode(audio_b64)
                            msg_placeholder.success("✅ Speech generated!")
                            time.sleep(8)
                            msg_placeholder.empty()
                            audio_placeholder.audio(audio_bytes, format="audio/mp3")
                            if remove_audio_button_placeholder.button("Remove Audio Player"):
                                audio_placeholder.empty()
                                remove_audio_button_placeholder.empty()

                    except Exception as e:
                        msg_placeholder.error(f"❌ Failed to parse Lambda response: {str(e)}")
                        st.text(response.text)
                        time.sleep(8)
                        msg_placeholder.empty()
                else:
                    try:
                        error_msg = response.json()
                    except:
                        error_msg = response.text
                    msg_placeholder.error(f"❌ Error: {response.status_code} — {error_msg}")
                    time.sleep(8)
                    msg_placeholder.empty()

            except Exception as e:
                msg_placeholder.error(f"❌ Request failed: {str(e)}")
                time.sleep(8)
                msg_placeholder.empty()