from flask import Flask, request, jsonify
import requests
import datetime
import os

app = Flask(__name__)

SHOP_NAME = os.getenv("SHOP_NAME")
ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN")
PRICE_RULE_ID = os.getenv("PRICE_RULE_ID")

SHOPIFY_API_URL = f"https://{SHOP_NAME}.myshopify.com/admin/api/2023-10"
CUSTOMER_METAFIELDS_URL = lambda cid: f"{SHOPIFY_API_URL}/customers/{cid}/metafields.json"

DOG_DOLLARS_NAMESPACE = "loyalty"
DOG_DOLLARS_KEY = "dog_dollars"
DISCOUNT_CODE_KEY = "last_discount_code"
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

def get_dog_dollars_balance(metafields):
    for metafield in metafields:
        if metafield["namespace"] == DOG_DOLLARS_NAMESPACE and metafield["key"] == DOG_DOLLARS_KEY:
            return int(metafield["value"]), metafield["id"]
    return 0, None

def get_discount_codes(metafields):
    for metafield in metafields:
        if metafield["namespace"] == DOG_DOLLARS_NAMESPACE and metafield["key"] == DISCOUNT_CODE_KEY:
            return metafield["value"], metafield["id"]
    return "", None

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
        return requests.put(url, headers=headers, json=data).status_code in [200, 201]
    else:
        url = CUSTOMER_METAFIELDS_URL(customer_id)
        return requests.post(url, headers=headers, json=data).status_code in [200, 201]

def save_discount_codes_to_customer(customer_id, codes, metafield_id=None):
    value = "\n".join(codes)
    data = {
        "metafield": {
            "namespace": DOG_DOLLARS_NAMESPACE,
            "key": DISCOUNT_CODE_KEY,
            "type": "multi_line_text_field",
            "value": value
        }
    }
    if metafield_id:
        url = f"{SHOPIFY_API_URL}/metafields/{metafield_id}.json"
        return requests.put(url, headers=headers, json=data).status_code in [200, 201]
    else:
        url = CUSTOMER_METAFIELDS_URL(customer_id)
        return requests.post(url, headers=headers, json=data).status_code in [200, 201]

def save_used_code(customer_id, code):
    metafields = get_metafields(customer_id)
    existing = ""
    metafield_id = None
    for m in metafields:
        if m["namespace"] == DOG_DOLLARS_NAMESPACE and m["key"] == USED_CODES_KEY:
            existing = m["value"]
            metafield_id = m["id"]
            break
    updated = existing + "\n" + code if existing else code
    data = {
        "metafield": {
            "namespace": DOG_DOLLARS_NAMESPACE,
            "key": USED_CODES_KEY,
            "type": "multi_line_text_field",
            "value": updated
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
    return unique_code if response.status_code == 201 else None

@app.route("/generate-code", methods=["POST"])
def generate_code():
    data = request.get_json()
    raw_customer_id = data.get("customer_id")
    raw_order_id = data.get("order_id")
    earned_dog_dollars = int(data.get("dog_dollars", 0))

    customer_id = get_customer_numeric_id(raw_customer_id)
    order_id = get_order_numeric_id(raw_order_id)

    metafields = get_metafields(customer_id)
    current_balance, dog_id = get_dog_dollars_balance(metafields)
    codes_value, code_id = get_discount_codes(metafields)
    codes = codes_value.split("\n") if codes_value else []

    new_balance = current_balance + earned_dog_dollars
    update_dog_dollars(customer_id, new_balance, dog_id)

    if new_balance >= 125:
        code = create_discount_code(customer_id, order_id)
        if code:
            final_balance = new_balance - 125
            update_dog_dollars(customer_id, final_balance, dog_id)
            codes.append(f"{code}|{datetime.datetime.utcnow().isoformat()}|unused")
            save_discount_codes_to_customer(customer_id, codes, code_id)
            return jsonify({"success": True, "code": code, "dog_dollars": final_balance, "codes": codes})
        else:
            return jsonify({"success": False, "error": "Failed to create discount code", "dog_dollars": new_balance, "codes": codes})

    return jsonify({"success": True, "dog_dollars": new_balance, "codes": codes})

@app.route("/mark-used", methods=["POST"])
def mark_code_as_used():
    data = request.get_json()
    customer_id = str(data.get("customer_id"))
    used_code = data.get("used_code")

    if not used_code:
        return jsonify({"success": False, "error": "Missing discount code"}), 400

    metafields = get_metafields(customer_id)
    codes_value, code_id = get_discount_codes(metafields)
    codes = codes_value.split("\n") if codes_value else []

    updated_active = []
    moved_to_used = None

    for c in codes:
        if c.startswith(used_code):
            moved_to_used = c.replace("|unused", "|used")
        else:
            updated_active.append(c)

    if moved_to_used:
        save_discount_codes_to_customer(customer_id, updated_active, code_id)
        save_used_code(customer_id, moved_to_used)
        return jsonify({"success": True, "message": "Discount code marked as used"})
    else:
        return jsonify({"success": False, "error": "Code not found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
