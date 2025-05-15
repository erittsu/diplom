from flask import Flask, render_template, request, redirect, url_for, session
import pyodbc
import bcrypt
import json

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# Подключение к БД
def get_db_connection():
    return pyodbc.connect(
        r'DRIVER={ODBC Driver 17 for SQL Server};'
        r'SERVER=localhost\SQLEXPRESS;'
        r'DATABASE=warehouse;'
        r'UID=flask_user;'
        r'PWD=elich3258;'
    )

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None  # Для передачи ошибки в шаблон (если нужно)

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, password, role FROM Users WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()

        if user and bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
            session['user_id'] = user.user_id
            session['username'] = username
            session['role'] = user.role

            if user.role == 'admin':
                return redirect('/admin')
            elif user.role == 'staff':
                return redirect('/staff')
            elif user.role == 'supplier':
                return redirect('/supplier')
            else:
                return "Неизвестная роль пользователя"
        else:
            return render_template('login.html')

    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))

# Страница регистрации (только для админа)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'role' not in session or session['role'] != 'admin':
        return "Доступ запрещён", 403

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO Users (username, password, role) VALUES (?, ?, ?)",
                       (username, hashed_password, role))
        conn.commit()
        conn.close()

        return redirect('/login')

    return render_template('register.html')

@app.route('/admin')
def admin_panel():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')
    
    # Получаем статистику для дашборда
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Количество поставок
    cursor.execute("SELECT COUNT(*) FROM Deliveries")
    total_deliveries = cursor.fetchone()[0]
    
    # Количество активных пользователей
    cursor.execute("SELECT COUNT(*) FROM Users")
    active_users = cursor.fetchone()[0]
    
    conn.close()
    
    return render_template(
        'admin_panel.html',
        username=session['username'],
        total_deliveries=total_deliveries,
        active_users=active_users
    )

@app.route('/admin/deliveries')
def admin_deliveries():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')

    status_filter = request.args.get('status_filter', 'all')
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT D.delivery_id, D.delivery_date, D.status, 
               S.supplier_name, U.username as created_by
        FROM Deliveries D
        JOIN Suppliers S ON D.supplier_id = S.supplier_id
        JOIN Users U ON D.created_by = U.user_id
    """
    params = []

    if status_filter != 'all':
        query += " WHERE D.status = ?"
        params.append(status_filter)

    query += " ORDER BY D.delivery_date DESC"
    cursor.execute(query, params)
    deliveries = cursor.fetchall()
    conn.close()

    return render_template('admin_deliveries.html', deliveries=deliveries)

@app.route('/admin/approve_delivery/<int:delivery_id>', methods=['POST'])
def approve_delivery(delivery_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE Deliveries 
        SET status = 'received' 
        WHERE delivery_id = ? AND status = 'pending'
    """, (delivery_id,))
    conn.commit()
    conn.close()

    return redirect(url_for('admin_deliveries', operation_status=f'approved_{delivery_id}'))

@app.route('/admin/cancel_delivery/<int:delivery_id>', methods=['POST'])
def admin_cancel_delivery(delivery_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE Deliveries 
        SET status = 'cancelled' 
        WHERE delivery_id = ? AND status = 'pending'
    """, (delivery_id,))
    conn.commit()
    conn.close()

    return redirect(url_for('admin_deliveries', operation_status=f'cancelled_{delivery_id}'))

@app.route('/staff')
def staff_panel():
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT I.item_id, I.item_name, I.article_code, I.status, L.location_name
        FROM Items I
        LEFT JOIN Item_Locations IL ON I.item_id = IL.item_id
        LEFT JOIN Locations L ON IL.location_id = L.location_id
        ORDER BY I.item_id DESC
    """)
    items = cursor.fetchall()

    cursor.execute("""
        SELECT D.delivery_id, S.supplier_name, D.delivery_date, D.item_list
        FROM Deliveries D
        JOIN Suppliers S ON D.supplier_id = S.supplier_id
        WHERE D.status = 'pending'
        ORDER BY D.delivery_date DESC
    """)
    deliveries = cursor.fetchall()

    conn.close()

    return render_template('staff_panel.html', items=items, deliveries=deliveries)

