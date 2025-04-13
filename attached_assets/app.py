import os
import sqlite3
from datetime import datetime
from flask import Flask, request, render_template, send_file, redirect, url_for, abort, after_this_request, jsonify
import tempfile
from werkzeug.utils import secure_filename
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
import io

app = Flask(__name__, template_folder="templates", static_folder="static")
DB_FILE = "accounting.db"

# Initialize database
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Accounting tables
        cursor.execute('''CREATE TABLE IF NOT EXISTS accounts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT UNIQUE NOT NULL,
                            balance REAL DEFAULT 0
                          )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            date TEXT,
                            account_id INTEGER,
                            description TEXT,
                            debit REAL,
                            credit REAL,
                            FOREIGN KEY(account_id) REFERENCES accounts(id)
                          )''')
        
        # Inventory tables
        cursor.execute('''CREATE TABLE IF NOT EXISTS inventory (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT NOT NULL,
                            quantity INTEGER DEFAULT 0,
                            price REAL DEFAULT 0,
                            category TEXT,
                            supplier TEXT,
                            expiry_date TEXT,
                            barcode TEXT UNIQUE,
                            sold INTEGER DEFAULT 0,
                            remaining INTEGER DEFAULT 0,
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP
                          )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS inventory_transactions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            date TEXT,
                            item_id INTEGER,
                            type TEXT,  -- 'purchase' or 'sale'
                            quantity INTEGER,
                            unit_price REAL,
                            total_value REAL,
                            FOREIGN KEY(item_id) REFERENCES inventory(id)
                          )''')
        
        # Asset tables
        cursor.execute('''CREATE TABLE IF NOT EXISTS assets (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT NOT NULL,
                            purchase_price REAL NOT NULL,
                            useful_life INTEGER NOT NULL,
                            depreciation_method TEXT NOT NULL,
                            annual_depreciation REAL NOT NULL,
                            sale_price REAL,
                            gain_loss REAL,
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP
                          )''')
        
        # Accounts Receivable table
        cursor.execute('''CREATE TABLE IF NOT EXISTS receivables (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            customer_name TEXT NOT NULL,
                            invoice_number TEXT UNIQUE NOT NULL,
                            amount REAL NOT NULL,
                            date_issued TEXT NOT NULL,
                            due_date TEXT NOT NULL,
                            date_paid TEXT,
                            status TEXT DEFAULT 'open',  -- 'open', 'paid', 'overdue'
                            account_id INTEGER,
                            FOREIGN KEY(account_id) REFERENCES accounts(id)
                          )''')
        
        conn.commit()

# Helper functions
def insert_transaction(cursor, date, account_id, description, debit, credit):
    cursor.execute("INSERT INTO transactions (date, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
                   (date, account_id, description, debit, credit))
    cursor.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (debit - credit, account_id))

def validate_date(date_str):
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return None

def validate_amount(amount_str):
    try:
        return float(amount_str)
    except ValueError:
        return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'xlsx', 'xls', 'csv'}

@app.route('/search', methods=['GET'])
def search():
    search_term = request.args.get('q', '').strip()
    results = []
    
    if search_term:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # Search accounts
            cursor.execute("SELECT id, name FROM accounts WHERE name LIKE ?", 
                         (f'%{search_term}%',))
            account_results = [{'type': 'account', 'id': row[0], 'name': row[1]} 
                             for row in cursor.fetchall()]
            
            # Search transactions
            cursor.execute('''SELECT t.id, t.description, a.name 
                            FROM transactions t 
                            JOIN accounts a ON t.account_id = a.id 
                            WHERE t.description LIKE ?''',
                         (f'%{search_term}%',))
            transaction_results = [{'type': 'transaction', 'id': row[0], 'description': row[1], 'account': row[2]} 
                                for row in cursor.fetchall()]
            
            # Search inventory
            cursor.execute("SELECT id, name FROM inventory WHERE name LIKE ?", 
                         (f'%{search_term}%',))
            inventory_results = [{'type': 'inventory', 'id': row[0], 'name': row[1]} 
                              for row in cursor.fetchall()]
            
            # Search assets
            cursor.execute("SELECT id, name FROM assets WHERE name LIKE ?", 
                         (f'%{search_term}%',))
            asset_results = [{'type': 'asset', 'id': row[0], 'name': row[1]} 
                          for row in cursor.fetchall()]
            
            # Search receivables
            cursor.execute("SELECT id, customer_name FROM receivables WHERE customer_name LIKE ? OR invoice_number LIKE ?", 
                         (f'%{search_term}%', f'%{search_term}%'))
            receivable_results = [{'type': 'receivable', 'id': row[0], 'name': row[1]} 
                              for row in cursor.fetchall()]
            
            results = account_results + transaction_results + inventory_results + asset_results + receivable_results
    
    return render_template("search_results.html", 
                         results=results, 
                         search_term=search_term)

