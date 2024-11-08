import json
import re
from typing import AsyncGenerator

import google.generativeai as genai
from google.ai.generativelanguage_v1beta.types.content import Blob, Content, Part
from google.generativeai.types import HarmBlockThreshold, HarmCategory


def initialize_genai(api_key: str, model: str = "gemini-1.5-flash-002"):
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model)


def get_prompt() -> str:
    return """
    Role: Professional Image Text Recognizer and Translator

    Languages:
      - Image Text: Automatically detect (Japanese or English)
      - Translation: Translate to the other language (English or Japanese)

    Instructions:
    1. Accurately transcribe the text in the image, detecting whether it's in Japanese or English.
    2. Preserve the original text format and structure:
       - Maintain bullet points, numbered lists, and other formatting elements.
       - Keep line breaks and paragraph structures intact.
       - Preserve any special characters or symbols used for formatting.
    3. Refine the transcription:
       - Retain all meaningful punctuation.
       - Accurately capture any emphasis (bold, italic, underline) if discernible.
    4. Translate the transcribed text to the other language (Japanese to English or English to Japanese).
    5. In the translation:
       - Maintain the original formatting, including lists and line breaks.
       - Preserve the tone, style, and intent of the original text.
       - Adapt idiomatic expressions and cultural nuances appropriately.
    6. Ensure both the transcription and translation accurately reflect the original image text in content and format.
    7. Always provide both the original text and its translation, regardless of the detected language.
    8. Output the result in the following JSON format:
        ```json
        {
            "detected_language": "The detected language (either 'ja' or 'en')",
            "ja": "The Japanese text (either transcription or translation)",
            "en": "The English text (either transcription or translation)"
        }
        ```
    """


def prepare_contents(prompt: str, image: bytes) -> list[Content]:
    return [
        Content(role="user", parts=[Part(text=prompt)]),
        Content(
            role="user",
            parts=[Part(inline_data=Blob(mime_type="image/jpeg", data=image))],
        )
    ]


def get_generation_config():
    return genai.GenerationConfig(
        temperature=0,
        response_mime_type="application/json",
        response_schema={
            "type": "object",
            "properties": {
                "detected_language": {"type": "string", "enum": ["ja", "en"]},
                "ja": {"type": "string"},
                "en": {"type": "string"},
            },
            "required": ["detected_language", "ja", "en"],
        }
    )


def get_safety_settings():
    return {
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    }


async def transcribe_and_translate_image_stream(gen_model: genai.GenerativeModel, image: bytes) -> AsyncGenerator[tuple[str, str, str], None]:
    prompt = get_prompt()
    contents = prepare_contents(prompt, image)

    res = await gen_model.generate_content_async(
        contents=contents,
        generation_config=get_generation_config(),
        safety_settings=get_safety_settings(),
        stream=True,
    )

    async for detected_lang, ja_text, en_text in process_response_stream(res):
        yield detected_lang, ja_text, en_text


async def process_response_stream(res) -> AsyncGenerator[tuple[str, str, str], None]:
    all_text = ""
    partial_result = {"detected_language": "", "ja": "", "en": ""}
    key_patterns = {
        "detected_language": r'"detected_language"\s*:\s*"(ja|en)"',
        "ja": r'"ja"\s*:\s*"((?:[^"]|\\")*)',
        "en": r'"en"\s*:\s*"((?:[^"]|\\")*)'
    }

    async for chunk in res:
        if chunk.text:
            all_text += chunk.text
            update_partial_result(all_text, partial_result, key_patterns)
            yield partial_result["detected_language"], partial_result["ja"], partial_result["en"]

    yield_final_result(res)


def update_partial_result(all_text: str, partial_result: dict, key_patterns: dict):
    for key, pattern in key_patterns.items():
        match = re.search(pattern, all_text)
        if match:
            value = match.group(1)
            value = value.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')
            partial_result[key] = value


def yield_final_result(res):
    try:
        final_json = json.loads(res.text)
        yield final_json["detected_language"], final_json["ja"], final_json["en"]
    except json.JSONDecodeError:
        raise Exception("failed to decode final json")
