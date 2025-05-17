from flask import Blueprint, render_template, session, redirect, request, url_for
import pyodbc
import json

supplier_bp = Blueprint('supplier', __name__)

def get_db_connection():
    return pyodbc.connect(
        r'DRIVER={ODBC Driver 17 for SQL Server};'
        r'SERVER=localhost\SQLEXPRESS;'
        r'DATABASE=warehouse;'
        r'UID=flask_user;'
        r'PWD=elich3258;'
    )

@supplier_bp.route('/')
def supplier_panel():
    if 'username' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    status_filter = request.args.get('status_filter', 'all')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Базовый запрос - теперь используем supplier_login из сессии
    query = """
        SELECT delivery_id, delivery_date, status
        FROM Deliveries
        WHERE supplier_id = (SELECT supplier_id FROM Suppliers WHERE supplier_login = ?)
    """
    params = [session['username']]

    # Фильтры остаются без изменений
    if status_filter != 'all':
        query += " AND status = ?"
        params.append(status_filter)

    if start_date and end_date:
        query += " AND delivery_date BETWEEN ? AND ?"
        params.extend([start_date, end_date])

    query += " ORDER BY delivery_date DESC"
    cursor.execute(query, params)
    deliveries = cursor.fetchall()
    conn.close()

    return render_template('supplier/supplier_panel.html', deliveries=deliveries)

@supplier_bp.route('/create_delivery', methods=['GET', 'POST'])
def create_delivery():
    if 'username' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    if request.method == 'GET':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT supplier_id, supplier_name 
            FROM Suppliers 
            WHERE supplier_login = ?
        """, (session['username'],))
        supplier = cursor.fetchone()
        conn.close()
        return render_template('supplier/create_delivery.html', supplier=supplier)

    # POST обработка
    delivery_date = request.form.get('delivery_date')
    delivery_items = request.form.get('delivery_items')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT supplier_id 
        FROM Suppliers 
        WHERE supplier_login = ?
    """, (session['username'],))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return "Поставщик не найден", 400

    supplier_id = result.supplier_id

    try:
        cursor.execute("""
            INSERT INTO Deliveries (supplier_id, delivery_date, status, item_list)
            VALUES (?, ?, 'pending', ?)
        """, (supplier_id, delivery_date, delivery_items))
        conn.commit()
    except pyodbc.IntegrityError as e:
        conn.rollback()
        return f"Ошибка при добавлении: {e}", 400
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('supplier.supplier_panel'))

@supplier_bp.route('/delivery/<int:delivery_id>')
def delivery_details(delivery_id):
    if 'username' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT D.delivery_id, D.delivery_date, D.status, D.item_list
        FROM Deliveries D
        JOIN Suppliers S ON D.supplier_id = S.supplier_id
        WHERE D.delivery_id = ? AND S.supplier_login = ?
    """, (delivery_id, session['username']))
    delivery = cursor.fetchone()
    conn.close()

    if not delivery:
        return "Поставка не найдена или доступ запрещён", 404

    items = json.loads(delivery.item_list)
    return render_template(
        'supplier/delivery_details.html',
        delivery=delivery,
        items=items,
        can_cancel=(delivery.status == 'pending')
    )

@supplier_bp.route('/cancel_delivery/<int:delivery_id>', methods=['POST'])
def cancel_delivery(delivery_id): 
    if 'username' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE Deliveries
        SET status = 'cancelled'
        WHERE delivery_id = ? AND status = 'pending'
        AND supplier_id IN (SELECT supplier_id FROM Suppliers WHERE supplier_login = ?)
    """, (delivery_id, session['username']))
    
    conn.commit()
    conn.close()
    return redirect(url_for('supplier.supplier_panel'))