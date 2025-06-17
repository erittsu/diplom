from flask import Blueprint, render_template, redirect, url_for, request, session
import pyodbc
import bcrypt

admin_bp = Blueprint('admin', __name__)

def get_db_connection():
    return pyodbc.connect(
        r'DRIVER={ODBC Driver 17 for SQL Server};'
        r'Server=WIN-EPU1AR2HMUO;'
        r'DATABASE=warehouse;'
        r'UID=flask_user;'
        r'PWD=elich3258;'
    )

@admin_bp.route('/')
def admin_dashboard():
    if 'role' not in session or session['role'] != 'admin':
        return "Доступ запрещён", 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Получаем статистику для дашборда
    cursor.execute("SELECT COUNT(*) FROM Users")
    active_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM Deliveries")
    total_deliveries = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM Outbound_Deliveries")
    total_outbound = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM Inventory_Transactions")
    audit_entries = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT TOP 5 transaction_type, transaction_date
        FROM Inventory_Transactions 
        ORDER BY transaction_date DESC
    """)
    recent_actions = cursor.fetchall()
    
    conn.close()
    
    return render_template('admin/admin_dashboard.html',
                         active_users=active_users,
                         total_deliveries=total_deliveries,
                         total_outbound=total_outbound,
                         audit_entries=audit_entries,
                         recent_actions=recent_actions)


@admin_bp.route('/users')
def admin_users():
    if 'role' not in session or session['role'] != 'admin':
        return "Доступ запрещён", 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, role FROM Users")
    users = cursor.fetchall()
    conn.close()
    
    return render_template('admin/admin_users.html', users=users)

@admin_bp.route('/register', methods=['GET', 'POST'])
def register():
    if 'role' not in session or session['role'] != 'admin':
        return "Доступ запрещён", 403
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        role = request.form['role']

        if password != confirm_password:
            return render_template('register.html', error="Пароли не совпадают")

        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Проверка существующего пользователя
            cursor.execute("SELECT username FROM Users WHERE username = ?", (username,))
            if cursor.fetchone():
                return render_template('register.html', error="Пользователь с таким именем уже существует")

            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Добавление пользователя
            cursor.execute("INSERT INTO Users (username, password, role) VALUES (?, ?, ?)",
                         (username, hashed_password, role))
            
            # Если это поставщик, добавляем информацию в таблицу Suppliers
            if role == 'supplier':
                supplier_name = request.form.get('supplier_name', '')
                contact_info = request.form.get('contact_info', '')
                
                cursor.execute("""
                    INSERT INTO Suppliers (supplier_name, contact_info, supplier_login)
                    VALUES (?, ?, ?)
                """, (supplier_name, contact_info, username))
            
            conn.commit()
            return redirect(url_for('admin.admin_users'))
        except Exception as e:
            conn.rollback()
            return render_template('register.html', error=f"Ошибка при регистрации: {str(e)}")
        finally:
            conn.close()

    return render_template('register.html')

@admin_bp.route('/deliveries')
def admin_deliveries():
    if 'role' not in session or session['role'] != 'admin':
        return "Доступ запрещён", 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.delivery_id, d.supplier_id, s.supplier_name, 
               d.delivery_date, d.status, d.item_list
        FROM Deliveries d
        JOIN Suppliers s ON d.supplier_id = s.supplier_id
        ORDER BY d.delivery_date DESC
    """)
    deliveries = cursor.fetchall()
    conn.close()
    
    return render_template('admin/admin_deliveries.html', deliveries=deliveries)

@admin_bp.route('/outbound')
def admin_outbound():
    if 'role' not in session or session['role'] != 'admin':
        return "Доступ запрещён", 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT outbound_id, destination_address, delivery_date, 
               status, item_list
        FROM Outbound_Deliveries
        ORDER BY delivery_date DESC
    """)
    outbound = cursor.fetchall()
    conn.close()
    
    return render_template('admin/admin_outbound.html', outbound=outbound)

@admin_bp.route('/audit')
def admin_audit():
    if 'role' not in session or session['role'] != 'admin':
        return "Доступ запрещён", 403
    
    # Get filter parameters
    filter_type = request.args.get('filter', 'all')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    # Pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 
    query = """
        SELECT 
            it.transaction_id, 
            it.user_id, 
            u.username,
            it.transaction_type, 
            it.transaction_date, 
            it.item_id, 
            it.location_id
        FROM Inventory_Transactions it
        LEFT JOIN Users u ON it.user_id = u.user_id
    """
    
    # 
    conditions = []
    params = []
    
    # фильтры для журнала аудита
    if filter_type != 'all':
        if filter_type == 'login':
            conditions.append("it.transaction_type IN ('login', 'logout')")
        elif filter_type == 'data_change':
            conditions.append("it.transaction_type IN ('user_create', 'user_update', 'user_delete')")
        elif filter_type == 'inventory':
            conditions.append("""it.transaction_type IN 
                ('add', 'remove', 'move', 'ship', 'place', 
                 'receive_delivery', 'create_delivery', 
                 'create_outbound', 'receive_outbound')""")
    
    # Add date range conditions
    if date_from:
        conditions.append("it.transaction_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("it.transaction_date <= ?")
        params.append(date_to + ' 23:59:59')
    
    # Combine conditions
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    # Count query for pagination
    count_query = "SELECT COUNT(*) FROM (" + query + ") AS total"
    cursor.execute(count_query, params)
    total_items = cursor.fetchone()[0]
    total_pages = (total_items + per_page - 1) // per_page
    
    # Add pagination to main query
    query += " ORDER BY it.transaction_date DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
    params.extend([(page-1)*per_page, per_page])
    
    cursor.execute(query, params)
    audit_logs = cursor.fetchall()
    
    conn.close()
    
    return render_template('admin/admin_audit.html', 
                         audit_logs=audit_logs,
                         page=page,
                         per_page=per_page,
                         total_items=total_items,
                         total_pages=total_pages,
                         filter_type=filter_type,
                         date_from=date_from or '',
                         date_to=date_to or '')