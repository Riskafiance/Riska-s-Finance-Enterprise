import os
import sqlite3
from datetime import datetime
from flask import Flask, request, render_template, send_file, redirect, url_for, abort, after_this_request, jsonify, flash
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

# (All other routes go here - I'm skipping these to focus on the upload function)

# New Excel Upload Feature - IMPROVED VERSION
@app.route('/upload_transactions', methods=['GET', 'POST'])
def upload_transactions():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash("No file selected", "error")
            return redirect(request.url)
        
        file = request.files['file']
        account_id = request.form.get('account_id')
        
        if file.filename == '':
            flash("No file selected", "error")
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
                    if col.lower() in ['date', 'transaction date', 'trans date', 'date posted']:
                        date_column = col
                        df[date_column] = pd.to_datetime(df[date_column], errors='coerce').dt.strftime('%Y-%m-%d')
                        break
                
                # Look for amount columns using case-insensitive matching
                amount_column = None
                debit_column = None
                credit_column = None
                
                for col in df.columns:
                    col_lower = col.lower()
                    if col_lower in ['amount', 'transaction amount', 'total']:
                        amount_column = col
                    elif col_lower in ['debit', 'deposit', 'payment', 'inflow']:
                        debit_column = col
                    elif col_lower in ['credit', 'withdrawal', 'expense', 'outflow']:
                        credit_column = col
                
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
                            for col in df.columns:
                                if col.lower() in ['description', 'memo', 'notes', 'payee', 'details']:
                                    if not pd.isna(row[col]) and str(row[col]).strip():
                                        description = str(row[col])
                                        break
                            
                            # Get amount and determine debit/credit
                            debit = 0
                            credit = 0
                            
                            if amount_column:
                                try:
                                    # Try to convert amount to float
                                    amount_str = str(row[amount_column])
                                    # Remove currency symbols and commas
                                    amount_str = amount_str.replace('$', '').replace(',', '').strip()
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
                                        if debit_str:
                                            debit = float(debit_str)
                                    except (ValueError, TypeError):
                                        debit = 0
                                
                                if credit_column:
                                    try:
                                        credit_str = str(row[credit_column]).replace('$', '').replace(',', '').strip()
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
                    flash(f"No transactions imported. Check your file format.", "error")
                
                return redirect(url_for('home'))
            except Exception as e:
                flash(f"Error processing file: {str(e)}", "error")
                return redirect(request.url)
    
    # GET request - show upload form
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM accounts")
        accounts = cursor.fetchall()
    return render_template("upload_transactions.html", accounts=accounts)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)