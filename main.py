import sys
import os
import sqlite3

# Add the current directory to the path so imports work correctly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import app and init_db from attached_assets directory
from attached_assets.app import app
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
import sqlite3
from datetime import datetime
import pandas as pd

# Set the template folder to the root templates directory
app.template_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
app.static_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Set a secret key for flash messages and sessions
app.secret_key = os.environ.get("SESSION_SECRET", "riska_finance_secret_key")

# Get the DB_FILE path
DB_FILE = "accounting.db"

# Define a custom init_db function that creates all necessary tables
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
        
        # Check register table
        cursor.execute('''CREATE TABLE IF NOT EXISTS check_register (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            check_number INTEGER NOT NULL,
                            payee TEXT NOT NULL,
                            amount REAL NOT NULL,
                            date TEXT NOT NULL,
                            account_id INTEGER NOT NULL,
                            description TEXT,
                            memo TEXT,
                            printed INTEGER DEFAULT 0,
                            FOREIGN KEY(account_id) REFERENCES accounts(id)
                          )''')
        
        conn.commit()

# Initialize database when app starts
init_db()

# Add routes

@app.route('/add_payment', methods=['GET', 'POST'])
def add_payment():
    if request.method == 'POST':
        # Get form data
        receivable_id = request.form.get('receivable_id')
        payment_date = request.form.get('payment_date')
        payment_account_id = request.form.get('payment_account_id')
        amount = request.form.get('amount')
        payment_method = request.form.get('payment_method')
        reference = request.form.get('reference')
        notes = request.form.get('notes')
        
        # Validate inputs
        if not all([receivable_id, payment_date, payment_account_id, amount]):
            return "Required fields missing", 400
            
        try:
            amount = float(amount)
            if amount <= 0:
                return "Amount must be positive", 400
        except ValueError:
            return "Invalid amount", 400
            
        if not validate_date(payment_date):
            return "Invalid date format. Use YYYY-MM-DD.", 400
            
        # Process payment
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
                    
                original_amount, ar_account_id, invoice_number, customer_name = receivable
                
                # Check if payment is full or partial
                payment_status = 'paid' if amount >= original_amount else 'open'
                
                # Update receivable status
                cursor.execute('''UPDATE receivables 
                                 SET status = ?, date_paid = ?
                                 WHERE id = ?''',
                              (payment_status, payment_date, receivable_id))
                
                # Create journal entry (credit Accounts Receivable, debit Cash/Bank)
                payment_description = f"Payment for invoice {invoice_number} from {customer_name}"
                if reference:
                    payment_description += f" (Ref: {reference})"
                if notes:
                    payment_description += f" - {notes}"
                
                # Credit Accounts Receivable
                cursor.execute('''INSERT INTO transactions 
                               (date, account_id, description, debit, credit)
                               VALUES (?, ?, ?, ?, ?)''',
                            (payment_date, ar_account_id, payment_description, 0, amount))
                
                # Debit Cash/Bank
                cursor.execute('''INSERT INTO transactions 
                               (date, account_id, description, debit, credit)
                               VALUES (?, ?, ?, ?, ?)''',
                            (payment_date, payment_account_id, payment_description, amount, 0))
                
                conn.commit()
                
            except sqlite3.Error as e:
                return f"Database error: {str(e)}", 500
                
        return redirect(url_for('receivables'))
        
    # GET request - show form
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Get open receivables
        cursor.execute('''SELECT id, invoice_number, customer_name, amount, due_date 
                        FROM receivables 
                        WHERE status != 'paid'
                        ORDER BY due_date''')
        open_receivables = []
        for row in cursor.fetchall():
            open_receivables.append({
                'id': row[0],
                'invoice_number': row[1],
                'customer_name': row[2],
                'amount': row[3],
                'due_date': row[4]
            })
        
        # Get accounts for deposit
        cursor.execute("SELECT id, name FROM accounts")
        accounts = cursor.fetchall()
        
    return render_template("add_payment.html", 
                          open_receivables=open_receivables,
                          accounts=accounts)