# Accounting routes
@app.route('/')
def index():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT a.id, a.name, a.balance, MAX(t.date) as last_updated
                          FROM accounts a
                          LEFT JOIN transactions t ON a.id = t.account_id
                          GROUP BY a.id''')
        accounts = cursor.fetchall()
    return render_template("index.html", accounts=accounts)

@app.route('/home')
def home():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM accounts")
        total_accounts = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM transactions")
        total_transactions = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(balance) FROM accounts")
        total_balance = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM inventory")
        total_inventory = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM assets")
        total_assets = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM receivables")
        total_receivables = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(amount) FROM receivables WHERE status != 'paid'")
        outstanding_receivables = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM transactions WHERE description LIKE '%check%'")
        total_checks = cursor.fetchone()[0]
    
    return render_template("home.html", 
                         total_accounts=total_accounts, 
                         total_transactions=total_transactions, 
                         total_balance=total_balance,
                         total_inventory=total_inventory,
                         total_assets=total_assets,
                         total_receivables=total_receivables,
                         outstanding_receivables=outstanding_receivables,
                         total_checks=total_checks)  # Add this line
@app.route('/journal_entry', methods=['GET', 'POST'])
def journal_entry():
    if request.method == 'POST':
        date = request.form.get('date')
        debit_accounts = request.form.getlist('debit_account')
        debit_amounts = request.form.getlist('debit_amount')
        debit_descriptions = request.form.getlist('debit_description')
        credit_accounts = request.form.getlist('credit_account')
        credit_amounts = request.form.getlist('credit_amount')
        credit_descriptions = request.form.getlist('credit_description')

        date = validate_date(date)
        if not date:
            return "Invalid date format. Use YYYY-MM-DD.", 400

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            try:
                for account_id, amount, description in zip(debit_accounts, debit_amounts, debit_descriptions):
                    amount = validate_amount(amount)
                    if amount is not None:
                        insert_transaction(cursor, date, account_id, description, amount, 0)
                
                for account_id, amount, description in zip(credit_accounts, credit_amounts, credit_descriptions):
                    amount = validate_amount(amount)
                    if amount is not None:
                        insert_transaction(cursor, date, account_id, description, 0, amount)
                
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                return f"An error occurred: {str(e)}", 500

        return redirect(url_for('index'))
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM accounts")
        accounts = cursor.fetchall()
    return render_template("journal_entry.html", accounts=accounts)

@app.route('/create_account', methods=['GET', 'POST'])
def create_account():
    if request.method == 'POST':
        name = request.form.get('name')
        if not name:
            return "Account name cannot be empty.", 400

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO accounts (name) VALUES (?)", (name,))
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                return "Account name already exists.", 400

        return redirect(url_for('index'))
    return render_template("create_account.html")

@app.route('/delete_account/<int:account_id>', methods=['POST'])
def delete_account(account_id):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            cursor.execute("DELETE FROM transactions WHERE account_id = ?", (account_id,))
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            return f"An error occurred: {str(e)}", 500

    return redirect(url_for('index'))

@app.route('/account/<int:account_id>')
def account_details(account_id):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, balance FROM accounts WHERE id = ?", (account_id,))
        account = cursor.fetchone()
        
        if not account:
            return "Account not found.", 404

        cursor.execute('''SELECT date, description, debit, credit
                          FROM transactions
                          WHERE account_id = ?
                          ORDER BY date''', (account_id,))
        transactions = cursor.fetchall()
    
    return render_template("account_details.html", account=account, transactions=transactions)

@app.route('/add_transaction_page', methods=['GET', 'POST'])
def add_transaction_page():
    if request.method == 'POST':
        date = request.form.get('date')
        description = request.form.get('description')
        amount = request.form.get('amount')
        category = request.form.get('category')
        account_id = request.form.get('account')

        date = validate_date(date)
        if not date:
            return "Invalid date format. Use YYYY-MM-DD.", 400

        amount = validate_amount(amount)
        if amount is None:
            return "Invalid amount.", 400

        if category not in ["Debit", "Credit"]:
            return "Invalid transaction category.", 400

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            try:
                if category == "Debit":
                    insert_transaction(cursor, date, account_id, description, amount, 0)
                elif category == "Credit":
                    insert_transaction(cursor, date, account_id, description, 0, amount)
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                return f"An error occurred: {str(e)}", 500

        return redirect(url_for('index'))
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, balance FROM accounts")
        accounts = cursor.fetchall()
    return render_template("add_transaction.html", accounts=accounts)

@app.route('/download_journal_report', methods=['GET'])
def download_journal_report():
    account_ids = request.args.getlist('account_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    if not account_ids:
        return "No accounts selected for the report.", 400

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        query = '''SELECT t.date, a.name, t.description, t.debit, t.credit
                   FROM transactions t
                   JOIN accounts a ON t.account_id = a.id
                   WHERE t.account_id IN ({})'''.format(','.join(['?'] * len(account_ids)))
        params = account_ids

        if start_date and end_date:
            query += " AND t.date BETWEEN ? AND ?"
            params.extend([start_date, end_date])
        elif start_date:
            query += " AND t.date >= ?"
            params.append(start_date)
        elif end_date:
            query += " AND t.date <= ?"
            params.append(end_date)

        query += " ORDER BY t.date"
        cursor.execute(query, tuple(params))
        journal_entries = cursor.fetchall()
    
    report_content = f"Journal Entries Report for Accounts: {', '.join(account_ids)}\n\n"
    if start_date or end_date:
        report_content += f"Date Range: {start_date or 'Start'} to {end_date or 'End'}\n\n"
    report_content += "Date\t\tAccount\t\tDescription\t\tDebit\t\tCredit\n"
    report_content += "-" * 80 + "\n"
    for entry in journal_entries:
        date, account, description, debit, credit = entry
        report_content += f"{date}\t{account}\t{description}\t{debit}\t{credit}\n"
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode='w') as temp_file:
        temp_file.write(report_content)
        temp_file_path = temp_file.name

    @after_this_request
    def cleanup(response):
        try:
            os.remove(temp_file_path)
        except Exception as e:
            app.logger.error(f"Error deleting temporary file: {e}")
        return response

    return send_file(temp_file_path, as_attachment=True, download_name="journal_report.txt")

@app.route('/download_pnl_report', methods=['GET'])
def download_pnl_report():
    account_id = request.args.get('account_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    if not account_id:
        return "No account selected for the report.", 400

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Get account info
        cursor.execute("SELECT name, balance FROM accounts WHERE id = ?", (account_id,))
        account_name, current_balance = cursor.fetchone()
        
        # Get transactions
        query = '''SELECT date, description, debit, credit 
                   FROM transactions 
                   WHERE account_id = ?'''
        params = [account_id]

        if start_date and end_date:
            query += " AND date BETWEEN ? AND ?"
            params.extend([start_date, end_date])
        elif start_date:
            query += " AND date >= ?"
            params.append(start_date)
        elif end_date:
            query += " AND date <= ?"
            params.append(end_date)

        query += " ORDER BY date"
        cursor.execute(query, tuple(params))
        transactions = cursor.fetchall()
        
        # Calculate totals
        total_debit = sum(t[2] for t in transactions)
        total_credit = sum(t[3] for t in transactions)
        net_profit_loss = total_debit - total_credit

    # Create PDF in memory
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    
    # Set up PDF styling
    pdf.setTitle(f"P&L Report - {account_name}")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(100, 750, f"Profit & Loss Report - {account_name}")
    
    pdf.setFont("Helvetica", 12)
    pdf.drawString(100, 730, f"Date Range: {start_date or 'Start'} to {end_date or 'End'}")
    pdf.drawString(100, 710, f"Current Balance: ${current_balance:.2f}")
    
    # Create transaction table
    data = [["Date", "Description", "Debit", "Credit"]]
    for t in transactions:
        data.append([
            t[0],
            t[1],
            f"${t[2]:.2f}",
            f"${t[3]:.2f}"
        ])
    
    # Add summary row
    data.append(["TOTALS:", "", f"${total_debit:.2f}", f"${total_credit:.2f}"])
    data.append(["NET PROFIT/LOSS:", "", f"${net_profit_loss:.2f}"])

    # Create table
    table = Table(data, colWidths=[100, 200, 80, 80])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 12),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-3), colors.beige),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('BACKGROUND', (0,-2), (-1,-1), colors.lightgrey),
        ('FONTNAME', (0,-2), (-1,-1), 'Helvetica-Bold'),
    ]))
    
    # Draw table
    table.wrapOn(pdf, 100, 650)
    table.drawOn(pdf, 100, 650 - len(data)*20)

    # Add footer
    pdf.setFont("Helvetica-Oblique", 10)
    pdf.drawString(100, 50, f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    pdf.showPage()
    pdf.save()
    
    # Return PDF
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"P&L_Report_{account_name.replace(' ', '_')}.pdf",
        mimetype='application/pdf'
    )

# Inventory routes
@app.route('/inventory')
def inventory():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM inventory")
        total_items = cursor.fetchone()[0]
    return render_template("inventory.html", total_items=total_items)

@app.route('/api/inventory', methods=['GET', 'POST'])
def inventory_api():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        if request.method == 'POST':
            data = request.get_json()
            try:
                cursor.execute('''INSERT INTO inventory 
                                (name, quantity, price, category, supplier, expiry_date, barcode, remaining)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                             (data['name'], data['quantity'], data['price'], 
                              data['category'], data['supplier'], 
                              data['expiryDate'], data['barcode'], data['quantity']))
                
                cursor.execute('''INSERT INTO inventory_transactions
                                (date, item_id, type, quantity, unit_price, total_value)
                                VALUES (datetime('now'), ?, 'purchase', ?, ?, ?)''',
                             (cursor.lastrowid, data['quantity'], data['price'], 
                              data['quantity'] * data['price']))
                
                conn.commit()
                return jsonify({"status": "success", "id": cursor.lastrowid})
            except sqlite3.IntegrityError:
                return jsonify({"status": "error", "message": "Barcode must be unique"}), 400
            except sqlite3.Error as e:
                return jsonify({"status": "error", "message": str(e)}), 500

        else:  # GET request
            cursor.execute("SELECT * FROM inventory ORDER BY name")
            items = [dict(zip([column[0] for column in cursor.description], row)) 
                    for row in cursor.fetchall()]
            return jsonify(items)

