from flask import Blueprint, render_template, session, redirect, request, url_for
import pyodbc
import json

supplier_bp = Blueprint('supplier', __name__)

def get_db_connection():
    return pyodbc.connect(
        r'DRIVER={ODBC Driver 17 for SQL Server};'
        r'Server=WIN-EPU1AR2HMUO;'
        r'DATABASE=warehouse;'
        r'UID=flask_user;'
        r'PWD=elich3258;'
    )

def get_supplier_id():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT supplier_id FROM Suppliers WHERE supplier_login = ?", (session['username'],))
    supplier_id = cursor.fetchone()[0]
    conn.close()
    return supplier_id

@supplier_bp.route('/')
def supplier_dashboard():
    if 'username' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    supplier_id = get_supplier_id()

    # Статистика по поставкам
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending_count,
            SUM(CASE WHEN status = 'received' THEN 1 ELSE 0 END) as received_count
        FROM Deliveries
        WHERE supplier_id = ?
    """, (supplier_id,))
    counts = cursor.fetchone()

    # Статистика по товарам
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) as in_stock,
            SUM(CASE WHEN status = 'to outbound' THEN 1 ELSE 0 END) as to_outbound
        FROM Items
        WHERE supplier_id = ?
    """, (supplier_id,))
    items_stats = cursor.fetchone()

    # Последние 5 поставок
    cursor.execute("""
        SELECT TOP 5 delivery_id, delivery_date, status 
        FROM Deliveries 
        WHERE supplier_id = ?
        ORDER BY delivery_date DESC
    """, (supplier_id,))
    recent_deliveries = cursor.fetchall()

    # Последние 5 добавленных товаров
    cursor.execute("""
        SELECT TOP 5 item_id, item_name, article_code, item_type, status, created_date
        FROM Items
        WHERE supplier_id = ?
        ORDER BY created_date DESC
    """, (supplier_id,))
    recent_items = cursor.fetchall()

    conn.close()

    return render_template('supplier/supplier_dashboard.html',
                         pending_deliveries_count=counts.pending_count or 0,
                         received_deliveries_count=counts.received_count or 0,
                         items_in_stock=items_stats.in_stock or 0,
                         items_to_outbound=items_stats.to_outbound or 0,
                         recent_deliveries=recent_deliveries,
                         recent_items=recent_items)

@supplier_bp.route('/deliveries')
def supplier_deliveries():
    if 'username' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    status_filter = request.args.get('status')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    conn = get_db_connection()
    cursor = conn.cursor()
    supplier_id = get_supplier_id()
    
    query = """
        SELECT 
            D.delivery_id, 
            D.delivery_date, 
            D.status,
            (SELECT COUNT(*) FROM OPENJSON(D.item_list)) as items_count
        FROM Deliveries D
        WHERE D.supplier_id = ?
    """
    params = [supplier_id]

    if status_filter and status_filter != 'all':
        query += " AND D.status = ?"
        params.append(status_filter)

    if start_date and end_date:
        query += " AND D.delivery_date BETWEEN ? AND ?"
        params.extend([start_date, end_date])

    query += " ORDER BY D.delivery_date DESC"
    cursor.execute(query, params)
    deliveries = cursor.fetchall()
    conn.close()

    return render_template('supplier/supplier_deliveries.html', 
                         deliveries=deliveries,
                         status_filter=status_filter)

