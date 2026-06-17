import re
import requests
from fastapi import HTTPException
from app.config import SMARTY_AUTH_ID, SMARTY_AUTH_TOKEN
from app.models.address import Address, AddressComponents

class SmartyAPIClient:
    @staticmethod
    def build_request(text: str) -> dict:
        """
        Load auth-id and auth-token from environment variables (via config).
        Return a dict: { "params": {...}, "data": text }
        """
        return {
            "params": {
                "auth-id": SMARTY_AUTH_ID,
                "auth-token": SMARTY_AUTH_TOKEN
            },
            "data": text
        }

    @staticmethod
    def send_request(request_data: dict) -> requests.Response:
        """
        Make HTTP POST to Smarty API endpoint using requests library.
        Set timeout (e.g., 10 seconds).
        On timeout/connection failure, raise HTTPException(503):
          "Unable to connect to API. Please try again later."
        """
        url = "https://us-extract.api.smarty.com/"
        try:
            response = requests.post(
                url,
                params=request_data.get("params"),
                data=request_data.get("data"),
                headers={"Content-Type": "text/plain"},
                timeout=10
            )
        except (requests.Timeout, requests.ConnectionError):
            raise HTTPException(
                status_code=503,
                detail="Unable to connect to API. Please try again later."
            )

        if response.status_code != 200:
            SmartyAPIClient.handle_error(response.status_code, response.text)

        return response

    @staticmethod
    def parse_response(raw_response: requests.Response) -> list:
        """
        Extract "addresses" array from JSON response.
        For each address, parse input_text and components.
        Return list of Address objects.
        If JSON parsing fails, raise HTTPException(500):
          "Unexpected response from API. Please try again."
        """
        try:
            data = raw_response.json()
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Unexpected response from API. Please try again."
            )

        if not isinstance(data, dict) or "addresses" not in data:
            raise HTTPException(
                status_code=500,
                detail="Unexpected response from API. Please try again."
            )

        addresses_list = data.get("addresses")
        if not isinstance(addresses_list, list):
            raise HTTPException(
                status_code=500,
                detail="Unexpected response from API. Please try again."
            )

        parsed_addresses = []
        for item in addresses_list:
            input_text = item.get("text") or ""
            api_outputs = item.get("api_output") or []
            
            primary_number = ""
            street_name = ""
            street_suffix = ""
            city_name = ""
            state_abbreviation = ""
            zipcode = ""

            if api_outputs and isinstance(api_outputs, list):
                # Grab components from the first verified address components dict
                components = api_outputs[0].get("components") or {}
                primary_number = components.get("primary_number") or ""
                street_name = components.get("street_name") or ""
                street_suffix = components.get("street_suffix") or ""
                city_name = components.get("city_name") or ""
                state_abbreviation = components.get("state_abbreviation") or ""
                zipcode = components.get("zipcode") or ""
            else:
                # Regex fallback for unverified addresses
                fallback = SmartyAPIClient._parse_unverified_address(input_text)
                if fallback:
                    primary_number = ""
                    street_name = fallback["street"]
                    street_suffix = ""
                    city_name = fallback["city"]
                    state_abbreviation = fallback["state"]
                    zipcode = fallback["zip"]

            addr_obj = Address(
                input_text=input_text,
                components=AddressComponents(
                    primary_number=primary_number,
                    street_name=street_name,
                    street_suffix=street_suffix,
                    city_name=city_name,
                    state_abbreviation=state_abbreviation,
                    zipcode=zipcode
                )
            )
            parsed_addresses.append(addr_obj)

        return parsed_addresses

    @staticmethod
    def _parse_unverified_address(text: str) -> dict:
        """
        Extract basic address fields from unverified raw text, mapping full state names
        to 2-letter codes and splitting street/city on street suffixes or unit designators.
        """
        US_STATES = {
            "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
            "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
            "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
            "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
            "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
            "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
            "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
            "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
            "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
            "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
            "district of columbia": "DC"
        }

        # Normalize spaces
        clean_text = re.sub(r'\s+', ' ', text).strip()
        
        # Strip phone numbers
        phone_pattern = r'(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
        clean_text = re.sub(phone_pattern, '', clean_text)
        
        # Strip common prefixes
        clean_text = re.sub(r'(?i)\b(?:address|phone|tel|mobile|cell|office):\s*', '', clean_text)
        
        # Clean leading/trailing spaces and commas
        clean_text = re.sub(r'^[\s,]+|[\s,]+$', '', clean_text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        
        # Match ZIP code at the end
        zip_match = re.search(r'\b(\d{5}(?:-\d{4})?)$', clean_text)
        if not zip_match:
            return None
            
        zipcode = zip_match.group(1)
        # Text before ZIP code
        remaining_text = clean_text[:zip_match.start()].strip()
        # Clean commas at the end
        remaining_text = re.sub(r'[\s,]+$', '', remaining_text)
        
        words = remaining_text.split()
        if not words:
            return None
            
        state_name = ""
        state_abbr = ""
        
        # Try last two words (for New York, New Jersey, etc.)
        if len(words) >= 2:
            last_two = " ".join(words[-2:]).lower()
            if last_two in US_STATES:
                state_name = " ".join(words[-2:])
                state_abbr = US_STATES[last_two]
                remaining_text = " ".join(words[:-2]).strip()
                
        # If not matched, try the last word
        if not state_name:
            last_one = words[-1].lower()
            if len(last_one) == 2 and last_one.upper() in US_STATES.values():
                state_name = words[-1]
                state_abbr = last_one.upper()
                remaining_text = " ".join(words[:-1]).strip()
            elif last_one in US_STATES:
                state_name = words[-1]
                state_abbr = US_STATES[last_one]
                remaining_text = " ".join(words[:-1]).strip()
            else:
                state_name = words[-1]
                state_abbr = state_name.upper()
                remaining_text = " ".join(words[:-1]).strip()
                
        # Clean trailing commas
        remaining_text = re.sub(r'[\s,]+$', '', remaining_text)
        
        # Split remaining_text into Street and City
        if ',' in remaining_text:
            parts = remaining_text.split(",")
            street = ",".join(parts[:-1]).strip()
            city = parts[-1].strip()
        else:
            # Search for street suffix or unit designators
            split_idx = -1
            unit_pats = [
                r'\b(apt|apartment|suite|ste|room|rm|floor|fl|dept|department|box|po box|p.o. box)\b\s*#?\s*\w+',
                r'\b(po box|p.o. box|box)\b\s*\d+'
            ]
            suffix_pats = [
                r'\b(road|rd|lane|ln|street|st|avenue|ave|drive|dr|trail|way|court|ct|plaza|pl|boulevard|blvd|highway|hwy)\b'
            ]
            
            for pat in unit_pats:
                for m in re.finditer(pat, remaining_text, re.I):
                    if m.end() > split_idx:
                        split_idx = m.end()
                        
            if split_idx == -1:
                for pat in suffix_pats:
                    for m in re.finditer(pat, remaining_text, re.I):
                        if m.end() > split_idx:
                            split_idx = m.end()
                            
            if split_idx != -1:
                street = remaining_text[:split_idx].strip()
                city = remaining_text[split_idx:].strip()
                if not city:
                    words_rem = remaining_text.split()
                    if len(words_rem) >= 2:
                        street = " ".join(words_rem[:-1]).strip()
                        city = words_rem[-1].strip()
            else:
                words_rem = remaining_text.split()
                if len(words_rem) >= 2:
                    street = " ".join(words_rem[:-1]).strip()
                    city = words_rem[-1].strip()
                else:
                    street = remaining_text
                    city = ""
                    
        # Clean leading/trailing non-alphanumeric characters from street
        street = re.sub(r'^[^a-zA-Z0-9]+', '', street).strip()
        return {'street': street, 'city': city, 'state': state_abbr, 'zip': zipcode}

    @staticmethod
    def handle_error(status_code: int, error_body: str) -> None:
        """
        Map status codes to specific user-friendly HTTPExceptions.
        """
        if status_code == 401:
            raise HTTPException(
                status_code=401,
                detail="Invalid API credentials. Please contact administrator."
            )
        elif status_code == 402:
            raise HTTPException(
                status_code=402,
                detail="API usage limit reached. Please try again later."
            )
        elif status_code == 500:
            raise HTTPException(
                status_code=500,
                detail="Something went wrong on server. Please try again later."
            )
        elif status_code in [400, 413]:
            raise HTTPException(
                status_code=status_code,
                detail="The file is too large to process. Please upload a smaller document."
            )
        else:
            raise HTTPException(
                status_code=status_code,
                detail="Unexpected error. Please try again."
            )
