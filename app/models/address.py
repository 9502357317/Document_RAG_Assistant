from pydantic import BaseModel

class AddressComponents(BaseModel):
    primary_number: str
    street_name: str
    street_suffix: str
    city_name: str
    state_abbreviation: str
    zipcode: str

class Address(BaseModel):
    input_text: str
    components: AddressComponents
