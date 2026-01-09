# app.py - Laboratory Reagent Inventory Web App with Barcode/QR Support
# A simple Flask-based app implementing your feature plan
# Features: Reagent catalog (with CAS, supplier, location, quantity), QR code generation/labeling,
# Basic stock tracking, search/filter, usage logging, low-stock/expiration alerts, admin overview
# Uses SQLite for simplicity, Flask-Login for role-based access (admin/user)

from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime
import qrcode
import io
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_change_this'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///reagents.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)  # In production, hash passwords!
    role = db.Column(db.String(20), default='user')  # 'admin' or 'user'

class Reagent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    cas_number = db.Column(db.String(50))
    supplier = db.Column(db.String(100))
    location = db.Column(db.String(100))
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), default='g')  # e.g., g, ml, bottles
    expiration_date = db.Column(db.Date)
    low_stock_threshold = db.Column(db.Float, default=10.0)
    qr_code = db.Column(db.String(200))  # Store filename or data

class UsageLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reagent_id = db.Column(db.Integer, db.ForeignKey('reagent.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    quantity_used = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create DB and sample data (run once)
@app.before_first_request
def create_tables():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password='admin123', role='admin')  # Change password!
        user = User(username='user', password='user123', role='user')
        db.session.add(admin)
        db.session.add(user)
        db.session.commit()

# Routes
@app.route('/')
@login_required
def index():
    search = request.args.get('search', '')
    reagents = Reagent.query.filter(
        Reagent.name.contains(search) |
        Reagent.cas_number.contains(search) |
        Reagent.location.contains(search)
    ).all()
    
    # Alerts
    alerts = []
    for r in Reagent.query.all():
        if r.quantity <= r.low_stock_threshold:
            alerts.append(f"Low stock: {r.name} ({r.quantity} {r.unit})")
        if r.expiration_date and r.expiration_date < datetime.today().date():
            alerts.append(f"Expired: {r.name}")
    
    return render_template('index.html', reagents=reagents, alerts=alerts, search=search)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.password == request.form['password']:  # Plaintext - use hashing in prod!
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_reagent():
    if request.method == 'POST':
        reagent = Reagent(
            name=request.form['name'],
            cas_number=request.form['cas_number'],
            supplier=request.form['supplier'],
            location=request.form['location'],
            quantity=float(request.form['quantity']),
            unit=request.form['unit'],
            expiration_date=datetime.strptime(request.form['expiration_date'], '%Y-%m-%d') if request.form['expiration_date'] else None,
            low_stock_threshold=float(request.form.get('low_stock_threshold', 10))
        )
        db.session.add(reagent)
        db.session.commit()
        
        # Generate QR code (contains reagent ID for scanning)
        qr_img = qrcode.make(f"http://127.0.0.1:5000/reagent/{reagent.id}")
        qr_io = io.BytesIO()
        qr_img.save(qr_io, 'PNG')
        qr_io.seek(0)
        # In production, save to file or use base64 in template
        reagent.qr_code = f"qr_{reagent.id}.png"  # Placeholder
        db.session.commit()
        
        flash('Reagent added!')
        return redirect(url_for('index'))
    return render_template('add.html')

@app.route('/reagent/<int:id>')
@login_required
def view_reagent(id):
    reagent = Reagent.query.get_or_404(id)
    logs = UsageLog.query.filter_by(reagent_id=id).all()
    return render_template('view.html', reagent=reagent, logs=logs)

@app.route('/qr/<int:id>')
def get_qr(id):
    reagent = Reagent.query.get_or_404(id)
    url = request.url_root + 'reagent/' + str(id)
    qr_img = qrcode.make(url)
    qr_io = io.BytesIO()
    qr_img.save(qr_io, 'PNG')
    qr_io.seek(0)
    return send_file(qr_io, mimetype='image/png')

@app.route('/scan', methods=['GET', 'POST'])
@login_required
def scan():
    if request.method == 'POST':
        reagent_id = request.form['reagent_id']  # In real app, use JS scanner to fill this
        return redirect(url_for('view_reagent', id=reagent_id))
    return render_template('scan.html')  # Page with camera access for scanning

@app.route('/log_usage/<int:id>', methods=['POST'])
@login_required
def log_usage(id):
    reagent = Reagent.query.get_or_404(id)
    qty = float(request.form['quantity_used'])
    reagent.quantity -= qty
    log = UsageLog(reagent_id=id, user_id=current_user.id, quantity_used=qty, notes=request.form.get('notes'))
    db.session.add(log)
    db.session.commit()
    flash('Usage logged!')
    return redirect(url_for('view_reagent', id=id))

@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Admin only')
        return redirect(url_for('index'))
    total = Reagent.query.count()
    low_stock = Reagent.query.filter(Reagent.quantity <= Reagent.low_stock_threshold).count()
    expired = Reagent.query.filter(Reagent.expiration_date < datetime.today().date()).count()
    return render_template('admin.html', total=total, low_stock=low_stock, expired=expired)

if __name__ == '__main__':
    with app.app_context():
        create_tables()
    app.run(debug=True)