@app.route('/api/inventory/<int:item_id>', methods=['PUT', 'DELETE'])
def inventory_item(item_id):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        if request.method == 'PUT':
            data = request.get_json()
            sold_qty = data.get('sold', 0)
            
            if sold_qty <= 0:
                return jsonify({"status": "error", "message": "Quantity must be positive"}), 400
            
            cursor.execute("SELECT price FROM inventory WHERE id = ?", (item_id,))
            result = cursor.fetchone()
            if not result:
                return jsonify({"status": "error", "message": "Item not found"}), 404
            price = result[0]
            
            cursor.execute('''UPDATE inventory 
                            SET sold = sold + ?, 
                                remaining = remaining - ?
                            WHERE id = ? AND remaining >= ?''',
                         (sold_qty, sold_qty, item_id, sold_qty))
            
            if cursor.rowcount == 0:
                return jsonify({"status": "error", "message": "Not enough stock"}), 400
            
            cursor.execute('''INSERT INTO inventory_transactions
                            (date, item_id, type, quantity, unit_price, total_value)
                            VALUES (datetime('now'), ?, 'sale', ?, ?, ?)''',
                         (item_id, sold_qty, price, sold_qty * price))
            
            conn.commit()
            return jsonify({"status": "success"})
            
        elif request.method == 'DELETE':
            cursor.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
            cursor.execute("DELETE FROM inventory_transactions WHERE item_id = ?", (item_id,))
            conn.commit()
            return jsonify({"status": "success"})

