from faker import Faker
import random
import csv
from rapidfuzz.distance import JaroWinkler

fake = Faker()

MASTER_ROWS = 10000
INCOMING_ROWS = 3000

master_file = "master_data.csv"
incoming_file = "incoming_data.csv"

# -----------------------------------
# Helper functions
# -----------------------------------

def mutate_name(name):
    variants = [
        name.replace("PT", "PT."),
        name.upper(),
        name.lower(),
        name.replace(" ", ""),
        name.replace("a", "o", 1),
        name + " Tbk",
    ]
    return random.choice(variants)

def random_status():
    return random.choice([
        "SUCCESS",
        "FAILED",
        "PENDING",
        "REFUNDED"
    ])

# -----------------------------------
# Generate MASTER DATA
# -----------------------------------

master_rows = []

for i in range(1, MASTER_ROWS + 1):
    merchant_name = fake.company()

    row = {
        "transaction_id": i,
        "customer_id": random.randint(100000, 999999),
        "customer_name": fake.name(),
        "merchant_name": merchant_name,
        "merchant_category": random.choice([
            "Retail",
            "Food",
            "Tech",
            "Health",
            "Fashion"
        ]),
        "email": fake.email(),
        "phone": fake.phone_number(),
        "city": fake.city(),
        "country": fake.country(),
        "amount": round(random.uniform(10, 5000), 2),
        "currency": "IDR",
        "status": random_status(),
        "transaction_timestamp": fake.iso8601(),
    }

    master_rows.append(row)

master_columns = [
    "transaction_id",
    "customer_id",
    "customer_name",
    "merchant_name",
    "merchant_category",
    "email",
    "phone",
    "city",
    "country",
    "amount",
    "currency",
    "status",
    "transaction_timestamp"
]

with open(master_file, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=master_columns)
    writer.writeheader()
    writer.writerows(master_rows)

print(f"Generated {master_file}")

# -----------------------------------
# Generate INCOMING DATA
# Fewer columns + messy values
# -----------------------------------

incoming_rows = []

sampled_master = random.sample(master_rows, INCOMING_ROWS)

for row in sampled_master:

    merchant_variant = mutate_name(row["merchant_name"])

    incoming_row = {
        "transaction_id": row["transaction_id"],
        "customer_name": row["customer_name"],
        "merchant_name": merchant_variant,
        "amount": row["amount"] + random.uniform(-5, 5),
        "status": row["status"],
    }

    # Random corruption
    if random.random() < 0.05:
        incoming_row["customer_name"] = None

    if random.random() < 0.03:
        incoming_row["amount"] = None

    incoming_rows.append(incoming_row)

incoming_columns = [
    "transaction_id",
    "customer_name",
    "merchant_name",
    "amount",
    "status"
]

with open(incoming_file, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=incoming_columns)
    writer.writeheader()
    writer.writerows(incoming_rows)

print(f"Generated {incoming_file}")

# -----------------------------------
# Example similarity check
# -----------------------------------

# sample_master = master_rows[0]["merchant_name"]
# sample_incoming = mutate_name(sample_master)

# score = JaroWinkler.similarity(
#     sample_master,
#     sample_incoming
# )

# print("\nExample fuzzy matching:")
# print("Master   :", sample_master)
# print("Incoming :", sample_incoming)
# print("JW Score :", round(score, 4))