from flask import Flask, request, jsonify
import requests
import datetime
import os

app = Flask(__name__)

# Load sensitive values from environment variables
SHOP_NAME = os.environ.get("SHOP_NAME")
ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN")
PRICE_RULE_ID = os.environ.get("PRICE_RULE_ID")

# Shopify API endpoints
SHOPIFY_API_URL = f"https://{SHOP_NAME}.myshopify.com/admin/api/2023-10"
CUSTOMER_METAFIELDS_URL = lambda cid: f"{SHOPIFY_API_URL}/customers/{cid}/metafields.json"

# Metafield namespace/key
DOG_DOLLARS_NAMESPACE = "loyalty"
DOG_DOLLARS_KEY = "dog_dollars"
DISCOUNT_CODE_KEY = "last_discount_code"

headers = {
    "X-Shopify-Access-Token": ADMIN_API_TOKEN,
    "Content-Type": "application/json"
}

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
        response = requests.put(url, headers=headers, json=data)
    else:
        url = CUSTOMER_METAFIELDS_URL(customer_id)
        response = requests.post(url, headers=headers, json=data)
    return response.status_code in [200, 201]

def save_discount_code_to_customer(customer_id, code):
    data = {
        "metafield": {
            "namespace": DOG_DOLLARS_NAMESPACE,
            "key": DISCOUNT_CODE_KEY,
            "type": "single_line_text_field",
            "value": code
        }
    }
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

customer_id = str(raw_customer_id)
order_id = str(raw_order_id)


    # Fetch existing dog dollars
    metafields = get_metafields(customer_id)
    current_balance, metafield_id = get_dog_dollars_balance(metafields)
    new_balance = current_balance + earned_dog_dollars

    # Update dog dollars
    update_dog_dollars(customer_id, new_balance, metafield_id)

    # Create discount if eligible
    if new_balance >= 125:
        code = create_discount_code(customer_id, order_id)
        if code:
            # Subtract 125 and update
            final_balance = new_balance - 125
            update_dog_dollars(customer_id, final_balance)
            save_discount_code_to_customer(customer_id, code)
            return jsonify({"success": True, "code": code, "dog_dollars": final_balance})
        else:
            # Could not create code, still return updated balance
            return jsonify({"success": False, "error": "Failed to create discount code", "dog_dollars": new_balance})

    return jsonify({"success": True, "dog_dollars": new_balance})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