@app.route('/inventory/report')
def inventory_report():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        cursor.execute('''SELECT 
                            COUNT(*) as total_items,
                            SUM(quantity * price) as total_value,
                            SUM(sold * price) as total_sold_value,
                            SUM(remaining * price) as total_remaining_value
                          FROM inventory''')
        summary = dict(zip([column[0] for column in cursor.description], cursor.fetchone()))
        
        cursor.execute("SELECT name, remaining FROM inventory WHERE remaining < 10 ORDER BY remaining")
        low_stock = [dict(zip([column[0] for column in cursor.description], row)) 
                    for row in cursor.fetchall()]
        
        cursor.execute('''SELECT i.name, t.date, t.type, t.quantity, t.unit_price, t.total_value
                          FROM inventory_transactions t
                          JOIN inventory i ON t.item_id = i.id
                          ORDER BY t.date DESC LIMIT 10''')
        recent_transactions = [dict(zip([column[0] for column in cursor.description], row)) 
                             for row in cursor.fetchall()]
    
    return render_template("inventory_report.html",
                         summary=summary,
                         low_stock=low_stock,
                         recent_transactions=recent_transactions,
                         now=datetime.now())

# Asset routes
@app.route('/assets')
def assets():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM assets")
        total_assets = cursor.fetchone()[0]
    return render_template("asset_keeper.html", total_assets=total_assets)

