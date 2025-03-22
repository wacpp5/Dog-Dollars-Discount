from flask import Flask, request, jsonify
import requests
import datetime
import os
import json

app = Flask(__name__)

# Use environment variables for security
SHOP_NAME = os.environ.get("SHOP_NAME")
ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN")
PRICE_RULE_ID = os.environ.get("PRICE_RULE_ID")

# Shopify API endpoints
SHOPIFY_API_URL = f"https://{SHOP_NAME}.myshopify.com/admin/api/2023-10"
CUSTOMER_METAFIELDS_URL = lambda cid: f"{SHOPIFY_API_URL}/customers/{cid}/metafields.json"

# Metafield namespace/key
DOG_DOLLARS_NAMESPACE = "loyalty"
DOG_DOLLARS_KEY = "dog_dollars"
DISCOUNT_CODE_KEY = "discount_codes"

headers = {
    "X-Shopify-Access-Token": ADMIN_API_TOKEN,
    "Content-Type": "application/json"
}

def get_customer_numeric_id(customer_gid):
    if isinstance(customer_gid, str) and "gid://" in customer_gid:
        return customer_gid.split("/")[-1]
    return str(customer_gid)

def get_order_numeric_id(order_gid):
    if isinstance(order_gid, str) and "gid://" in order_gid:
        return order_gid.split("/")[-1]
    return str(order_gid)

def get_metafields(customer_id):
    response = requests.get(CUSTOMER_METAFIELDS_URL(customer_id), headers=headers)
    if response.status_code == 200:
        return response.json().get("metafields", [])
    return []

def get_dog_dollars_balance(metafields):
    for metafield in metafields:
        if metafield["namespace"] == DOG_DOLLARS_NAMESPACE and metafield["key"] == DOG_DOLLARS_KEY:
            return int(metafield["value"]), metafield["id"]
    return 0, None

def get_discount_codes(metafields):
    for metafield in metafields:
        if metafield["namespace"] == DOG_DOLLARS_NAMESPACE and metafield["key"] == DISCOUNT_CODE_KEY:
            return metafield.get("value", "").splitlines(), metafield["id"]
    return [], None

def update_dog_dollars(customer_id, new_balance, metafield_id=None):
    data = {
        "metafield": {
            "namespace": DOG_DOLLARS_NAMESPACE,
            "key": DOG_DOLLARS_KEY,
            "type": "number_integer",
            "value": str(new_balance)
        }
    }
    if metafield_id:
        url = f"{SHOPIFY_API_URL}/metafields/{metafield_id}.json"
        return requests.put(url, headers=headers, json=data)
    else:
        url = CUSTOMER_METAFIELDS_URL(customer_id)
        return requests.post(url, headers=headers, json=data)

def save_discount_code_to_customer(customer_id, new_code):
    metafields = get_metafields(customer_id)
    existing_codes, metafield_id = get_discount_codes(metafields)

    if new_code not in existing_codes:
        existing_codes.append(new_code)

    formatted_value = "\n".join(existing_codes)

    data = {
        "metafield": {
            "namespace": DOG_DOLLARS_NAMESPACE,
            "key": DISCOUNT_CODE_KEY,
            "type": "multi_line_text_field",
            "value": formatted_value
        }
    }

    if metafield_id:
        url = f"{SHOPIFY_API_URL}/metafields/{metafield_id}.json"
        requests.put(url, headers=headers, json=data)
    else:
        url = CUSTOMER_METAFIELDS_URL(customer_id)
        requests.post(url, headers=headers, json=data)

def create_discount_code(customer_id, order_id):
    unique_code = f"DOG-{customer_id}-{order_id}"
    today = datetime.datetime.utcnow()
    ends_at = (today + datetime.timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    payload = {
        "discount_code": {
            "code": unique_code,
            "usage_limit": 1,
            "applies_once_per_customer": True,
            "starts_at": today.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ends_at": ends_at,
            "customer_selection": "all",
            "value_type": "percentage",
            "value": "10.0"
        }
    }
    url = f"{SHOPIFY_API_URL}/price_rules/{PRICE_RULE_ID}/discount_codes.json"
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 201:
        return unique_code
    return None

@app.route("/generate-code", methods=["POST"])
def generate_code():
    data = request.get_json()
    raw_customer_id = data.get("customer_id")
    raw_order_id = data.get("order_id")
    earned_dog_dollars = int(data.get("dog_dollars", 0))

    customer_id = get_customer_numeric_id(raw_customer_id)
    order_id = get_order_numeric_id(raw_order_id)

    metafields = get_metafields(customer_id)
    current_balance, balance_metafield_id = get_dog_dollars_balance(metafields)
    new_balance = current_balance + earned_dog_dollars

    update_dog_dollars(customer_id, new_balance, balance_metafield_id)

    issued_codes = []

    while new_balance >= 125:
        code = create_discount_code(customer_id, order_id)
        if code:
            save_discount_code_to_customer(customer_id, code)
            issued_codes.append(code)
            new_balance -= 125
            update_dog_dollars(customer_id, new_balance)
        else:
            return jsonify({
                "success": False,
                "dog_dollars": new_balance,
                "error": "Failed to create discount code",
                "codes": issued_codes
            })

    return jsonify({
        "success": True,
        "dog_dollars": new_balance,
        "codes": issued_codes
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
