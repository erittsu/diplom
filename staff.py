from flask import Blueprint, render_template, session, redirect, request, url_for
import pyodbc
import json
from datetime import datetime

staff_bp = Blueprint('staff', __name__)

def get_db_connection():
    return pyodbc.connect(
        r'DRIVER={ODBC Driver 17 for SQL Server};'
        r'Server=WIN-EPU1AR2HMUO;'
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
        # Get delivery data
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

        # Get selected items from form (only checked items)
        accepted_indices = [int(i) for i in request.form.getlist('accept_item')]
        items_to_accept = [items[i] for i in accepted_indices]

        # Get free locations grouped by type
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

        # Process each accepted item
        for item in items_to_accept:
            item_type = item['type']
            location_id = None
            
            # Try to find matching location type first
            if item_type in free_locations and free_locations[item_type]:
                location_id = free_locations[item_type].pop()
            elif 'обычный' in free_locations and free_locations['обычный']:
                location_id = free_locations['обычный'].pop()
            
            if not location_id:
                conn.rollback()
                return f"Нет доступной ячейки для товара типа: {item_type}", 400

            # Add item to Items table
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
            
            # Place item in location
            cursor.execute("""
                INSERT INTO Item_Locations (item_id, location_id, placed_by)
                VALUES (?, ?, ?)
            """, (new_item_id, location_id, session['user_id']))
            
            # Log transaction
            cursor.execute("""
                INSERT INTO Inventory_Transactions 
                (user_id, item_id, location_id, transaction_type)
                VALUES (?, ?, ?, 'receive_delivery')
            """, (session['user_id'], new_item_id, location_id))

        # Update delivery status if all items were accepted
        if len(accepted_indices) == len(items):
            cursor.execute("""
                UPDATE Deliveries 
                SET status = 'received' 
                WHERE delivery_id = ?
            """, (delivery_id,))
        else:
            # If only some items were accepted, update the item_list in the delivery
            remaining_items = [item for i, item in enumerate(items) if i not in accepted_indices]
            cursor.execute("""
                UPDATE Deliveries 
                SET item_list = ?
                WHERE delivery_id = ?
            """, (json.dumps(remaining_items, ensure_ascii=False), delivery_id))
        
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
            json.dumps([{"item_id": item_id}], ensure_ascii=False),
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
    sort_by = request.args.get('sort', 'date_desc')
    
    conn = get_db_connection()
    cursor = conn.cursor()

    # Базовый запрос
    query = """
        SELECT 
            D.delivery_id, 
            S.supplier_name, 
            FORMAT(D.delivery_date, 'dd.MM.yyyy') as delivery_date,
            D.status, 
            D.item_list as items_json,
            (SELECT COUNT(*) FROM OPENJSON(D.item_list)) as items_count,
            CASE WHEN D.status = 'pending' THEN 0 ELSE 1 END as priority
        FROM Deliveries D
        JOIN Suppliers S ON D.supplier_id = S.supplier_id
    """
    
    params = ()
    where_clauses = []
    
    # Добавляем фильтр если указан и не равен 'all'
    if status_filter and status_filter != 'all':
        where_clauses.append("D.status = ?")
        params = (status_filter,)
    
    # Добавляем фильтр по дате в зависимости от сортировки
    if sort_by == 'today':
        where_clauses.append("CAST(D.delivery_date AS DATE) = CAST(GETDATE() AS DATE)")
    elif sort_by == 'week':
        where_clauses.append("D.delivery_date >= DATEADD(day, -7, GETDATE())")
    elif sort_by == 'month':
        where_clauses.append("D.delivery_date >= DATEADD(month, -1, GETDATE())")
    
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    
    # Добавляем сортировку
    if sort_by in ['date_asc', 'today', 'week', 'month']:
        query += " ORDER BY priority ASC, D.delivery_date ASC"
    else:  # По умолчанию: date_desc и другие случаи
        query += " ORDER BY priority ASC, D.delivery_date DESC"
    
    cursor.execute(query, params)
    
    # Получаем данные
    columns = [column[0] for column in cursor.description]
    deliveries = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template(
        'staff/staff_deliveries.html',
        deliveries=deliveries,
        status_filter=status_filter,
        current_sort=sort_by
    )

@staff_bp.route('/deliveries/<int:delivery_id>', methods=['GET', 'POST'])
def staff_delivery_details(delivery_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if request.method == 'POST':
            accept_index = request.form.get('accept_item')
            if accept_index is not None:
                accept_index = int(accept_index)
                
                cursor.execute("""
                    SELECT item_list, supplier_id FROM Deliveries 
                    WHERE delivery_id = ? AND status = 'pending'
                """, (delivery_id,))
                row = cursor.fetchone()
                if not row:
                    return render_template('staff/staff_delivery_details.html', 
                                        error='Поставка не найдена или уже обработана',
                                        delivery=None)

                items = json.loads(row.item_list)
                supplier_id = row.supplier_id

                if 0 <= accept_index < len(items):
                    item = items[accept_index]
                    
                    # Проверяем, не был ли уже принят этот товар
                    if item.get('accepted', False):
                        return redirect(url_for('staff.staff_delivery_details', delivery_id=delivery_id))
                    
                    cursor.execute("""
                        SELECT TOP 1 location_id, location_name 
                        FROM Locations
                        WHERE location_id NOT IN (SELECT location_id FROM Item_Locations)
                        AND (location_type = ? OR location_type = 'обычный')
                        ORDER BY 
                            CASE WHEN location_type = ? THEN 0 ELSE 1 END
                    """, (item['type'], item['type']))
                    
                    location = cursor.fetchone()
                    if not location:
                        return render_template('staff/staff_delivery_details.html',
                                            error=f"Нет доступной ячейки для товара типа: {item['type']}",
                                            delivery=None)

                    # Вставляем товар
                    cursor.execute("""
                        INSERT INTO Items (item_name, article_code, price, weight, size, 
                                        item_type, status, supplier_id)
                        OUTPUT INSERTED.item_id
                        VALUES (?, ?, ?, ?, ?, ?, 'accepted', ?)
                    """, (
                        item['item_name'], 
                        item['article_code'], 
                        item['price'],
                        item['weight'], 
                        item['size'], 
                        item['type'],
                        supplier_id
                    ))

                    new_item_id_result = cursor.fetchone()
                    if not new_item_id_result:
                        conn.rollback()
                        error_msg = "Ошибка при создании товара: не удалось получить ID нового товара"
                        print(error_msg)
                        return render_template('staff/staff_delivery_details.html',
                                            error=error_msg,
                                            delivery=None)
                    new_item_id = new_item_id_result[0]

                    # Размещаем товар
                    cursor.execute("""
                        INSERT INTO Item_Locations (item_id, location_id)
                        VALUES (?, ?)
                    """, (new_item_id, location.location_id))
                    
                    # Логируем операцию
                    cursor.execute("""
                        INSERT INTO Inventory_Transactions 
                        (user_id, item_id, location_id, transaction_type)
                        VALUES (?, ?, ?, 'receive_delivery')
                    """, (session['user_id'], new_item_id, location.location_id))

                    # Помечаем товар как принятый в списке поставки
                    items[accept_index]['accepted'] = True
                    items[accept_index]['location_id'] = location.location_id
                    items[accept_index]['location_name'] = location.location_name
                    
                    # Обновляем список товаров в поставке
                    cursor.execute("""
                        UPDATE Deliveries 
                        SET item_list = ?
                        WHERE delivery_id = ?
                    """, (json.dumps(items), delivery_id))
                    
                    # Проверяем, все ли товары приняты
                    all_accepted = all(item.get('accepted', False) for item in items)
                    if all_accepted:
                        cursor.execute("""
                            UPDATE Deliveries 
                            SET status = 'received'
                            WHERE delivery_id = ?
                        """, (delivery_id,))
                    
                    conn.commit()
                    return redirect(url_for('staff.staff_delivery_details', delivery_id=delivery_id))

        # Получаем данные о поставке для GET-запроса
        cursor.execute("""
            SELECT 
                D.delivery_id, 
                S.supplier_name, 
                FORMAT(D.delivery_date, 'dd.MM.yyyy') as delivery_date, 
                D.status, 
                D.item_list as items_json,
                (SELECT COUNT(*) FROM OPENJSON(D.item_list)) as items_count
            FROM Deliveries D
            JOIN Suppliers S ON D.supplier_id = S.supplier_id
            WHERE D.delivery_id = ?
        """, (delivery_id,))
        
        row = cursor.fetchone()
        if not row:
            return render_template('staff/staff_delivery_details.html', 
                                error='Поставка не найдена',
                                delivery=None)

        # Обработка данных поставки
        columns = [column[0] for column in cursor.description]
        delivery = dict(zip(columns, row))
        
        items = []
        json_error = None
        items_json = delivery.get('items_json', '[]')
        
        try:
            items = json.loads(items_json)
            if not isinstance(items, list):
                items = []
                json_error = 'Некорректный формат списка товаров'
        except Exception as e:
            json_error = f'Ошибка при чтении списка товаров: {str(e)}'
            print(f"JSON decode error: {e}\nOriginal JSON: {items_json}")

        # Для уже принятых товаров получаем информацию о ячейках из базы
        for item in items:
            if item.get('accepted', False) and 'location_id' in item:
                cursor.execute("""
                    SELECT location_name 
                    FROM Locations 
                    WHERE location_id = ?
                """, (item['location_id'],))
                location = cursor.fetchone()
                if location:
                    item['location_name'] = location.location_name

        delivery_data = {
            'delivery_id': delivery.get('delivery_id'),
            'supplier_name': delivery.get('supplier_name'),
            'delivery_date': delivery.get('delivery_date'),
            'status': delivery.get('status'),
            'delivery_items': items,  
            'items_count': len(items),
            'items_json': items_json
        }
        
        template = render_template('staff/staff_delivery_details.html', 
                                 delivery=delivery_data,
                                 error=json_error)
        return template
        
    except Exception as e:
        if conn:
            conn.rollback()
        return render_template('staff/staff_delivery_details.html',
                            error=f'Ошибка при обработке данных: {str(e)}',
                            delivery=None)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        
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

@staff_bp.route('/outbound/<int:outbound_id>')
def staff_outbound_details(outbound_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get outbound delivery details
    cursor.execute("""
        SELECT 
            outbound_id, 
            destination_address, 
            FORMAT(delivery_date, 'dd.MM.yyyy') as delivery_date, 
            status, 
            item_list as items_json,
            recipient_type,
            recipient_name,
            contact_info
        FROM Outbound_Deliveries
        WHERE outbound_id = ?
    """, (outbound_id,))
    
    row = cursor.fetchone()
    if not row:
        conn.close()
        return render_template('staff/staff_outbound_details.html', 
                            error='Возвратная поставка не найдена',
                            outbound=None)

    # Process outbound data
    columns = [column[0] for column in cursor.description]
    outbound = dict(zip(columns, row))
    
    try:
        items = json.loads(outbound['items_json'])
        if not isinstance(items, list):
            items = []
    except:
        items = []
    
    # Get full item details for each item in the outbound
    detailed_items = []
    for item in items:
        if 'item_id' in item:
            cursor.execute("""
                SELECT I.item_id, I.item_name, I.article_code, I.price, 
                    I.weight, I.size, I.item_type, I.supplier_id,
                    S.supplier_name, L.location_name
                FROM Items I
                LEFT JOIN Suppliers S ON I.supplier_id = S.supplier_id
                LEFT JOIN Item_Locations IL ON I.item_id = IL.item_id
                LEFT JOIN Locations L ON IL.location_id = L.location_id
                WHERE I.item_id = ?
            """, (item['item_id'],))
            
            item_row = cursor.fetchone()
            if item_row:
                item_columns = [column[0] for column in cursor.description]
                item_details = dict(zip(item_columns, item_row))
                detailed_items.append(item_details)

    # Ensure items is always a list
    outbound['items'] = detailed_items
    outbound['items_count'] = len(detailed_items)
    
    conn.close()
    
    return render_template(
        'staff/staff_outbound_details.html',
        outbound=outbound,
        error=None
    )

@staff_bp.route('/outbound/<int:outbound_id>/ship', methods=['POST'])
def ship_outbound(outbound_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get outbound items
        cursor.execute("""
            SELECT item_list FROM Outbound_Deliveries 
            WHERE outbound_id = ? AND status = 'preparing'
        """, (outbound_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return "Outbound delivery not found or already processed", 404

        items = json.loads(row.item_list)
        
        # Update status of each item to 'shipped'
        for item in items:
            if 'item_id' in item:
                cursor.execute("""
                    UPDATE Items SET status = 'shipped'
                    WHERE item_id = ?
                """, (item['item_id'],))
                
                # Log the transaction
                cursor.execute("""
                    INSERT INTO Inventory_Transactions 
                    (user_id, item_id, transaction_type)
                    VALUES (?, ?, 'ship')
                """, (session['user_id'], item['item_id']))
        
        # Update outbound status
        cursor.execute("""
            UPDATE Outbound_Deliveries 
            SET status = 'shipped'
            WHERE outbound_id = ?
        """, (outbound_id,))
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        return f"Error shipping outbound: {str(e)}", 500
    finally:
        conn.close()

    return redirect(url_for('staff.staff_outbound_details', outbound_id=outbound_id))

@staff_bp.route('/outbound/<int:outbound_id>/cancel', methods=['POST'])
def cancel_outbound(outbound_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Update outbound status to cancelled
        cursor.execute("""
            UPDATE Outbound_Deliveries 
            SET status = 'cancelled'
            WHERE outbound_id = ? AND status = 'preparing'
        """, (outbound_id,))
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        return f"Error cancelling outbound: {str(e)}", 500
    finally:
        conn.close()

    return redirect(url_for('staff.staff_outbound_details', outbound_id=outbound_id))

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