@app.route('/api/assets', methods=['GET', 'POST'])
def assets_api():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        if request.method == 'POST':
            data = request.get_json()
            try:
                # Calculate depreciation
                depreciation = 0
                if data['method'] == "straight-line":
                    depreciation = data['price'] / data['life']
                elif data['method'] == "double-declining":
                    depreciation = (2 / data['life']) * data['price']
                
                cursor.execute('''INSERT INTO assets 
                                (name, purchase_price, useful_life, depreciation_method, annual_depreciation)
                                VALUES (?, ?, ?, ?, ?)''',
                             (data['name'], data['price'], data['life'], 
                              data['method'], depreciation))
                
                conn.commit()
                return jsonify({"status": "success", "id": cursor.lastrowid})
            except sqlite3.Error as e:
                conn.rollback()
                return jsonify({"status": "error", "message": str(e)}), 500

        else:  # GET request
            cursor.execute("SELECT * FROM assets ORDER BY name")
            assets = [dict(zip([column[0] for column in cursor.description], row)) 
                     for row in cursor.fetchall()]
            return jsonify(assets)

@app.route('/api/assets/<int:asset_id>', methods=['PUT', 'DELETE'])
def asset_item(asset_id):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        if request.method == 'PUT':
            data = request.get_json()
            try:
                # Calculate gain/loss when selling
                cursor.execute("SELECT purchase_price, useful_life, annual_depreciation FROM assets WHERE id = ?", (asset_id,))
                asset = cursor.fetchone()
                
                if not asset:
                    return jsonify({"status": "error", "message": "Asset not found"}), 404
                
                purchase_price, useful_life, annual_depreciation = asset
                sale_price = data.get('sale_price', 0)
                book_value = purchase_price - (annual_depreciation * useful_life)
                gain_loss = sale_price - book_value
                
                cursor.execute('''UPDATE assets 
                                SET sale_price = ?,
                                    gain_loss = ?
                                WHERE id = ?''',
                             (sale_price, gain_loss, asset_id))
                
                conn.commit()
                return jsonify({"status": "success"})
            except sqlite3.Error as e:
                conn.rollback()
                return jsonify({"status": "error", "message": str(e)}), 500
            
        elif request.method == 'DELETE':
            try:
                cursor.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
                conn.commit()
                return jsonify({"status": "success"})
            except sqlite3.Error as e:
                conn.rollback()
                return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/assets/report')