@app.route('/receive_delivery/<int:delivery_id>', methods=['POST'])
def receive_delivery(delivery_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT item_list FROM Deliveries WHERE delivery_id = ?", (delivery_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return "Поставка не найдена", 404

    try:
        items = json.loads(row.item_list)
    except:
        conn.close()
        return "Невалидный JSON", 400

    for item in items:
        cursor.execute("""
            INSERT INTO Items (item_name, article_code, price, weight, size, item_type, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            item.get('item_name'), item.get('article_code'), item.get('price'),
            item.get('weight'), item.get('size'), item.get('type'), session['user_id']
        ))
        cursor.execute("SELECT SCOPE_IDENTITY()")
        new_item_id = cursor.fetchone()[0]

        cursor.execute("""
            SELECT location_id FROM Locations
            WHERE location_id NOT IN (SELECT location_id FROM Item_Locations)
            ORDER BY location_id
        """)
        loc_row = cursor.fetchone()
        if loc_row:
            location_id = loc_row.location_id
            cursor.execute("""
                INSERT INTO Item_Locations (item_id, location_id, placed_by)
                VALUES (?, ?, ?)
            """, (new_item_id, location_id, session['user_id']))

    cursor.execute("UPDATE Deliveries SET status = 'received' WHERE delivery_id = ?", (delivery_id,))
    conn.commit()
    conn.close()

    return redirect('/staff')


@app.route('/supplier')
def supplier_panel():
    if 'user_id' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    status_filter = request.args.get('status_filter', 'all')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Базовый запрос
    query = """
        SELECT delivery_id, delivery_date, status
        FROM Deliveries
        WHERE supplier_id = (SELECT supplier_id FROM Suppliers WHERE user_id = ?)
    """
    params = [session['user_id']]

    # Фильтр по статусу
    if status_filter != 'all':
        query += " AND status = ?"
        params.append(status_filter)

    # Фильтр по дате
    if start_date and end_date:
        query += " AND delivery_date BETWEEN ? AND ?"
        params.extend([start_date, end_date])

    query += " ORDER BY delivery_date DESC"
    cursor.execute(query, params)
    deliveries = cursor.fetchall()
    conn.close()

    return render_template('supplier_panel.html', deliveries=deliveries)

@app.route('/create_delivery', methods=['GET', 'POST'])
def create_delivery():
    if request.method == 'GET':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT supplier_id, supplier_name FROM Suppliers WHERE user_id = ?", (session['user_id'],))
        supplier = cursor.fetchone()
        conn.close()
        return render_template('create_delivery.html', supplier=supplier)

    # POST: обработка формы
    delivery_date = request.form.get('delivery_date')
    delivery_items = request.form.get('delivery_items')
    created_by = session['user_id']

    # Получаем supplier_id по user_id из сессии
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT supplier_id FROM Suppliers WHERE user_id = ?", (created_by,))
    result = cursor.fetchone()
    if not result:
        conn.close()
        return "Поставщик не найден", 400

    supplier_id = result.supplier_id

    try:
        cursor.execute("""
            INSERT INTO Deliveries (supplier_id, delivery_date, status, item_list, created_by)
            VALUES (?, ?, 'pending', ?, ?)
        """, (supplier_id, delivery_date, delivery_items, created_by))
        conn.commit()
    except pyodbc.IntegrityError as e:
        conn.rollback()
        return f"Ошибка при добавлении: {e}", 400
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('supplier_panel'))

@app.route('/supplier/delivery/<int:delivery_id>')
def delivery_details(delivery_id):
    if 'user_id' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверяем, что поставка принадлежит текущему поставщику
    cursor.execute("""
        SELECT D.delivery_id, D.delivery_date, D.status, D.item_list
        FROM Deliveries D
        JOIN Suppliers S ON D.supplier_id = S.supplier_id
        WHERE D.delivery_id = ? AND S.user_id = ?
    """, (delivery_id, session['user_id']))
    delivery = cursor.fetchone()
    conn.close()

    if not delivery:
        return "Поставка не найдена или доступ запрещён", 404

    items = json.loads(delivery.item_list)  # Парсим JSON
    return render_template(
        'delivery_details.html',
        delivery=delivery,
        items=items,
        can_cancel=(delivery.status == 'pending')  # Флаг для кнопки отмены
    )

@app.route('/supplier/cancel_delivery/<int:delivery_id>', methods=['POST'])
def supplier_cancel_delivery(delivery_id): 
    if 'user_id' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверяем принадлежность поставки и статус
    cursor.execute("""
        UPDATE Deliveries
        SET status = 'cancelled'
        WHERE delivery_id = ? AND status = 'pending'
        AND supplier_id IN (SELECT supplier_id FROM Suppliers WHERE user_id = ?)
    """, (delivery_id, session['user_id']))
    
    conn.commit()
    conn.close()
    return redirect(url_for('supplier_panel'))

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect('/login')
    return f"Добро пожаловать, {session['username']}! Ваша роль: {session['role']}"

if __name__ == '__main__':
    app.run(debug=True, port=5000)

