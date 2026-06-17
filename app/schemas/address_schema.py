from pydantic import BaseModel
from typing import List

class Address(BaseModel):
    street: str
    city: str
    state: str
    zip: str

class AddressList(BaseModel):
    addresses: List[Address]