def assets_report():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Get summary data
        cursor.execute('''SELECT 
                            COUNT(*) as total_assets,
                            SUM(purchase_price) as total_value,
                            SUM(sale_price) as total_sales,
                            SUM(gain_loss) as net_gain_loss
                          FROM assets''')
        summary = dict(zip([column[0] for column in cursor.description], cursor.fetchone()))
        
        # Get recent sales
        cursor.execute('''SELECT name, purchase_price, sale_price, gain_loss
                          FROM assets
                          WHERE sale_price IS NOT NULL
                          ORDER BY created_at DESC LIMIT 10''')
        recent_sales = [dict(zip([column[0] for column in cursor.description], row)) 
                       for row in cursor.fetchall()]
    
    return render_template("assets_report.html",
                         summary=summary,
                         recent_sales=recent_sales,
                         now=datetime.now())

# Accounts Receivable routes
@app.route('/receivables')
def receivables():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM receivables")
        total_receivables = cursor.fetchone()[0]
        
        cursor.execute('''SELECT SUM(amount) FROM receivables 
                          WHERE status = 'open' OR status = 'overdue' ''')
        total_outstanding = cursor.fetchone()[0] or 0
        
        cursor.execute('''SELECT SUM(amount) FROM receivables 
                          WHERE status = 'paid' ''')
        total_collected = cursor.fetchone()[0] or 0
        
    return render_template("receivables.html", 
                         total_receivables=total_receivables,
                         total_outstanding=total_outstanding,
                         total_collected=total_collected)

@app.route('/receivables/add', methods=['GET', 'POST'])
def add_receivable():
    if request.method == 'POST':
        customer_name = request.form.get('customer_name')
        invoice_number = request.form.get('invoice_number')
        amount = request.form.get('amount')
        date_issued = request.form.get('date_issued')
        due_date = request.form.get('due_date')
        account_id = request.form.get('account_id')

        # Validate inputs
        if not all([customer_name, invoice_number, amount, date_issued, due_date, account_id]):
            return "All fields are required", 400

        try:
            amount = float(amount)
            if amount <= 0:
                return "Amount must be positive", 400
        except ValueError:
            return "Invalid amount", 400

        if not validate_date(date_issued) or not validate_date(due_date):
            return "Invalid date format. Use YYYY-MM-DD.", 400

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            try:
                # Insert receivable
                cursor.execute('''INSERT INTO receivables 
                                (customer_name, invoice_number, amount, 
                                 date_issued, due_date, account_id)
                                VALUES (?, ?, ?, ?, ?, ?)''',
                             (customer_name, invoice_number, amount, 
                              date_issued, due_date, account_id))
                
                # Create journal entry (debit Accounts Receivable)
                insert_transaction(cursor, date_issued, account_id, 
                                  f"Invoice {invoice_number} to {customer_name}", 
                                  amount, 0)
                
                conn.commit()
            except sqlite3.IntegrityError:
                return "Invoice number already exists", 400
            except sqlite3.Error as e:
                return f"Database error: {str(e)}", 500

        return redirect(url_for('receivables'))
    
    # GET request - show form
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM accounts")
        accounts = cursor.fetchall()
    return render_template("add_receivable.html", accounts=accounts)

@app.route('/receivables/mark_paid/<int:receivable_id>', methods=['POST'])
def mark_receivable_paid(receivable_id):
    payment_date = request.form.get('payment_date')
    payment_account_id = request.form.get('payment_account_id')

    if not payment_date or not payment_account_id:
        return "Payment date and account are required", 400

    if not validate_date(payment_date):
        return "Invalid date format. Use YYYY-MM-DD.", 400

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        try:
            # Get receivable details
            cursor.execute('''SELECT amount, account_id, invoice_number, customer_name 
                             FROM receivables 
                             WHERE id = ? AND status != 'paid' ''', 
                          (receivable_id,))
            receivable = cursor.fetchone()
            
            if not receivable:
                return "Receivable not found or already paid", 404

            amount, ar_account_id, invoice_number, customer_name = receivable

            # Update receivable status
            cursor.execute('''UPDATE receivables 
                             SET status = 'paid', date_paid = ?
                             WHERE id = ?''',
                          (payment_date, receivable_id))
            
            # Create journal entry (credit Accounts Receivable, debit Cash/Bank)
            insert_transaction(cursor, payment_date, ar_account_id,
                             f"Payment for invoice {invoice_number} from {customer_name}",
                             0, amount)
            
            insert_transaction(cursor, payment_date, payment_account_id,
                             f"Payment received for invoice {invoice_number} from {customer_name}",
                             amount, 0)
            
            conn.commit()
        except sqlite3.Error as e:
            return f"Database error: {str(e)}", 500

    return redirect(url_for('receivables'))

