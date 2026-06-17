from app.schemas.address_schema import AddressList

sample_json = """
{
    "addresses": [
        {
            "street": "123 Main St",
            "city": "Boston",
            "state": "MA",
            "zip": "02110"
        }
    ]
}
"""

if __name__ == "__main__":
    result = AddressList.model_validate_json(sample_json)
    print(result)