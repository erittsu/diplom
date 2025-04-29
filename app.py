from flask import Flask, render_template, request, redirect, session, flash
import pyodbc
import bcrypt

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

# Страница логина
@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, password, role FROM Users WHERE username = ?", username)
        user = cursor.fetchone()
        conn.close()

        if user and bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
            session['user_id'] = user.user_id
            session['username'] = username
            session['role'] = user.role
            return redirect('/dashboard')  # или главная страница
        else:
            flash('Неверный логин или пароль', 'error')

    return render_template('login.html')

# Страница регистрации
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

# Заглушка панели
@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect('/login')
    return f"Добро пожаловать, {session['username']}! Ваша роль: {session['role']}"

if __name__ == '__main__':
    app.run(debug=True)