# Helper function to validate dates
def validate_date(date_str):
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False

@app.route('/save_check', methods=['POST'])
def save_check():
    try:
        # Get data from form
        check_number = request.form.get('check_number')
        date = request.form.get('date')
        payee = request.form.get('payee')
        amount = request.form.get('amount')
        account_id = request.form.get('account_id')
        description = request.form.get('description')
        memo = request.form.get('memo')
        
        # Validate required fields
        if not all([check_number, date, payee, amount, account_id]):
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        
        # Validate date format
        if not validate_date(date):
            return jsonify({'success': False, 'message': 'Invalid date format'}), 400
        
        # Convert to appropriate types
        try:
            check_number = int(check_number)
            account_id = int(account_id)
            amount = float(amount)
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid numeric values'}), 400
        
        # Check if amount is positive
        if amount <= 0:
            return jsonify({'success': False, 'message': 'Amount must be positive'}), 400
        
        # Save to database
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # Check if account exists
            cursor.execute("SELECT balance FROM accounts WHERE id = ?", (account_id,))
            account = cursor.fetchone()
            if not account:
                return jsonify({'success': False, 'message': 'Account not found'}), 404
            
            account_balance = account[0]
            
            # Check if sufficient funds
            if account_balance < amount:
                return jsonify({'success': False, 'message': 'Insufficient funds'}), 400
            
            # Begin transaction
            try:
                # Insert into check register
                cursor.execute('''
                    INSERT INTO check_register
                    (check_number, date, payee, amount, account_id, description, memo, printed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (check_number, date, payee, amount, account_id, description, memo, 0))
                
                # Record transaction
                transaction_description = f"Check #{check_number} to {payee}"
                if memo:
                    transaction_description += f" - {memo}"
                
                # Credit (decrease) the bank account
                cursor.execute('''
                    INSERT INTO transactions
                    (date, account_id, description, debit, credit)
                    VALUES (?, ?, ?, ?, ?)
                ''', (date, account_id, transaction_description, 0, amount))
                
                # Update account balance
                cursor.execute('''
                    UPDATE accounts
                    SET balance = balance - ?
                    WHERE id = ?
                ''', (amount, account_id))
                
                conn.commit()
                
                return jsonify({
                    'success': True, 
                    'message': f'Check #{check_number} to {payee} for ${amount:.2f} saved successfully',
                    'check_id': cursor.lastrowid
                })
                
            except sqlite3.Error as e:
                conn.rollback()
                return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500
                
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

# Note: upload_transactions function is defined in attached_assets/app.py
# We will patch it there to fix Excel import issues

@app.route('/api/recent_transactions', methods=['GET'])
def get_recent_transactions():
    """API endpoint to get recent transactions"""
    try:
        limit = request.args.get('limit', default=15, type=int)
        
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # Get recent transactions (including check transactions)
            cursor.execute('''SELECT t.date, a.name as account_name, t.description, 
                              t.debit, t.credit, t.id
                              FROM transactions t
                              JOIN accounts a ON t.account_id = a.id
                              ORDER BY t.id DESC LIMIT ?''', (limit,))
            
            transactions = []
            for row in cursor.fetchall():
                transactions.append({
                    'date': row[0],
                    'account': row[1],
                    'description': row[2],
                    'debit': float(row[3]) if row[3] else 0.0,
                    'credit': float(row[4]) if row[4] else 0.0,
                    'id': row[5]
                })
                
            return jsonify({"success": True, "transactions": transactions})
            
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/upload_transactions_new', methods=['GET', 'POST'])
def upload_transactions_new():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash("No file selected", "danger")
            return redirect(request.url)
        
        file = request.files['file']
        account_id = request.form.get('account_id')
        
        if file.filename == '':
            flash("No file selected", "danger")
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            try:
                # Read Excel/CSV file
                if file.filename.endswith('.csv'):
                    df = pd.read_csv(file)
                else:
                    df = pd.read_excel(file)
                
                # Print columns for debugging
                print("Excel columns:", df.columns.tolist())
                print("First row sample:", df.iloc[0].to_dict() if not df.empty else "No data")
                
                # Convert date format if column exists (handle multiple possible date column names)
                date_column = None
                for col in df.columns:
                    if any(date_keyword in col.lower() for date_keyword in ['date', 'day', 'time']):
                        date_column = col
                        df[date_column] = pd.to_datetime(df[date_column], errors='coerce').dt.strftime('%Y-%m-%d')
                        break
                
                # Look for amount columns using case-insensitive matching
                amount_column = None
                debit_column = None
                credit_column = None
                description_column = None
                
                for col in df.columns:
                    col_lower = col.lower()
                    # Find amount column
                    if any(amount_keyword in col_lower for amount_keyword in ['amount', 'transaction', 'total', 'sum']):
                        amount_column = col
                    # Find debit/deposit column
                    elif any(debit_keyword in col_lower for debit_keyword in ['debit', 'deposit', 'payment', 'inflow', 'in']):
                        debit_column = col
                    # Find credit/withdrawal column
                    elif any(credit_keyword in col_lower for credit_keyword in ['credit', 'withdrawal', 'expense', 'outflow', 'out']):
                        credit_column = col
                    # Find description column
                    elif any(desc_keyword in col_lower for desc_keyword in ['description', 'memo', 'notes', 'payee', 'details']):
                        description_column = col
                
                # Handle transactions
                success_count = 0
                error_count = 0
                
                with sqlite3.connect(DB_FILE) as conn:
                    cursor = conn.cursor()
                    
                    for _, row in df.iterrows():
                        try:
                            # Get date (use current date if not found)
                            date = datetime.now().strftime('%Y-%m-%d')
                            if date_column and not pd.isna(row[date_column]):
                                date = row[date_column]
                            
                            # Get description
                            description = "Excel Upload"
                            if description_column and not pd.isna(row[description_column]):
                                description = str(row[description_column]).strip()
                            else:
                                # Try to find a description in any column containing descriptive text
                                for col in df.columns:
                                    if any(desc_word in col.lower() for desc_word in ['desc', 'memo', 'payee', 'note']):
                                        if not pd.isna(row[col]) and str(row[col]).strip():
                                            description = str(row[col]).strip()
                                            break
                            
                            # Get amount and determine debit/credit
                            debit = 0
                            credit = 0
                            
                            if amount_column:
                                try:
                                    # Try to convert amount to float
                                    amount_str = str(row[amount_column])
                                    # Remove currency symbols, commas, and handle parentheses for negative values
                                    amount_str = amount_str.replace('$', '').replace(',', '')
                                    
                                    # Handle parentheses (negative values)
                                    if '(' in amount_str and ')' in amount_str:
                                        amount_str = '-' + amount_str.replace('(', '').replace(')', '')
                                    
                                    amount_str = amount_str.strip()
                                    
                                    if amount_str:
                                        amount = float(amount_str)
                                        
                                        # Positive is debit, negative is credit
                                        if amount > 0:
                                            debit = abs(amount)
                                        else:
                                            credit = abs(amount)
                                except (ValueError, TypeError):
                                    # Skip this row if amount cannot be converted
                                    error_count += 1
                                    continue
                            else:
                                # Try to get debit and credit directly from columns
                                if debit_column:
                                    try:
                                        debit_str = str(row[debit_column]).replace('$', '').replace(',', '').strip()
                                        # Remove parentheses
                                        if '(' in debit_str and ')' in debit_str:
                                            debit_str = debit_str.replace('(', '').replace(')', '')
                                        
                                        if debit_str:
                                            debit = float(debit_str)
                                    except (ValueError, TypeError):
                                        debit = 0
                                
                                if credit_column:
                                    try:
                                        credit_str = str(row[credit_column]).replace('$', '').replace(',', '').strip()
                                        # Remove parentheses
                                        if '(' in credit_str and ')' in credit_str:
                                            credit_str = credit_str.replace('(', '').replace(')', '')
                                        
                                        if credit_str:
                                            credit = float(credit_str)
                                    except (ValueError, TypeError):
                                        credit = 0
                            
                            # Insert transaction if we have valid amounts
                            if debit > 0 or credit > 0:
                                insert_transaction(cursor, date, account_id, description, debit, credit)
                                success_count += 1
                            else:
                                error_count += 1
                                
                        except Exception as e:
                            print(f"Error processing row: {e}")
                            error_count += 1
                    
                    conn.commit()
                
                if success_count > 0:
                    flash(f"Successfully imported {success_count} transactions. {error_count} rows had errors.", 
                          "success" if error_count == 0 else "warning")
                else:
                    flash(f"No transactions imported. Check your file format.", "danger")
                
                return redirect(url_for('home'))
            except Exception as e:
                flash(f"Error processing file: {str(e)}", "danger")
                return redirect(request.url)
    
    # GET request - show upload form
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM accounts")
        accounts = cursor.fetchall()
    return render_template("upload_transactions_new.html", accounts=accounts)

# Add new transaction route that works with the form
@app.route('/add_transaction', methods=['GET', 'POST'])
def add_transaction():
    if request.method == 'POST':
        date = request.form.get('date')
        description = request.form.get('description')
        amount = request.form.get('amount')
        
        # Look for either transaction_type (new form) or category (old form)
        transaction_type = request.form.get('transaction_type')
        if not transaction_type:
            category = request.form.get('category')
            if category == "Debit":
                transaction_type = "debit"
            elif category == "Credit":
                transaction_type = "credit"
                
        # Look for either account_id (new form) or account (old form)
        account_id = request.form.get('account_id')
        if not account_id:
            account_id = request.form.get('account')

        try:
            # Validate date format
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            date = date_obj.strftime('%Y-%m-%d')
        except ValueError:
            flash("Invalid date format. Use YYYY-MM-DD.", "danger")
            return redirect(request.url)

        try:
            amount = float(amount)
            if amount <= 0:
                flash("Amount must be positive.", "danger")
                return redirect(request.url)
        except ValueError:
            flash("Invalid amount.", "danger")
            return redirect(request.url)

        # Handle transaction type (debit or credit)
        if transaction_type not in ["debit", "credit"]:
            flash("Invalid transaction type.", "danger")
            return redirect(request.url)

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            try:
                if transaction_type == "debit":
                    insert_transaction(cursor, date, account_id, description, amount, 0)
                elif transaction_type == "credit":
                    insert_transaction(cursor, date, account_id, description, 0, amount)
                conn.commit()
                flash("Transaction added successfully!", "success")
            except sqlite3.Error as e:
                conn.rollback()
                flash(f"An error occurred: {str(e)}", "danger")
                return redirect(request.url)

        return redirect(url_for('home'))
    
    # GET request - show form
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, balance FROM accounts")
        accounts = cursor.fetchall()
    return render_template("add_transaction_fixed.html", accounts=accounts)

# Helper function to add transactions
def insert_transaction(cursor, date, account_id, description, debit, credit):
    cursor.execute("INSERT INTO transactions (date, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
                  (date, account_id, description, debit, credit))
    cursor.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (debit - credit, account_id))

# Helper function for allowed file extensions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'xlsx', 'xls', 'csv'}

# Asset Keeper Routes
@app.route('/asset_keeper', methods=['GET'])
def asset_keeper():
    return render_template("asset_keeper.html")

@app.route('/asset_report', methods=['GET'])
def asset_report():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Get summary data
        cursor.execute("SELECT COUNT(*) FROM assets")
        total_assets = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(purchase_price) FROM assets")
        total_value = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT SUM(sale_price) FROM assets WHERE sale_price IS NOT NULL")
        total_sales = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT SUM(gain_loss) FROM assets WHERE gain_loss IS NOT NULL")
        net_gain_loss = cursor.fetchone()[0] or 0
        
        summary = {
            'total_assets': total_assets,
            'total_value': total_value,
            'total_sales': total_sales,
            'net_gain_loss': net_gain_loss
        }
        
        # Get recent sales
        cursor.execute("""
            SELECT name, purchase_price, sale_price, gain_loss 
            FROM assets 
            WHERE sale_price IS NOT NULL
            ORDER BY id DESC LIMIT 10
        """)
        recent_sales = [
            {
                'name': row[0],
                'purchase_price': row[1],
                'sale_price': row[2],
                'gain_loss': row[3]
            }
            for row in cursor.fetchall()
        ]
        
    return render_template("assets_report.html", 
                         summary=summary, 
                         recent_sales=recent_sales,
                         now=datetime.now())

@app.route('/api/assets', methods=['GET', 'POST'])
def api_assets():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        if request.method == 'GET':
            cursor.execute("""
                SELECT id, name, purchase_price, useful_life, 
                       depreciation_method, annual_depreciation, 
                       sale_price, gain_loss
                FROM assets
                ORDER BY id DESC
            """)
            
            assets = []
            for row in cursor.fetchall():
                assets.append({
                    'id': row[0],
                    'name': row[1],
                    'purchase_price': row[2],
                    'useful_life': row[3],
                    'depreciation_method': row[4],
                    'annual_depreciation': row[5],
                    'sale_price': row[6],
                    'gain_loss': row[7]
                })
                
            return jsonify(assets)
            
        elif request.method == 'POST':
            data = request.json
            
            if not all(key in data for key in ['name', 'price', 'life', 'method']):
                return jsonify({'message': 'Missing required fields'}), 400
                
            name = data['name']
            price = float(data['price'])
            life = int(data['life'])
            method = data['method']
            
            # Calculate annual depreciation
            if method == 'straight-line':
                annual_depreciation = price / life
            elif method == 'double-declining':
                annual_depreciation = (price * 2) / life
            else:
                annual_depreciation = price / life
                
            try:
                cursor.execute("""
                    INSERT INTO assets (name, purchase_price, useful_life, 
                                      depreciation_method, annual_depreciation)
                    VALUES (?, ?, ?, ?, ?)
                """, (name, price, life, method, annual_depreciation))
                
                conn.commit()
                return jsonify({'message': 'Asset added successfully', 'id': cursor.lastrowid})
                
            except sqlite3.Error as e:
                return jsonify({'message': f'Database error: {str(e)}'}), 500

@app.route('/api/assets/<int:asset_id>', methods=['PUT', 'DELETE'])
def api_asset_by_id(asset_id):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        if request.method == 'PUT':
            data = request.json
            
            if 'sale_price' not in data:
                return jsonify({'message': 'Sale price is required'}), 400
                
            sale_price = float(data['sale_price'])
            
            try:
                # Get asset details
                cursor.execute("""
                    SELECT purchase_price, useful_life, annual_depreciation
                    FROM assets WHERE id = ?
                """, (asset_id,))
                
                asset = cursor.fetchone()
                if not asset:
                    return jsonify({'message': 'Asset not found'}), 404
                    
                purchase_price, useful_life, annual_depreciation = asset
                
                # Calculate gain/loss (simplified: sale_price - purchase_price)
                # In a real system, would account for accumulated depreciation
                gain_loss = sale_price - purchase_price
                
                # Update asset with sale information
                cursor.execute("""
                    UPDATE assets 
                    SET sale_price = ?, gain_loss = ?
                    WHERE id = ?
                """, (sale_price, gain_loss, asset_id))
                
                conn.commit()
                return jsonify({'message': 'Asset sold successfully'})
                
            except sqlite3.Error as e:
                return jsonify({'message': f'Database error: {str(e)}'}), 500
                
        elif request.method == 'DELETE':
            try:
                cursor.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
                
                if cursor.rowcount == 0:
                    return jsonify({'message': 'Asset not found'}), 404
                    
                conn.commit()
                return jsonify({'message': 'Asset deleted successfully'})
                
            except sqlite3.Error as e:
                return jsonify({'message': f'Database error: {str(e)}'}), 500

# API endpoint to get account balance history for charts
@app.route('/api/balance_history', methods=['GET'])
def get_balance_history():
    months = 7  # Number of months to show on chart
    today = datetime.now()
    
    # Create a list of month labels and first day of each month
    month_labels = []
    month_dates = []
    
    for i in range(months):
        # Calculate month (going backwards from current month)
        target_month = today.month - i
        target_year = today.year
        
        # Handle year boundary
        while target_month <= 0:
            target_month += 12
            target_year -= 1
            
        # Create date for first day of month
        first_day = datetime(target_year, target_month, 1)
        month_dates.insert(0, first_day.strftime('%Y-%m-%d'))
        
        # Create month label
        month_labels.insert(0, first_day.strftime('%b'))
    
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # Get current total balance across all accounts
            cursor.execute("SELECT SUM(balance) FROM accounts")
            current_total = cursor.fetchone()[0] or 0
            
            # We'll reconstruct historical balances by looking at transactions
            balances = [current_total]
            income_data = []
            expense_data = []
            
            # For each month period, calculate income and expenses
            for i in range(len(month_dates)-1):
                start_date = month_dates[i]
                end_date = month_dates[i+1]
                
                # Get income for this period (using description to determine transaction type)
                # In this system, income might be identified by credits
                cursor.execute("""
                    SELECT SUM(credit) FROM transactions 
                    WHERE date >= ? AND date < ?
                """, (start_date, end_date))
                period_income = cursor.fetchone()[0] or 0
                income_data.append(period_income)
                
                # Get expenses for this period (using debit as an indicator of expenses)
                cursor.execute("""
                    SELECT SUM(debit) FROM transactions 
                    WHERE date >= ? AND date < ?
                """, (start_date, end_date))
                period_expense = cursor.fetchone()[0] or 0
                expense_data.append(period_expense)
            
            # For the last period (current month), we need special handling
            current_month_start = month_dates[-1]
            
            # Get income for current month
            cursor.execute("""
                SELECT SUM(credit) FROM transactions
                WHERE date >= ?
            """, (current_month_start,))
            current_income = cursor.fetchone()[0] or 0
            income_data.append(current_income)
            
            # Get expenses for current month
            cursor.execute("""
                SELECT SUM(debit) FROM transactions
                WHERE date >= ?
            """, (current_month_start,))
            current_expense = cursor.fetchone()[0] or 0
            expense_data.append(current_expense)
            
            # Calculate balances from the current back to the first month
            for i in range(len(month_dates)-1, 0, -1):
                # Get sum of all transactions between this month and previous month
                cursor.execute("""
                    SELECT SUM(debit) - SUM(credit) 
                    FROM transactions 
                    WHERE date >= ? AND date < ?
                """, (month_dates[i-1], month_dates[i]))
                
                # Subtract this period's net change from the balance
                period_change = cursor.fetchone()[0] or 0
                previous_balance = balances[0] - period_change
                balances.insert(0, previous_balance)
                
            return jsonify({
                'labels': month_labels,
                'balances': balances,
                'income': income_data,
                'expenses': expense_data
            })
            
    except sqlite3.Error as e:
        # Return empty data on error
        return jsonify({
            'labels': month_labels,
            'balances': [0] * len(month_labels),
            'income': [0] * len(month_labels),
            'expenses': [0] * len(month_labels),
            'error': str(e)
        })

# This allows Gunicorn to find the app variable
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)