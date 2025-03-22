from flask import Flask, request, jsonify
import requests
import datetime
import os

app = Flask(__name__)

SHOP_NAME = os.getenv("SHOPIFY_SHOP_NAME")
ADMIN_API_TOKEN = os.getenv("SHOPIFY_ADMIN_API_TOKEN")
PRICE_RULE_ID = os.getenv("SHOPIFY_PRICE_RULE_ID")

SHOPIFY_API_URL = f"https://{SHOP_NAME}.myshopify.com/admin/api/2023-10"
CUSTOMER_METAFIELDS_URL = lambda cid: f"{SHOPIFY_API_URL}/customers/{cid}/metafields.json"
METAFIELD_URL = lambda metafield_id: f"{SHOPIFY_API_URL}/metafields/{metafield_id}.json"

DOG_DOLLARS_NAMESPACE = "loyalty"
DOG_DOLLARS_KEY = "dog_dollars"
LAST_DISCOUNT_CODE_KEY = "last_discount_code"
USED_CODES_KEY = "used_discount_codes"

headers = {
    "X-Shopify-Access-Token": ADMIN_API_TOKEN,
    "Content-Type": "application/json"
}

def get_customer_numeric_id(customer_gid):
    return str(customer_gid).split("/")[-1]

def get_order_numeric_id(order_gid):
    return str(order_gid).split("/")[-1]

def get_metafields(customer_id):
    response = requests.get(CUSTOMER_METAFIELDS_URL(customer_id), headers=headers)
    if response.status_code == 200:
        return response.json().get("metafields", [])
    return []

def get_metafield_by_key(customer_id, key):
    metafields = get_metafields(customer_id)
    for metafield in metafields:
        if metafield["namespace"] == DOG_DOLLARS_NAMESPACE and metafield["key"] == key:
            return metafield
    return None

def update_dog_dollars(customer_id, new_balance, metafield_id=None):
    data = {
        "metafield": {
            "namespace": DOG_DOLLARS_NAMESPACE,
            "key": DOG_DOLLARS_KEY,
            "type": "number_integer",
            "value": str(new_balance)
        }
    }
    url = METAFIELD_URL(metafield_id) if metafield_id else CUSTOMER_METAFIELDS_URL(customer_id)
    method = requests.put if metafield_id else requests.post
    response = method(url, headers=headers, json=data)
    return response.status_code in [200, 201]

def create_multiline_metafield(customer_id, key, value):
    data = {
        "metafield": {
            "namespace": DOG_DOLLARS_NAMESPACE,
            "key": key,
            "type": "multi_line_text_field",
            "value": value
        }
    }
    response = requests.post(CUSTOMER_METAFIELDS_URL(customer_id), headers=headers, json=data)
    return response.status_code == 201

def update_multiline_metafield(metafield_id, value):
    data = {
        "metafield": {
            "id": metafield_id,
            "value": value,
            "type": "multi_line_text_field"
        }
    }
    response = requests.put(METAFIELD_URL(metafield_id), headers=headers, json=data)
    return response.status_code == 200

def append_code_to_metafield(customer_id, code):
    existing = get_metafield_by_key(customer_id, LAST_DISCOUNT_CODE_KEY)
    timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    entry = f"{code} | Created on {timestamp}"
    if existing:
        combined = existing["value"].strip() + "\n" + entry
        update_multiline_metafield(existing["id"], combined)
    else:
        create_multiline_metafield(customer_id, LAST_DISCOUNT_CODE_KEY, entry)

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
    return unique_code if response.status_code == 201 else None

@app.route("/generate-code", methods=["POST"])
def generate_code():
    data = request.get_json()
    raw_customer_id = data.get("customer_id")
    raw_order_id = data.get("order_id")
    earned_dog_dollars = int(data.get("dog_dollars", 0))

    customer_id = get_customer_numeric_id(raw_customer_id)
    order_id = get_order_numeric_id(raw_order_id)

    balance_field = get_metafield_by_key(customer_id, DOG_DOLLARS_KEY)
    current_balance = int(balance_field["value"]) if balance_field else 0
    new_balance = current_balance + earned_dog_dollars
    update_dog_dollars(customer_id, new_balance, balance_field["id"] if balance_field else None)

    codes_issued = []
    while new_balance >= 125:
        code = create_discount_code(customer_id, order_id)
        if code:
            codes_issued.append(code)
            new_balance -= 125
            update_dog_dollars(customer_id, new_balance)
            append_code_to_metafield(customer_id, code)
        else:
            break

    return jsonify({"success": True, "dog_dollars": new_balance, "codes": codes_issued})

@app.route("/mark-used", methods=["POST"])
def mark_code_as_used():
    data = request.get_json()
    raw_customer_id = data.get("customer_id")
    used_code = data.get("code")

    if not used_code:
        return jsonify({"success": False, "error": "Missing discount code"}), 400

    customer_id = get_customer_numeric_id(raw_customer_id)
    active_metafield = get_metafield_by_key(customer_id, LAST_DISCOUNT_CODE_KEY)
    used_metafield = get_metafield_by_key(customer_id, USED_CODES_KEY)

    active_codes = active_metafield["value"].strip().split("\n") if active_metafield else []
    used_codes = used_metafield["value"].strip().split("\n") if used_metafield else []

    updated_active = [c for c in active_codes if not c.startswith(used_code)]
    timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    updated_used = used_codes + [f"{used_code} | Used on {timestamp}"]

    if active_metafield:
        update_multiline_metafield(active_metafield["id"], "\n".join(updated_active))
    if used_metafield:
        update_multiline_metafield(used_metafield["id"], "\n".join(updated_used))
    else:
        create_multiline_metafield(customer_id, USED_CODES_KEY, "\n".join(updated_used))

    return jsonify({"success": True, "message": "Discount code marked as used"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