@app.route('/api/receivables')
def receivables_api():
    status_filter = request.args.get('status', 'all')
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        query = '''SELECT r.*, a.name as account_name 
                   FROM receivables r
                   JOIN accounts a ON r.account_id = a.id'''
        
        if status_filter == 'open':
            query += " WHERE r.status = 'open'"
        elif status_filter == 'overdue':
            query += " WHERE r.status = 'overdue'"
        elif status_filter == 'paid':
            query += " WHERE r.status = 'paid'"
        
        query += " ORDER BY r.due_date"
        cursor.execute(query)
        
        receivables = [dict(zip([column[0] for column in cursor.description], row)) 
                      for row in cursor.fetchall()]
    
    return jsonify(receivables)

@app.route('/receivables/report')
def receivables_report():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Summary stats
        cursor.execute('''SELECT 
                            COUNT(*) as total,
                            SUM(CASE WHEN status = 'open' THEN amount ELSE 0 END) as open_amount,
                            SUM(CASE WHEN status = 'overdue' THEN amount ELSE 0 END) as overdue_amount,
                            SUM(CASE WHEN status = 'paid' THEN amount ELSE 0 END) as paid_amount
                          FROM receivables''')
        summary = dict(zip([column[0] for column in cursor.description], cursor.fetchone()))
        
        # Aging report
        cursor.execute('''SELECT 
                            customer_name,
                            invoice_number,
                            amount,
                            date_issued,
                            due_date,
                            CASE 
                                WHEN status = 'paid' THEN 'Paid'
                                WHEN date(due_date) < date('now') THEN 'Overdue'
                                ELSE 'Current'
                            END as status,
                            julianday('now') - julianday(due_date) as days_overdue
                          FROM receivables
                          WHERE status != 'paid'
                          ORDER BY days_overdue DESC''')
        aging_report = [dict(zip([column[0] for column in cursor.description], row)) 
                      for row in cursor.fetchall()]
    
    return render_template("receivables_report.html",
                         summary=summary,
                         aging_report=aging_report,
                         now=datetime.now().strftime('%Y-%m-%d'))
# Check Writing routes
@app.route('/checks')
def checks():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Get all accounts (not just checking accounts)
        cursor.execute("SELECT id, name, balance FROM accounts")
        accounts = [{'id': row[0], 'name': row[1], 'balance': row[2]} for row in cursor.fetchall()]
        
        # Get recent checks
        cursor.execute('''SELECT c.check_number, c.date, c.payee, c.amount, a.name as account_name
                          FROM check_register c
                          JOIN accounts a ON c.account_id = a.id
                          ORDER BY c.date DESC LIMIT 10''')
        recent_checks = cursor.fetchall()
        
        # Count total checks
        cursor.execute("SELECT COUNT(*) FROM check_register")
        total_checks = cursor.fetchone()[0]
    
    return render_template("checks.html",
                         accounts=accounts,
                         recent_checks=recent_checks,
                         total_checks=total_checks)
