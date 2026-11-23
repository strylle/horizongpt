# llm.py
# talks to the ai. pick anthropic, openai or gemini in config.json
# keys: ANTHROPIC_API_KEY, OPENAI_API_KEY or GEMINI_API_KEY

import json
import os

import settings

provider = settings.provider

# claude models that can fall back if they refuse
anthropic_fallback_models = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1", "claude-opus-5"]


# any provider's api error
class LLMError(Exception):
    pass


key_names = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}


# what's missing, or None
def missing_key():
    key = key_names.get(provider)
    if key is not None and not os.environ.get(key):
        return "Put your " + key + " in .env first."
    return None


client = None


def get_client():
    global client
    if client is not None:
        return client
    if missing_key() is not None:
        raise LLMError(missing_key())
    if provider == "anthropic":
        import anthropic
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        if workspace:
            client = anthropic.Anthropic(default_headers={"anthropic-workspace-id": workspace})
        else:
            client = anthropic.Anthropic()
    elif provider == "openai":
        import openai
        client = openai.OpenAI()
    elif provider == "gemini":
        from google import genai
        client = genai.Client()
    else:
        raise ValueError("unknown provider in config.json: " + provider)
    return client


# provider errors -> LLMError
def api_errors():
    if provider == "anthropic":
        import anthropic
        return (anthropic.APIError,)
    if provider == "openai":
        import openai
        return (openai.OpenAIError,)
    from google.genai import errors
    return (errors.APIError,)


# text answer. returns (text, refused)
def write(system, message, model, effort, max_tokens=16000):
    try:
        return call(system, message, model, effort, max_tokens, None)
    except api_errors() as e:
        raise LLMError(str(e)) from e


# json answer matching the schema, or None
def write_json(system, message, schema, model, effort="low", max_tokens=2048):
    try:
        text, refused = call(system, message, model, effort, max_tokens, schema)
    except api_errors() as e:
        raise LLMError(str(e)) from e
    if refused or text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# text is None if it got cut off
def call(system, message, model, effort, max_tokens, schema):
    c = get_client()

    if provider == "anthropic":
        output_config = {"effort": effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        request = dict(model=model, max_tokens=max_tokens, system=system, output_config=output_config,
                       messages=[{"role": "user", "content": message}])
        if model in anthropic_fallback_models and schema is None:
            response = c.beta.messages.create(**request, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            response = c.messages.create(**request)
        if response.stop_reason == "refusal":
            return None, True
        if schema is not None and response.stop_reason != "end_turn":
            return None, False
        text = ""
        for block in response.content:
            if block.type == "text":
                text = text + block.text
        return text.strip(), False

    if provider == "openai":
        request = dict(model=model, instructions=system, input=message, max_output_tokens=max_tokens,
                       reasoning={"effort": effort})
        if schema is not None:
            request["text"] = {"format": {"type": "json_schema", "name": "result", "schema": schema, "strict": True}}
        response = c.responses.create(**request)
        for item in response.output:
            for part in getattr(item, "content", None) or []:
                if part.type == "refusal":
                    return None, True
        if response.status != "completed":
            return None, False
        return response.output_text.strip(), False

    # gemini
    from google.genai import types
    level = effort.upper()
    if level not in ["LOW", "MEDIUM", "HIGH"]:
        level = "HIGH" if level in ["XHIGH", "MAX"] else "LOW"  # gemini flash has no minimal
    config = types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens,
                                         thinking_config=types.ThinkingConfig(thinking_level=level))
    if schema is not None:
        config.response_mime_type = "application/json"
        config.response_json_schema = schema
    response = c.models.generate_content(model=model, contents=message, config=config)
    if response.prompt_feedback is not None and response.prompt_feedback.block_reason:
        return None, True
    if not response.candidates:
        return None, False
    finish = str(response.candidates[0].finish_reason)
    if "SAFETY" in finish or "PROHIBITED" in finish or "BLOCKLIST" in finish:
        return None, True
    if "STOP" not in finish:
        return None, False
    return (response.text or "").strip(), False
