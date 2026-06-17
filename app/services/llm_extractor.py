import logging
import json
from app.services.llm import generate, LLMUnavailable
from app.schemas.address_schema import AddressList
from app.models.address import Address as Phase1Address, AddressComponents
from app.services.address_service import AddressService

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a precise data extraction assistant. Extract EVERY postal address from the document text provided by the user.
Return the output as a strict JSON object matching this schema:
{
  "addresses": [
    {
      "street": "Street name, number, suite, apartment, box number",
      "city": "City name",
      "state": "State abbreviation or name",
      "zip": "ZIP/postal code"
    }
  ]
}
If no address is found, return:
{
  "addresses": []
}
Your output must be valid JSON and contain ONLY the JSON block. Do not write any explanations, code block ticks, or extra text."""

def extract_json_block(text: str) -> str:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
        return text[start_idx:end_idx + 1]
    return text

def convert_to_phase1_addresses(address_list: AddressList) -> list:
    """Convert Pydantic AddressList to list of Phase1Address objects."""
    results = []
    for addr in address_list.addresses:
        # Construct input_text for Phase 1 normalization
        raw_parts = [addr.street, addr.city, addr.state, addr.zip]
        raw_text = ", ".join([p for p in raw_parts if p])
        
        components = AddressComponents(
            primary_number="",
            street_name=addr.street,
            street_suffix="",
            city_name=addr.city,
            state_abbreviation=addr.state,
            zipcode=addr.zip
        )
        
        results.append(Phase1Address(
            input_text=raw_text,
            components=components
        ))
    return results

def get_generated_text(raw_response: str, messages: list) -> str:
    prompt_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])
    if raw_response.startswith(prompt_str):
        generated = raw_response[len(prompt_str):].strip()
    else:
        normalized_prompt = prompt_str.replace("\r\n", "\n").strip()
        normalized_raw = raw_response.replace("\r\n", "\n").strip()
        if normalized_raw.startswith(normalized_prompt):
            generated = normalized_raw[len(normalized_prompt):].strip()
        else:
            generated = raw_response
    
    if generated.startswith("assistant:"):
        generated = generated[len("assistant:"):].strip()
    elif generated.startswith("assistant\n"):
        generated = generated[len("assistant\n"):].strip()
    return generated


def extract_addresses_with_llm(text: str) -> tuple[list, str]:
    """
    Extract addresses from document text using LLM.
    Returns a tuple: (list of Phase1Address objects, path_taken)
    path_taken can be: 'llm', 'llm_retry', 'fallback_regex'
    """
    user_content = f"Document Text:\n{text}"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]
    
    # First attempt
    try:
        raw_response = generate(messages, max_tokens=1024)
        generated_text = get_generated_text(raw_response, messages)
        json_str = extract_json_block(generated_text)
        validated = AddressList.model_validate_json(json_str)
        logger.info("LLM address extraction successful on first attempt.")
        return convert_to_phase1_addresses(validated), "llm"
    except Exception as e:
        logger.warning(f"First LLM extraction attempt failed: {e}. Retrying...")
        error_msg = str(e)
        
        # Second attempt (Retry with error message)
        retry_user_content = (
            f"Document Text:\n{text}\n\n"
            f"Your previous response failed validation/parsing with the following error:\n{error_msg}\n"
            f"Please output a corrected, valid JSON matching the schema exactly."
        )
        retry_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": retry_user_content}
        ]
        
        try:
            raw_response = generate(retry_messages, max_tokens=1024)
            generated_text = get_generated_text(raw_response, retry_messages)
            json_str = extract_json_block(generated_text)
            validated = AddressList.model_validate_json(json_str)
            logger.info("LLM address extraction successful on retry.")
            return convert_to_phase1_addresses(validated), "llm_retry"
        except Exception as retry_e:
            logger.error(f"Second LLM extraction attempt failed: {retry_e}. Falling back to deterministic regex extractor.")
            
            # Fallback to Phase 1 deterministic extractor
            try:
                fallback_addresses = AddressService.process_text(text)
                return fallback_addresses, "fallback_regex"
            except Exception as fallback_e:
                logger.error(f"Fallback deterministic extractor failed: {fallback_e}")
                # Return empty list and fallback path if both failed completely
                return [], "fallback_regex"
