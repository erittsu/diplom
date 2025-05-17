from flask import Blueprint, render_template, redirect, url_for, request, session
import pyodbc

admin_bp = Blueprint('admin', __name__)

def get_db_connection():
    return pyodbc.connect(
        r'DRIVER={ODBC Driver 17 for SQL Server};'
        r'SERVER=localhost\SQLEXPRESS;'
        r'DATABASE=warehouse;'
        r'UID=flask_user;'
        r'PWD=elich3258;'
    )

@admin_bp.route('/')
def admin_panel():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM Deliveries")
    total_deliveries = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM Users")
    active_users = cursor.fetchone()[0]
    
    conn.close()
    
    return render_template(
        'admin/admin_panel.html',
        username=session['username'],
        total_deliveries=total_deliveries,
        active_users=active_users
    )

@admin_bp.route('/deliveries')
def admin_deliveries():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')

    status_filter = request.args.get('status_filter', 'all')
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
    SELECT D.delivery_id, D.delivery_date, D.status, 
           S.supplier_name, S.supplier_login as created_by
    FROM Deliveries D
    JOIN Suppliers S ON D.supplier_id = S.supplier_id
"""
    params = []

    if status_filter != 'all':
        query += " WHERE D.status = ?"
        params.append(status_filter)

    query += " ORDER BY D.delivery_date DESC"
    cursor.execute(query, params)
    deliveries = cursor.fetchall()
    conn.close()

    return render_template('admin/admin_deliveries.html', deliveries=deliveries)

# УБРАТЬ
@admin_bp.route('/approve_delivery/<int:delivery_id>', methods=['POST'])
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

    return redirect(url_for('admin.admin_deliveries', operation_status=f'approved_{delivery_id}'))

# УБРАТЬ
@admin_bp.route('/cancel_delivery/<int:delivery_id>', methods=['POST'])
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

    return redirect(url_for('admin.admin_deliveries', operation_status=f'cancelled_{delivery_id}'))