@supplier_bp.route('/create-delivery', methods=['GET', 'POST'])
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
        return render_template('supplier/supplier_create_delivery.html', supplier=supplier)

    # POST handling
    delivery_date = request.form.get('delivery_date')
    delivery_items = request.form.get('delivery_items')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        supplier_id = get_supplier_id()
        
        # Validate and clean JSON - keep only required fields
        items_data = json.loads(delivery_items)
        cleaned_items = []
        for item in items_data:
            # Создаем новый объект только с необходимыми полями
            cleaned_item = {
                'item_name': str(item.get('item_name', '')),
                'article_code': str(item.get('article_code', '')),
                'price': float(item.get('price', 0)),
                'weight': float(item.get('weight', 0)),
                'size': str(item.get('size', '')),
                'type': str(item.get('type', 'обычный'))
            }
            cleaned_items.append(cleaned_item)
        
        # Двойное преобразование для гарантии чистоты данных
        cleaned_json = json.dumps(cleaned_items, ensure_ascii=False, indent=2)
        cleaned_data = json.loads(cleaned_json)  # Проверка корректности
        final_json = json.dumps(cleaned_data, ensure_ascii=False)
        
        cursor.execute("""
            INSERT INTO Deliveries (supplier_id, delivery_date, status, item_list)
            VALUES (?, ?, 'pending', ?)
        """, (supplier_id, delivery_date, final_json))
        conn.commit()
        
        # Log the transaction
        cursor.execute("""
            INSERT INTO Inventory_Transactions (user_id, transaction_type)
            VALUES ((SELECT user_id FROM Users WHERE username = ?), 'create_delivery')
        """, (session['username'],))
        conn.commit()
        
    except (pyodbc.IntegrityError, json.JSONDecodeError, ValueError) as e:
        conn.rollback()
        return f"Ошибка при добавлении: {e}", 400
    finally:
        conn.close()

    return redirect(url_for('supplier.supplier_deliveries'))

@supplier_bp.route('/delivery/<int:delivery_id>')
def delivery_details(delivery_id):
    if 'username' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    supplier_id = get_supplier_id()
    
    cursor.execute("""
        SELECT 
            D.delivery_id, 
            D.delivery_date, 
            D.status, 
            D.item_list as items_json,
            (SELECT COUNT(*) FROM OPENJSON(D.item_list)) as items_count
        FROM Deliveries D
        WHERE D.delivery_id = ? AND D.supplier_id = ?
    """, (delivery_id, supplier_id))
    delivery = cursor.fetchone()
    conn.close()

    if not delivery:
        return "Поставка не найдена или доступ запрещён", 404

    try:
        delivery_items = json.loads(delivery.items_json)
        # Преобразуем JSON в список словарей для удобства работы в шаблоне
        items = []
        for item in delivery_items:
            items.append({
                'item_name': item.get('item_name', ''),
                'article_code': item.get('article_code', ''),
                'type': item.get('type', ''),
                'price': item.get('price', 0),
                'weight': item.get('weight', 0),
                'size': item.get('size', ''),
                'accepted': item.get('accepted', False),  # По умолчанию товар не принят
                'location_name': item.get('location_name', '')  # По умолчанию нет ячейки
            })
    except json.JSONDecodeError as e:
        items = []
        error = f"Ошибка декодирования списка товаров: {str(e)}"

    return render_template(
        'supplier/supplier_delivery_details.html',
        delivery=delivery,
        delivery_items=items,
        error=error if 'error' in locals() else None
    )


@supplier_bp.route('/cancel-delivery/<int:delivery_id>', methods=['POST'])
def cancel_delivery(delivery_id): 
    if 'username' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    supplier_id = get_supplier_id()
    
    # First check if the delivery exists and belongs to this supplier
    cursor.execute("""
        SELECT status, item_list FROM Deliveries
        WHERE delivery_id = ? AND supplier_id = ?
    """, (delivery_id, supplier_id))
    delivery = cursor.fetchone()
    
    if not delivery:
        conn.close()
        return "Поставка не найдена или доступ запрещён", 404
    
    if delivery.status != 'pending':
        conn.close()
        return "Можно отменять только ожидающие поставки", 400
    
    try:
        # Update delivery status to cancelled
        cursor.execute("""
            UPDATE Deliveries
            SET status = 'cancelled'
            WHERE delivery_id = ? AND status = 'pending' AND supplier_id = ?
        """, (delivery_id, supplier_id))
        
        if cursor.rowcount == 0:
            conn.rollback()
            conn.close()
            return "Не удалось отменить поставку", 400
        
        # Update status of all items in this delivery
        # First parse the item_list JSON to get article codes
        item_list = json.loads(delivery.item_list)
        article_codes = [item.get('article_code') for item in item_list if item.get('article_code')]
        
        if article_codes:
            # Update items status to 'cancelled' (assuming you have this status in your Items table)
            cursor.execute("""
                UPDATE Items
                SET status = 'cancelled'
                WHERE article_code IN ({}) AND supplier_id = ?
            """.format(','.join(['?']*len(article_codes))), article_codes + [supplier_id])
        
        # Log the transaction
        cursor.execute("""
            INSERT INTO Inventory_Transactions (user_id, transaction_type)
            VALUES ((SELECT user_id FROM Users WHERE username = ?), 'remove')
        """, (session['username'],))
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        return f"Ошибка при отмене поставки: {str(e)}", 500
    finally:
        conn.close()
    
    return redirect(url_for('supplier.supplier_deliveries'))

