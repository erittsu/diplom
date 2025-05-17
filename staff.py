from flask import Blueprint, render_template, session, redirect, request, url_for
import pyodbc
import json
from datetime import datetime

staff_bp = Blueprint('staff', __name__)

def get_db_connection():
    return pyodbc.connect(
        r'DRIVER={ODBC Driver 17 for SQL Server};'
        r'SERVER=localhost\SQLEXPRESS;'
        r'DATABASE=warehouse;'
        r'UID=flask_user;'
        r'PWD=elich3258;'
    )

@staff_bp.route('/')
def staff_panel():
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT I.item_id, I.item_name, I.article_code, I.status, I.price, I.weight, 
               I.size, I.item_type, L.location_name
        FROM Items I
        LEFT JOIN Item_Locations IL ON I.item_id = IL.item_id
        LEFT JOIN Locations L ON IL.location_id = L.location_id
        ORDER BY I.item_id DESC
    """)
    items = []
    columns = [column[0] for column in cursor.description]
    for row in cursor.fetchall():
        items.append(dict(zip(columns, row)))


    cursor.execute("""
        SELECT D.delivery_id, S.supplier_name, 
               FORMAT(D.delivery_date, 'dd.MM.yyyy') as delivery_date, 
               D.status, D.item_list as delivery_items
        FROM Deliveries D
        JOIN Suppliers S ON D.supplier_id = S.supplier_id
        WHERE D.status = 'pending'
        ORDER BY D.delivery_date DESC
    """)
    deliveries = []
    columns = [column[0] for column in cursor.description]
    for row in cursor.fetchall():
        delivery_data = dict(zip(columns, row))
        try:
            delivery_data['delivery_items'] = json.loads(delivery_data['delivery_items'])
            deliveries.append(delivery_data)
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            continue

    conn.close()

    return redirect(url_for('staff.staff_dashboard', items=items, deliveries=deliveries))

@staff_bp.route('/receive_delivery/<int:delivery_id>', methods=['POST'])
def receive_delivery(delivery_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT item_list, supplier_id FROM Deliveries 
            WHERE delivery_id = ? AND status = 'pending'
        """, (delivery_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return "Delivery not found or already processed", 404

        items = json.loads(row.item_list)
        supplier_id = row.supplier_id

        # свободные ячейки с группировкой по типу (ПРОЦЕДУРУ)
        cursor.execute("""
            SELECT location_id, location_type 
            FROM Locations
            WHERE location_id NOT IN (SELECT location_id FROM Item_Locations)
            ORDER BY 
                CASE WHEN location_type = 'обычный' THEN 1 ELSE 0 END,
                location_type
        """)
        
        free_locations = {}
        for loc in cursor.fetchall():
            if loc.location_type not in free_locations:
                free_locations[loc.location_type] = []
            free_locations[loc.location_type].append(loc.location_id)

        for item in items:
            item_type = item['type']
            location_id = None
            
            if item_type in free_locations and free_locations[item_type]:
                location_id = free_locations[item_type].pop()

            elif 'обычный' in free_locations and free_locations['обычный']:
                location_id = free_locations['обычный'].pop()
            
            if not location_id:
                conn.rollback()
                return f"No available locations for item type {item_type}", 400

            # проверка совместимости
            cursor.execute("""
                SELECT location_type FROM Locations WHERE location_id = ?
            """, (location_id,))
            loc_type = cursor.fetchone().location_type
            
            if loc_type != 'обычный' and loc_type != item_type:
                conn.rollback()
                return f"Incompatible: item type {item_type} cannot be placed in location type {loc_type}", 400

            # добавление товара в Items
            cursor.execute("""
                INSERT INTO Items (item_name, article_code, price, weight, size, 
                                 item_type, status, supplier_id)
                VALUES (?, ?, ?, ?, ?, ?, 'accepted', ?)
            """, (
                item['item_name'], 
                item['article_code'], 
                item['price'],
                item['weight'], 
                item['size'], 
                item_type,
                supplier_id
            ))
            
            new_item_id = cursor.execute("SELECT SCOPE_IDENTITY()").fetchone()[0]
            
            # товар в Item_Locations
            cursor.execute("""
                INSERT INTO Item_Locations (item_id, location_id, placed_by)
                VALUES (?, ?, ?)
            """, (new_item_id, location_id, session['user_id']))
            
            # логи receive_delivery
            cursor.execute("""
                INSERT INTO Inventory_Transactions 
                (user_id, item_id, location_id, transaction_type)
                VALUES (?, ?, ?, 'receive_delivery')
            """, (session['user_id'], new_item_id, location_id))

        # обновление статуса ПРИНЯТ
        cursor.execute("""
            UPDATE Deliveries 
            SET status = 'received' 
            WHERE delivery_id = ?
        """, (delivery_id,))
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        return f"Error processing delivery: {str(e)}", 500
    finally:
        conn.close()

    return redirect(url_for('staff.staff_panel'))

@staff_bp.route('/place_item/<int:item_id>', methods=['POST'])
def place_item(item_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # тип товара
        cursor.execute("SELECT item_type FROM Items WHERE item_id = ?", (item_id,))
        item_type = cursor.fetchone().item_type

        # поиск подходящего места по типу
        cursor.execute("""
            SELECT TOP 1 location_id 
            FROM Locations 
            WHERE location_id NOT IN (SELECT location_id FROM Item_Locations)
            AND (location_type = ? OR location_type = 'обычный')
            ORDER BY 
                CASE WHEN location_type = ? THEN 0 ELSE 1 END
        """, (item_type, item_type))
        
        location = cursor.fetchone()
        if not location:
            return "No suitable free locations available", 400

        # помещение товара в ячейку
        cursor.execute("""
            INSERT INTO Item_Locations (item_id, location_id, placed_by)
            VALUES (?, ?, ?)
        """, (item_id, location.location_id, session['user_id']))
        
        # логи, ячейка
        cursor.execute("""
            INSERT INTO Inventory_Transactions 
            (user_id, item_id, location_id, transaction_type)
            VALUES (?, ?, ?, 'place')
        """, (session['user_id'], item_id, location.location_id))
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        return f"Error placing item: {str(e)}", 500
    finally:
        conn.close()

    return redirect(url_for('staff.staff_panel'))

# ДОРАБОТАТЬ
@staff_bp.route('/return_item/<int:item_id>', methods=['POST'])
def return_item(item_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT supplier_id FROM Items WHERE item_id = ?
        """, (item_id,))
        supplier_id = cursor.fetchone().supplier_id

        cursor.execute("""
            DELETE FROM Items WHERE item_id = ?
        """, (item_id,))
        
        # Log return
        cursor.execute("""
            INSERT INTO Outbound_Deliveries 
            (destination_address, status, item_list, created_by)
            VALUES (?, 'returned', ?, ?)
        """, (
            f"Return to supplier {supplier_id}",
            json.dumps([{"item_id": item_id}]),
            session['user_id']
        ))
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        return f"Error returning item: {str(e)}", 500
    finally:
        conn.close()

    return redirect(url_for('staff.staff_panel'))

@staff_bp.route('/dashboard')
def staff_dashboard():
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get dashboard statistics
    cursor.execute("SELECT COUNT(*) FROM Deliveries WHERE status = 'pending'")
    pending_deliveries_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM Deliveries WHERE status = 'received'")
    received_deliveries_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM Items")
    items_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM Outbound_Deliveries")
    outbound_count = cursor.fetchone()[0]
    
    # Get recent actions
    cursor.execute("""
        SELECT TOP 5 transaction_date as time, 
               CASE 
                   WHEN transaction_type = 'receive_delivery' THEN 'Receive delivery'
                   WHEN transaction_type = 'place' THEN 'Place item'
                   WHEN transaction_type = 'return' THEN 'Return item'
                   ELSE transaction_type
               END as description
        FROM Inventory_Transactions
        ORDER BY transaction_date DESC
    """)
    recent_actions = [dict(zip([column[0] for column in cursor.description], row)) 
                     for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template(
        'staff/staff_dashboard.html',
        current_date=datetime.now().strftime('%d.%m.%Y'),
        pending_deliveries_count=pending_deliveries_count,
        received_deliveries_count=received_deliveries_count,
        items_count=items_count,
        outbound_count=outbound_count,
        recent_actions=recent_actions
    )

@staff_bp.route('/deliveries')
def staff_deliveries():
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    status_filter = request.args.get('status')
    conn = get_db_connection()
    cursor = conn.cursor()

    # Базовый запрос
    query = """
        SELECT D.delivery_id, S.supplier_name, 
               D.delivery_date,
               D.status, D.item_list as items_json
        FROM Deliveries D
        JOIN Suppliers S ON D.supplier_id = S.supplier_id
    """
    
    # Добавляем условие WHERE если есть фильтр
    if status_filter:
        query += " WHERE D.status = ?"
        cursor.execute(query, (status_filter,))
    else:
        query += " ORDER BY D.delivery_date DESC"
        cursor.execute(query)
    
    deliveries = []
    for row in cursor.fetchall():
        delivery = dict(zip([column[0] for column in cursor.description], row))
        try:
            delivery['items'] = json.loads(delivery['items_json'])
            delivery['items_count'] = len(delivery['items'])
        except:
            delivery['items'] = []
            delivery['items_count'] = 0
        deliveries.append(delivery)
    
    conn.close()
    
    return render_template(
        'staff/staff_deliveries.html',
        deliveries=deliveries,
        status_filter=status_filter
    )

@staff_bp.route('/deliveries/<int:delivery_id>')
def staff_delivery_details(delivery_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT D.delivery_id, S.supplier_name, 
               FORMAT(D.delivery_date, 'dd.MM.yyyy') as delivery_date, 
               D.status, D.item_list as items_json
        FROM Deliveries D
        JOIN Suppliers S ON D.supplier_id = S.supplier_id
        WHERE D.delivery_id = ?
    """, (delivery_id,))
    
    delivery = cursor.fetchone()
    if not delivery:
        conn.close()
        return "Delivery not found", 404
    
    delivery = dict(zip([column[0] for column in cursor.description], delivery))
    try:
        delivery['items'] = json.loads(delivery['items_json'])
    except:
        delivery['items'] = []
    
    conn.close()
    
    return render_template(
        'staff/staff_delivery_details.html',
        delivery=delivery
    )

@staff_bp.route('/outbound')
def staff_outbound():
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    status_filter = request.args.get('status', 'preparing')
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT outbound_id, destination_address, 
               FORMAT(delivery_date, 'dd.MM.yyyy') as delivery_date, 
               status, item_list as items_json
        FROM Outbound_Deliveries
        WHERE status = ?
        ORDER BY delivery_date DESC
    """
    cursor.execute(query, (status_filter,))
    
    outbounds = []
    for row in cursor.fetchall():
        outbound = dict(zip([column[0] for column in cursor.description], row))
        try:
            outbound['items'] = json.loads(outbound['items_json'])
            outbound['items_count'] = len(outbound['items'])
        except:
            outbound['items'] = []
            outbound['items_count'] = 0
        outbounds.append(outbound)
    
    conn.close()
    
    return render_template(
        'staff/staff_outbound.html',
        outbounds=outbounds,
        status_filter=status_filter
    )

@staff_bp.route('/inventory')
def staff_inventory():
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT I.item_id, I.item_name, I.article_code, I.status, 
               I.price, I.weight, I.size, I.item_type, 
               L.location_name, L.location_type,
               FORMAT(IL.placed_date, 'dd.MM.yyyy HH:mm') as placed_date
        FROM Items I
        LEFT JOIN Item_Locations IL ON I.item_id = IL.item_id
        LEFT JOIN Locations L ON IL.location_id = L.location_id
        ORDER BY I.item_id DESC
    """)
    
    items = [dict(zip([column[0] for column in cursor.description], row)) 
            for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template(
        'staff/staff_inventory.html',
        items=items
    )