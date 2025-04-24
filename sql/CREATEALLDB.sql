-- ================================
-- Структура базы данных склада (обновлённая)
-- ================================

-- 1. Пользователи (логины, роли)
CREATE TABLE Users (
    user_id INT IDENTITY(1,1) PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(100) NOT NULL,
    role VARCHAR(20) DEFAULT 'user' -- user, admin
);
-- Используется для авторизации и логирования действий

-- 2. Поставщики
CREATE TABLE Suppliers (
    supplier_id INT IDENTITY(1,1) PRIMARY KEY,
    supplier_name VARCHAR(100) NOT NULL,
    contact_info VARCHAR(100),
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'suspended'))
);
-- Хранит информацию о поставщиках

-- 3. Поставки
CREATE TABLE Deliveries (
    delivery_id INT IDENTITY(1,1) PRIMARY KEY,
    supplier_id INT NOT NULL,
    delivery_date DATE DEFAULT GETDATE(),
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'received', 'cancelled')),
    item_list NVARCHAR(MAX) NOT NULL CHECK (ISJSON(item_list) > 0), -- JSON-объект со списком товаров
    created_by INT NOT NULL,
    FOREIGN KEY (supplier_id) REFERENCES Suppliers(supplier_id),
    FOREIGN KEY (created_by) REFERENCES Users(user_id)
);
-- JSON вида: [{"item_name": "Бутылка воды", "article_code": "BW123", "price": 12.50, "weight": 10.0, "size": "30x30x40", "type": "жидкий"}, {...}]

-- 4. Товары
CREATE TABLE Items (
    item_id INT IDENTITY(1,1) PRIMARY KEY,
    item_name VARCHAR(100) NOT NULL,
    article_code VARCHAR(50) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    weight DECIMAL(10,2),
    size VARCHAR(50), -- пример: "30x30x40"
    item_type VARCHAR(30) CHECK (item_type IN ('хрупкий', 'жидкий', 'крупногабаритный')),
    status VARCHAR(20) DEFAULT 'accepted' CHECK (status IN ('accepted', 'shipped')),
    created_by INT NOT NULL,
    FOREIGN KEY (created_by) REFERENCES Users(user_id)
);
-- Каждая единица товара — отдельная запись

-- 5. Ячейки склада
CREATE TABLE Locations (
    location_id INT IDENTITY(1,1) PRIMARY KEY,
    location_name VARCHAR(50) NOT NULL UNIQUE
);
-- Статус занятости будет рассчитываться через представление

-- 6. Размещение товара в ячейку
CREATE TABLE Item_Locations (
    item_location_id INT IDENTITY(1,1) PRIMARY KEY,
    item_id INT NOT NULL,
    location_id INT NOT NULL,
    placed_date DATETIME DEFAULT GETDATE(),
    placed_by INT NOT NULL,
    FOREIGN KEY (item_id) REFERENCES Items(item_id),
    FOREIGN KEY (location_id) REFERENCES Locations(location_id),
    FOREIGN KEY (placed_by) REFERENCES Users(user_id)
);
-- Показывает, в какой ячейке находится товар

-- 7. Отгрузки (исходящие поставки)
CREATE TABLE Outbound_Deliveries (
    outbound_id INT IDENTITY(1,1) PRIMARY KEY,
    destination_address VARCHAR(255) NOT NULL,
    delivery_date DATE DEFAULT GETDATE(),
    status VARCHAR(20) DEFAULT 'preparing' CHECK (status IN ('preparing', 'shipped', 'cancelled')),
    item_list NVARCHAR(MAX) NOT NULL CHECK (ISJSON(item_list) > 0), -- JSON-объект со списком отгружаемых товаров
    created_by INT NOT NULL,
    FOREIGN KEY (created_by) REFERENCES Users(user_id)
);
-- JSON вида: [{"item_id": 123, "article_code": "BW123"}, {...}]

-- 8. Журнал операций (все действия пользователей)
CREATE TABLE Inventory_Transactions (
    transaction_id INT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NOT NULL,
    item_id INT,
    location_id INT,
    transaction_type VARCHAR(20) NOT NULL CHECK (transaction_type IN ('add', 'remove', 'move', 'ship', 'place', 'receive_delivery', 'create_delivery', 'create_outbound', 'receive_outbound')),
    transaction_date DATETIME DEFAULT GETDATE(),
    FOREIGN KEY (user_id) REFERENCES Users(user_id),
    FOREIGN KEY (item_id) REFERENCES Items(item_id),
    FOREIGN KEY (location_id) REFERENCES Locations(location_id)
);
-- Лог всех действий: кто, что, куда

-- ================================
-- Описание структуры:
-- ================================
-- Users               - пользователи системы
-- Suppliers           - поставщики, от кого приходят поставки
-- Deliveries          - поставки от поставщиков, с JSON-списком товаров (валидный JSON)
-- Items               - каждый товар как отдельная запись
-- Locations           - ячейки склада
-- Item_Locations      - связь товара с ячейкой
-- Outbound_Deliveries - отгрузка куда-либо, JSON-список отгружаемых товаров (валидный JSON)
-- Inventory_Transactions - логирование всех действий пользователей
