from app import app, init_db
import webbrowser

if __name__ == '__main__':
    init_db()  
    webbrowser.open("http://127.0.0.1:5000")  # Auto-open browser
    app.run(debug=False)  # Disable debug mode for production