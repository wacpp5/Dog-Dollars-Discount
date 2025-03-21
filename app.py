from flask import Flask, request, jsonify
import requests
import datetime
import os

app = Flask(__name__)

# Load from environment variables
SHOP_NAME = os.environ.get("SHOP_NAME")
ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN")
PRICE_RULE_ID = os.environ.get("PRICE_RULE_ID")

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

    url = f"https://{SHOP_NAME}.myshopify.com/admin/api/2023-10/price_rules/{PRICE_RULE_ID}/discount_codes.json"
    headers = {
        "X-Shopify-Access-Token": ADMIN_API_TOKEN,
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 201:
        return unique_code
    else:
        print("Error:", response.text)
        return None

def save_discount_to_metafield(customer_id, discount_code):
    metafield_payload = {
        "metafield": {
            "namespace": "dog_dollars",
            "key": "discount_code",
            "value": discount_code,
            "type": "single_line_text_field"
        }
    }

    url = f"https://{SHOP_NAME}/admin/api/2023-10/customers/{customer_id}/metafields.json"

    headers = {
        "X-Shopify-Access-Token": ADMIN_API_TOKEN,
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=metafield_payload, headers=headers)

    if response.status_code == 201:
        print("Metafield saved!")
    else:
        print("Failed to save metafield:", response.text)




@app.route("/generate-code", methods=["POST"])
def generate_code():
    data = request.get_json()
    customer_id = data.get("customer_id")
    order_id = data.get("order_id")
    dog_dollars = int(data.get("dog_dollars", 0))

    if dog_dollars >= 125:
        code = create_discount_code(customer_id, order_id)
        return jsonify({"success": True, "code": code})
    else:
        return jsonify({"success": False, "message": "Not enough Dog Dollars"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