@supplier_bp.route('/outbound')
def supplier_outbound():
    if 'username' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get supplier name
    cursor.execute("SELECT supplier_name FROM Suppliers WHERE supplier_login = ?", (session['username'],))
    supplier_name = cursor.fetchone()[0]
    
    # Get outbound deliveries for this supplier
    cursor.execute("""
        SELECT outbound_id, delivery_date, status, recipient_type
        FROM Outbound_Deliveries
        WHERE recipient_type = 'supplier' AND recipient_name = ?
        ORDER BY delivery_date DESC
    """, (supplier_name,))
    outbound_deliveries = cursor.fetchall()
    
    conn.close()
    return render_template('supplier/supplier_outbound.html', outbound_deliveries=outbound_deliveries)

@supplier_bp.route('/outbound/<int:outbound_id>')
def outbound_details(outbound_id):
    if 'username' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get supplier name
    cursor.execute("SELECT supplier_name FROM Suppliers WHERE supplier_login = ?", (session['username'],))
    supplier_name = cursor.fetchone()[0]
    
    cursor.execute(""" 
        SELECT outbound_id, delivery_date, status, item_list, recipient_type, contact_info
        FROM Outbound_Deliveries
        WHERE outbound_id = ? AND recipient_type = 'supplier' AND recipient_name = ?
    """, (outbound_id, supplier_name))
    delivery = cursor.fetchone()
    conn.close()

    if not delivery:
        return "Отгрузка не найдена или доступ запрещён", 404

    try:
        items_data = json.loads(delivery.item_list)
        # Преобразуем данные в удобный формат для шаблона
        items = []
        for item in items_data:items.append({
                        'product_id': item.get('item_id'), 
                        'product_name': item.get('item_name'),
                        'article_code': item.get('article_code'),
                        'item_type': item.get('item_type'),
                        'size': item.get('size'),
                        'weight': item.get('weight'),
                        'price': item.get('price'),
                        'status': item.get('status', 'to send')  # Добавляем значение по умолчанию
                    })
    except json.JSONDecodeError as e:
        items = []
        error = f"Ошибка декодирования списка товаров: {str(e)}"

    return render_template(
        'supplier/supplier_outbound_details.html', 
        delivery=delivery,
        items=items,
        error=error if 'error' in locals() else None
    )

