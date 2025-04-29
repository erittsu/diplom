# create_admin.py
import bcrypt

password = 'adminpassword123'
hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

print(hashed.decode('utf-8'))
