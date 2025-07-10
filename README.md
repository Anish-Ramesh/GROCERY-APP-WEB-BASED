# Personal Grocery Chatbot

A chat-based grocery assistant with Google login, product catalog, cart, order placement, and admin dashboard (with Excel upload and schema management).

---

## SQL Schema

```sql
-- Product Catalog
CREATE TABLE product_catalog (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    category VARCHAR(50),
    price DECIMAL(10,2),
    stock INT,
    is_active TINYINT(1) DEFAULT 1
);

-- Cart
CREATE TABLE cart (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES product_catalog(id)
);

-- Orders
CREATE TABLE orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    order_details TEXT NOT NULL,
    placed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## Setup Instructions

1. **Clone the repository and install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```

2. **Set up your `.env` file:**
   ```env
   FLASK_SECRET_KEY=your_secret_key
   MYSQL_HOST=localhost
   MYSQL_USER=root
   MYSQL_PASSWORD=your_mysql_password
   MYSQL_DB=grocery_db
   GOOGLE_CLIENT_ID=your_google_client_id
   GOOGLE_CLIENT_SECRET=your_google_client_secret
   GEMINI_API_KEY=your_gemini_api_key
   ADMIN_EMAILS=admin1@gmail.com,admin2@yourcompany.com
   ```

3. **Create the database and tables:**
   - Use the SQL schema above in your MySQL client.

4. **Run the app:**
   ```sh
   python app.py
   ```

---

## How to Use

### User Features
- **Login:** Use Google login to access the chat.
- **Show products:** Type `product show` or `show products` to see available products (with IDs).
- **Add to cart:** Type `add to cart: product_id=<id>, quantity=<qty>` or `add to cart: pid=<id>, q=<qty>` (e.g., `add to cart: product_id=2, quantity=3`).
- **Place order:** Type `place order` to buy all items in your cart. Stock will be reduced accordingly.
- **Other:** Ask about products, recipes, or your cart in natural language.

### Admin Features
- **Admin login:** Log in with an email listed in `ADMIN_EMAILS` in your `.env` file.
- **Admin dashboard:**
  - View all orders in real time.
  - Upload an Excel file to replace the product catalog (columns must match the table).
  - Add, remove, or disable columns (schema management, to be implemented).
  - View and manage product catalog columns.
  - Switch between admin dashboard and user chat.

#### Excel Upload
- Uploading a new Excel file will **delete all existing products** and replace them with the new rows.
- The Excel columns must match the product_catalog table.

---

## Example Chat Commands

- Show products: `product show`
- Add to cart: `add to cart: product_id=2, quantity=3` or `add to cart: pid=2, q=3`
- Place order: `place order`

---

## Notes
- Only emails in `ADMIN_EMAILS` are admins.
- Stock is reduced in the database when an order is placed.
- If there is insufficient stock, the order will not go through.
- All admin features are accessible from the dashboard after admin login.
