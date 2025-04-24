from flask import Flask, jsonify, request, render_template
import pyodbc

app = Flask(__name__)

# Конфигурация подключения к базе данных
SERVER = 'localhost\\SQLEXPRESS'
DATABASE = 'warehouse'
USER = 'flask_user'
PASSWORD = 'elich3258'

# Функция для подключения к базе данных
def get_db_connection():
    conn = pyodbc.connect(
        r'DRIVER={ODBC Driver 17 for SQL Server};'
        fr'SERVER={SERVER};'
        fr'DATABASE={DATABASE};'
        fr'UID={USER};'
        fr'PWD={PASSWORD};'
    )
    return conn

# Главная страница
@app.route('/')
def index():
    return render_template('index.html')

# Получить все товары
@app.route('/items')
def get_items():
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT item_id, item_name, category_id, price FROM Items")
        items = cursor.fetchall()
        connection.close()

        items_list = [
            {
                'item_id': row.item_id,
                'item_name': row.item_name,
                'category_id': row.category_id,
                'price': float(row.price)
            } for row in items
        ]
        return jsonify(items_list)
    except Exception as e:
        return f"Error: {str(e)}", 500

# Получить все категории
@app.route('/categories')
def get_categories():
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT category_id, category_name FROM Categories")
        categories = cursor.fetchall()
        connection.close()

        categories_list = [
            {
                'category_id': row.category_id,
                'category_name': row.category_name
            } for row in categories
        ]
        return jsonify(categories_list)
    except Exception as e:
        return f"Error: {str(e)}", 500

# Добавить товар и разместить его в первой свободной ячейке
@app.route('/add_item', methods=['POST'])
def add_item():
    try:
        data = request.json
        item_name = data['item_name']
        category_id = data['category_id']
        price = data['price']
        quantity = data['quantity']

        connection = get_db_connection()
        cursor = connection.cursor()

        # Добавляем товар в таблицу Items
        cursor.execute(
            "INSERT INTO Items (item_name, category_id, price) OUTPUT INSERTED.item_id VALUES (?, ?, ?)",
            (item_name, category_id, price)
        )
        item_id = cursor.fetchone()[0]

        # Находим первую свободную ячейку
        cursor.execute("SELECT TOP 1 location_id FROM Locations WHERE is_occupied = 0")
        free_location = cursor.fetchone()

        if not free_location:
            connection.rollback()
            connection.close()
            return "No free location available", 400

        location_id = free_location[0]

        # Обновляем статус ячейки и добавляем запись в Item_Locations
        cursor.execute("UPDATE Locations SET is_occupied = 1 WHERE location_id = ?", (location_id,))
        cursor.execute("INSERT INTO Item_Locations (item_id, location_id, quantity) VALUES (?, ?, ?)",
                       (item_id, location_id, quantity))

        # Добавляем запись в журнал операций
        cursor.execute("INSERT INTO Inventory_Transactions (item_id, transaction_type, quantity, location_id) VALUES (?, 'add', ?, ?)",
                       (item_id, quantity, location_id))

        connection.commit()
        connection.close()

        return "Item added successfully", 201
    except Exception as e:
        return f"Error: {str(e)}", 500

# Просмотр размещения товаров по ячейкам
@app.route('/item_locations')
def item_locations():
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("""
            SELECT I.item_name, L.location_name, IL.quantity
            FROM Item_Locations IL
            JOIN Items I ON IL.item_id = I.item_id
            JOIN Locations L ON IL.location_id = L.location_id
        """)
        rows = cursor.fetchall()
        connection.close()

        locations_list = [
            {
                'item_name': row.item_name,
                'location_name': row.location_name,
                'quantity': row.quantity
            } for row in rows
        ]
        return jsonify(locations_list)
    except Exception as e:
        return f"Error: {str(e)}", 500

if __name__ == '__main__':
    app.run(debug=True)