@app.route('/write_check', methods=['GET', 'POST'])
def write_check():
    if request.method == 'POST':
        try:
            # Get form data
            payee = request.form.get('payee')
            amount = request.form.get('amount')
            date = request.form.get('date')
            check_number = request.form.get('check_number')
            account_id = request.form.get('account_id')
            memo = request.form.get('memo', '')
            save_action = request.form.get('save_action')

            # Validate required fields
            if not all([payee, amount, date, check_number, account_id]):
                flash("All required fields must be filled", "error")
                return redirect(url_for('write_check'))

            try:
                amount = float(amount)
                if amount <= 0:
                    flash("Amount must be positive", "error")
                    return redirect(url_for('write_check'))
            except ValueError:
                flash("Invalid amount entered", "error")
                return redirect(url_for('write_check'))

            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                
                # Verify account exists
                cursor.execute("SELECT name, balance FROM accounts WHERE id = ?", (account_id,))
                account = cursor.fetchone()
                if not account:
                    flash("Invalid bank account selected", "error")
                    return redirect(url_for('write_check'))
                
                account_name, balance = account
                if balance < amount:
                    flash(f"Insufficient funds in {account_name} (Balance: ${balance:.2f})", "error")
                    return redirect(url_for('write_check'))
                
                # Insert transaction
                description = f"Check #{check_number} to {payee}"
                if memo:
                    description += f" - {memo}"
                
                insert_transaction(cursor, date, account_id, description, 0, amount)
                
                # Save check details
                cursor.execute('''INSERT INTO check_register 
                                (check_number, payee, amount, date, account_id, memo, printed)
                                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                             (check_number, payee, amount, date, account_id, memo, save_action == 'print'))
                
                conn.commit()
                
                flash(f"Check #{check_number} for ${amount:.2f} to {payee} saved successfully", "success")
                
                if save_action == 'print':
                    return render_template("print_check.html",
                                        payee=payee,
                                        amount=amount,
                                        date=date,
                                        check_number=check_number,
                                        memo=memo,
                                        account_name=account_name)
                return redirect(url_for('checks'))

        except sqlite3.Error as e:
            flash(f"Database error: {str(e)}", "error")
            return redirect(url_for('write_check'))
    
    # GET request - show form
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        account_id = request.args.get('account_id')
        
        cursor.execute("SELECT id, name, balance FROM accounts")
        accounts = [{'id': row[0], 'name': row[1], 'balance': row[2]} for row in cursor.fetchall()]
        
        if not accounts:
            flash("No accounts found. Please create an account first.", "error")
            return redirect(url_for('create_account'))
            
        cursor.execute("SELECT MAX(check_number) FROM check_register")
        last_check = cursor.fetchone()[0]
        next_check = (last_check or 1000) + 1
        
    return render_template("write_check.html",
                         accounts=accounts,
                         selected_account_id=account_id,
                         next_check=next_check,
                         today=datetime.now().strftime('%Y-%m-%d'))
@app.route('/api/check_balance/<int:account_id>')
def check_balance(account_id):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM accounts WHERE id = ?", (account_id,))
        balance = cursor.fetchone()
        if balance:
            return jsonify({"balance": balance[0]})
    return jsonify({"error": "Account not found"}), 404

# Add this table creation to your init_db() function
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # ... your existing table creations ...
        
        # Add check register table
        cursor.execute('''CREATE TABLE IF NOT EXISTS check_register (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            check_number INTEGER NOT NULL,
                            payee TEXT NOT NULL,
                            amount REAL NOT NULL,
                            date TEXT NOT NULL,
                            account_id INTEGER NOT NULL,
                            description TEXT,
                            memo TEXT,
                            FOREIGN KEY(account_id) REFERENCES accounts(id)
                          )''')
        conn.commit()

# New Excel Upload Feature
@app.route('/upload_transactions', methods=['GET', 'POST'])
def upload_transactions():
    if request.method == 'POST':
        if 'file' not in request.files:
            return "No file selected", 400
        
        file = request.files['file']
        account_id = request.form.get('account_id')
        
        if file.filename == '':
            return "No file selected", 400
        
        if file and allowed_file(file.filename):
            try:
                # Read Excel/CSV file
                if file.filename.endswith('.csv'):
                    df = pd.read_csv(file)
                else:
                    df = pd.read_excel(file)
                
                # Convert date format if column exists
                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
                
                with sqlite3.connect(DB_FILE) as conn:
                    cursor = conn.cursor()
                    for _, row in df.iterrows():
                        date = row.get('date', datetime.now().strftime('%Y-%m-%d'))
                        description = row.get('description', 'Excel Upload')
                        debit = float(row.get('debit', 0))
                        credit = float(row.get('credit', 0))
                        insert_transaction(cursor, date, account_id, description, debit, credit)
                    conn.commit()
                
                return redirect(url_for('index'))
            except Exception as e:
                return f"Error processing file: {str(e)}", 500
    
    # GET request - show upload form
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM accounts")
        accounts = cursor.fetchall()
    return render_template("upload_transactions.html", accounts=accounts)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)