from flask import Flask, render_template, request, redirect, url_for, session
import bcrypt
import pyodbc
from admin import admin_bp
from staff import staff_bp
from supplier import supplier_bp

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# регистрация Blueprints 
app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(staff_bp, url_prefix='/staff')
app.register_blueprint(supplier_bp, url_prefix='/supplier')

# всё для коннекта с бд
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
    error = None
    
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
                # для поставщиков на всякий случай проверяется существование в таблице Suppliers
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT supplier_id FROM Suppliers WHERE supplier_login = ?", (username,))
                supplier = cursor.fetchone()
                conn.close()
                
                if not supplier:
                    return "Учетная запись поставщика не настроена", 403
                
                return redirect('/supplier')
            else:
                return "Неизвестная роль пользователя"
        else:
            return render_template('login.html', error="Неверное имя пользователя или пароль")

    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'role' not in session or session['role'] != 'admin':
        return "Доступ запрещён", 403

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        # проверка не существует уже пользователь с таким именем
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM Users WHERE username = ?", (username,))
        if cursor.fetchone():
            conn.close()
            return render_template('register.html', error="Пользователь с таким именем уже существует")

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        try:
            cursor.execute("INSERT INTO Users (username, password, role) VALUES (?, ?, ?)",
                         (username, hashed_password, role))
            
            # если регистрация поставщика, создаётся запись в таблице Suppliers
            if role == 'supplier':
                supplier_name = request.form.get('supplier_name', '')
                contact_info = request.form.get('contact_info', '')
                
                cursor.execute("""
                    INSERT INTO Suppliers (supplier_name, contact_info, supplier_login)
                    VALUES (?, ?, ?)
                """, (supplier_name, contact_info, username))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            return render_template('register.html', error=f"Ошибка при регистрации: {str(e)}")
        finally:
            conn.close()

        return redirect('/login')

    return render_template('register.html')

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect('/login')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Получаем данные пользователя
    cursor.execute("""
        SELECT username, role, created_at 
        FROM Users 
        WHERE user_id = ?
    """, (session['user_id'],))
    user_data = cursor.fetchone()
    
    # Для сотрудников получаем дополнительную статистику
    stats = {}
    if session.get('role') == 'staff':
        cursor.execute("SELECT COUNT(*) FROM Inventory_Transactions WHERE user_id = ?", (session['user_id'],))
        stats['total_actions'] = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(DISTINCT delivery_id) 
            FROM Deliveries D
            JOIN Inventory_Transactions IT ON IT.related_entity_id = D.delivery_id
            WHERE IT.user_id = ? AND IT.transaction_type = 'receive_delivery'
        """, (session['user_id'],))
        stats['processed_deliveries'] = cursor.fetchone()[0]
    
    conn.close()
    
    return render_template('profile.html', 
                         user_data=user_data,
                         stats=stats)

if __name__ == '__main__':
    app.run(debug=True)

# Users ↔ Deliveries (created_by) (удалена)
# Было: Deliveries.created_by → Users.user_id

# Причина:

# Поставки инициируются системой при получении данных от поставщика

# Ответственный фиксируется в журнале при подтверждении получения

# Альтернатива:

# sql
# SELECT user_id FROM Inventory_Transactions 
# WHERE transaction_type = 'receive_delivery' 
#   AND related_entity_id = [delivery_id]
# 4. Users ↔ Item_Locations (placed_by) (удалена)
# Было: Item_Locations.placed_by → Users.user_id

# Причина:

# Размещение товаров — часть процесса приемки

# Достаточно фиксации в журнале операций

# Альтернатива:

# sql
# SELECT user_id FROM Inventory_Transactions
# WHERE transaction_type = 'place' 
#   AND item_id = [item_id] 
#   AND location_id = [location_id]
# 5. Users ↔ Outbound_Deliveries (created_by) (удалена)
# Было: Outbound_Deliveries.created_by → Users.user_id

# Причина:

# Отгрузки могут создаваться автоматически (например, из заказов)

# Ответственный фиксируется при подтверждении отгрузки

# Альтернатива:

# sql
# SELECT user_id FROM Inventory_Transactions
# WHERE transaction_type = 'create_outbound' 
#   AND related_entity_id = [outbound_id]