from flask import Flask, request, jsonify
import requests
import datetime
import os

app = Flask(__name__)

# Environment variables for security
SHOP_NAME = os.environ.get("SHOP_NAME")  # e.g., 'your-store-name'
ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN")
PRICE_RULE_ID = os.environ.get("PRICE_RULE_ID")  # e.g., the ID for your 10% off rule

# Shopify API base URL
SHOPIFY_API_URL = f"https://{SHOP_NAME}.myshopify.com/admin/api/2023-10"
CUSTOMER_METAFIELDS_URL = lambda cid: f"{SHOPIFY_API_URL}/customers/{cid}/metafields.json"

# Metafield keys
DOG_DOLLARS_NAMESPACE = "loyalty"
DOG_DOLLARS_KEY = "dog_dollars"
DISCOUNT_CODE_KEY = "last_discount_code"

headers = {
    "X-Shopify-Access-Token": ADMIN_API_TOKEN,
    "Content-Type": "application/json"
}

def get_customer_numeric_id(customer_gid):
    return customer_gid.split("/")[-1] if isinstance(customer_gid, str) else str(customer_gid)

def get_order_numeric_id(order_gid):
    return order_gid.split("/")[-1] if isinstance(order_gid, str) else str(order_gid)

def get_metafields(customer_id):
    response = requests.get(CUSTOMER_METAFIELDS_URL(customer_id), headers=headers)
    if response.status_code == 200:
        return response.json().get("metafields", [])
    return []

def get_metafield_value_and_id(metafields, key):
    for metafield in metafields:
        if metafield["namespace"] == DOG_DOLLARS_NAMESPACE and metafield["key"] == key:
            return metafield["value"], metafield["id"]
    return None, None

def update_metafield(customer_id, key, value, metafield_type, metafield_id=None):
    data = {
        "metafield": {
            "namespace": DOG_DOLLARS_NAMESPACE,
            "key": key,
            "type": metafield_type,
            "value": value
        }
    }
    if metafield_id:
        url = f"{SHOPIFY_API_URL}/metafields/{metafield_id}.json"
        response = requests.put(url, headers=headers, json=data)
    else:
        url = CUSTOMER_METAFIELDS_URL(customer_id)
        response = requests.post(url, headers=headers, json=data)
    return response.status_code in [200, 201]

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
    current_balance_str, balance_id = get_metafield_value_and_id(metafields, DOG_DOLLARS_KEY)
    current_balance = int(current_balance_str) if current_balance_str else 0
    new_balance = current_balance + earned_dog_dollars

    update_metafield(customer_id, DOG_DOLLARS_KEY, str(new_balance), "number_integer", balance_id)

    existing_codes_str, codes_id = get_metafield_value_and_id(metafields, DISCOUNT_CODE_KEY)
    existing_codes = existing_codes_str.strip().split("\n") if existing_codes_str else []

    new_codes = []
    while new_balance >= 125:
        code = create_discount_code(customer_id, order_id)
        if code:
            new_codes.append(code)
            new_balance -= 125
        else:
            break

    if new_codes:
        update_metafield(customer_id, DOG_DOLLARS_KEY, str(new_balance), "number_integer")
        all_codes = "\n".join(existing_codes + new_codes)
        update_metafield(customer_id, DISCOUNT_CODE_KEY, all_codes, "multi_line_text_field", codes_id)

    return jsonify({
        "success": True,
        "dog_dollars": new_balance,
        "codes": existing_codes + new_codes
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