@supplier_bp.route('/create-outbound', methods=['GET', 'POST'])
def create_outbound():
    if 'username' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    if request.method == 'GET':
        conn = get_db_connection()
        cursor = conn.cursor()
        supplier_id = get_supplier_id()
        
        # Get items available for return (status = 'to outbound')
        cursor.execute("""
            SELECT item_id, item_name, article_code, price, weight, size, item_type, status, created_date
            FROM Items
            WHERE supplier_id = ? AND status = 'to outbound'
        """, (supplier_id,))
        available_items = cursor.fetchall()
        
        # Get supplier info for default contact info
        cursor.execute("""
            SELECT supplier_name, contact_info 
            FROM Suppliers 
            WHERE supplier_id = ?
        """, (supplier_id,))
        supplier = cursor.fetchone()
        conn.close()
        
        return render_template('supplier/supplier_create_outbound.html', 
                            available_items=available_items,
                            supplier=supplier)

    # POST handling
    destination_address = request.form.get('destination_address')
    contact_info = request.form.get('contact_info')
    selected_items = request.form.getlist('selected_items')
    
    if not selected_items:
        return "Не выбраны товары для возврата", 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    supplier_id = get_supplier_id()
    
    try:
        # Get supplier name
        cursor.execute("SELECT supplier_name FROM Suppliers WHERE supplier_id = ?", (supplier_id,))
        supplier_name = cursor.fetchone()[0]
        
        # Get selected items details with all available information
        cursor.execute(f"""
            SELECT 
                i.item_id, 
                i.item_name, 
                i.article_code, 
                i.price, 
                i.weight, 
                i.size, 
                i.item_type,
                i.status,
                i.created_date,
                l.location_name
            FROM Items i
            LEFT JOIN Item_Locations il ON i.item_id = il.item_id
            LEFT JOIN Locations l ON il.location_id = l.location_id
            WHERE i.item_id IN ({','.join(['?']*len(selected_items))})
        """, selected_items)
        items = cursor.fetchall()
        
        # Prepare item list JSON with all item information
        item_list = []
        for item in items:
            item_data = {
                'item_id': item.item_id,
                'item_name': item.item_name,
                'article_code': item.article_code,
                'price': float(item.price),
                'weight': float(item.weight) if item.weight else None,
                'size': item.size,
                'item_type': item.item_type,
                'status': item.status,
                'created_date': item.created_date.strftime('%Y-%m-%d %H:%M:%S') if item.created_date else None,
                'location_name': item.location_name
            }
            item_list.append(item_data)
        
        # Insert outbound delivery with complete item information
        cursor.execute("""
            INSERT INTO Outbound_Deliveries (
                destination_address,
                status,
                item_list,
                recipient_type,
                recipient_name,
                contact_info
            )
            VALUES (?, 'preparing', ?, 'supplier', ?, ?)
        """, (
            destination_address,
            json.dumps(item_list, ensure_ascii=False),
            supplier_name,
            contact_info
        ))
        
        # Update items status from 'to outbound' to 'to send'
        cursor.execute(f"""
            UPDATE Items
            SET status = 'to send'
            WHERE item_id IN ({','.join(['?']*len(selected_items))})
        """, selected_items)
        
        # Log the transaction
        cursor.execute("""
            INSERT INTO Inventory_Transactions (user_id, transaction_type)
            VALUES ((SELECT user_id FROM Users WHERE username = ?), 'create_outbound')
        """, (session['username'],))
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        return f"Ошибка при создании возвратной поставки: {str(e)}", 500
    finally:
        conn.close()
    
    return redirect(url_for('supplier.supplier_outbound'))

@supplier_bp.route('/mark-for-return/<int:item_id>', methods=['POST'])
def mark_for_return(item_id):
    if 'username' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    supplier_id = get_supplier_id()
    
    try:
        # Verify item belongs to this supplier
        cursor.execute("""
            SELECT 1 FROM Items 
            WHERE item_id = ? AND supplier_id = ?
        """, (item_id, supplier_id))
        if not cursor.fetchone():
            return "Товар не найден или не принадлежит вам", 404
        
        # Update item status to 'to outbound'
        cursor.execute("""
            UPDATE Items
            SET status = 'to outbound'
            WHERE item_id = ?
        """, (item_id,))
        
        # Log the transaction - используем одно из разрешенных значений
        cursor.execute("""
            INSERT INTO Inventory_Transactions (user_id, transaction_type)
            VALUES ((SELECT user_id FROM Users WHERE username = ?), 'create_outbound')
        """, (session['username'],))
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        return f"Ошибка при обновлении статуса товара: {str(e)}", 500
    finally:
        conn.close()
    
    return redirect(url_for('supplier.supplier_items'))

@supplier_bp.route('/items')
def supplier_items():
    if 'username' not in session or session.get('role') != 'supplier':
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    supplier_id = get_supplier_id()
    
    cursor.execute("""
        SELECT i.item_id, i.item_name, i.article_code, i.price, i.status, 
               l.location_name, i.created_date
        FROM Items i
        LEFT JOIN Item_Locations il ON i.item_id = il.item_id
        LEFT JOIN Locations l ON il.location_id = l.location_id
        WHERE i.supplier_id = ?
        ORDER BY i.created_date DESC
    """, (supplier_id,))
    items = cursor.fetchall()
    
    conn.close()
    return render_template('supplier/supplier_items.html', items=items)