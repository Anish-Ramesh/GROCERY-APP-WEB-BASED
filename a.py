import mysql.connector
from mysql.connector import Error

# Database credentials
DB_HOST = "bpo977qofmifrmo5ciff-mysql.services.clever-cloud.com"
DB_USER = "uikso7x7mfnszsh0"
DB_PASSWORD = "tp2Zws86wsTBZrzVyGrU"  # ← Change later for security
DB_NAME = "bpo977qofmifrmo5ciff"


# ------------------- DATABASE CONNECTION ------------------- #
def connect_db():
    """Create and return database connection."""
    try:
        connection = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=3306,
            ssl_disabled=True  # set True if SSL issues happen
        )
        if connection.is_connected():
            print("Connected to MySQL database")
            return connection
        else:
            print("Connection failed")
            return None

    except Error as e:
        print("Error:", e)
        return None


# ---------------------- CREATE TABLES ---------------------- #
def create_tables(connection):
    """Create necessary tables."""
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id VARCHAR(100),
            product_id INT,
            quantity INT,
            added_at DATETIME
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS e (
            id INT PRIMARY KEY,
            FID TEXT,
            LID TEXT,
            s DECIMAL(10, 2),
            did INT
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_catalog (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100),
            description TEXT,
            category VARCHAR(50),
            price DECIMAL(10, 2),
            stock INT,
            is_active TINYINT(1)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id VARCHAR(100),
            order_details TEXT,
            placed_at DATETIME
        );
    """)

    connection.commit()
    print("Tables created successfully.")


# ------------------- INSERT SAMPLE PRODUCTS ------------------- #
def insert_products(connection):
    """Insert sample products into product_catalog."""
    cursor = connection.cursor()
    products = [
        (6, "Nestlé Maggi 70g", "Instant noodles pack", "Snacks", 14.00, 74, 1),
        (7, "Britannia Bread", "Fresh white sandwich bread", "Bakery", 45.00, 60, 1),
        (8, "Surf Excel 1kg", "Detergent powder for washing", "Cleaning", 120.00, 40, 1),
        (9, "Colgate Toothpaste", "Strong teeth & fresh breath", "Personal", 55.00, 90, 1),
        (10, "Dettol Handwash 200ml", "Liquid hand soap refill", "Cleaning", 75.00, 70, 1),
    ]

    cursor.executemany("""
        INSERT IGNORE INTO product_catalog
        (id, name, description, category, price, stock, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """, products)

    connection.commit()
    print("Sample products inserted.")


# ------------------------- MAIN SCRIPT ------------------------- #
def main():
    conn = connect_db()
    if conn:
        create_tables(conn)
        insert_products(conn)
        conn.close()
        print("Connection closed.")


# -------------------- RUN THE SCRIPT -------------------- #
if __name__ == "__main__":
    main()
