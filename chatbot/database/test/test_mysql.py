from dotenv import load_dotenv

from chatbot.database.mysql import MySQLDatabase

load_dotenv()

db = MySQLDatabase()

def test_get_table_names():
    result = db.get_table_names()
    print(result)
    
def test_get_table_schema():
    result = db.get_table_schema("users")
    print(result)

def test_execute_query_select():
    result = db.execute("SELECT name, tax_id FROM users LIMIT 2;")
    print(result)
    
def test_execute_query_join():
    query = """
    SELECT
    i.invoice_number,
    i.issue_date,
    c.name AS client_name,
    s.name AS seller_name,
    id.description,
    id.quantity,
    id.net_price,
    id.gross_worth AS item_gross_worth
    FROM
        invoices AS i
    JOIN
        users AS c ON i.client_id = c.id
    JOIN
        users AS s ON i.seller_id = s.id
    JOIN
        invoice_detail AS id ON i.id = id.invoice_id
    LIMIT 5;
    """
    result = db.execute(query)
    print(result)

