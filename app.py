import os
import secrets
import csv
import io
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(20), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed = db.Column(db.Boolean, default=False)
    confirmed_at = db.Column(db.DateTime)
    session_id = db.Column(db.String(50))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Ensure session unique ID for order tracking
def get_or_create_session_id():
    if 'session_id' not in session:
        session['session_id'] = secrets.token_hex(16)
    return session['session_id']

# Ensure static directories exist
def ensure_static_dirs():
    os.makedirs('static/images', exist_ok=True)

# Route to serve the QR code image (1.jpg from the root directory)
@app.route('/qr_code')
def qr_code():
    return send_file('1.jpg', mimetype='image/jpeg')

# Home route
@app.route('/')
def home():
    # Check if user has a confirmed order
    session_id = get_or_create_session_id()
    has_confirmed_order = Order.query.filter_by(session_id=session_id, confirmed=True).first() is not None
    
    return render_template('index.html', has_confirmed_order=has_confirmed_order)

# Payment route
@app.route('/payment')
def payment():
    # Ensure static folders exist
    ensure_static_dirs()
    
    # Check if payment QR code exists, if not, create a placeholder
    qr_code_path = os.path.join('static', 'images', 'payment_qrcode.jpg')
    if not os.path.exists(qr_code_path):
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np
        
        try:
            # Create a placeholder QR code image
            img = Image.new('RGB', (200, 200), color=(255, 255, 255))
            d = ImageDraw.Draw(img)
            
            # Draw a border
            d.rectangle([(0, 0), (199, 199)], outline=(0, 0, 0))
            
            # Add text
            d.text((40, 80), "赞赏码占位图", fill=(0, 0, 0))
            d.text((25, 100), "请替换为您的微信赞赏码", fill=(0, 0, 0))
            
            # Save the image
            img.save(qr_code_path)
        except Exception as e:
            print(f"Error creating placeholder QR code: {e}")
    
    return render_template('payment.html')

# Create order
@app.route('/create_order', methods=['POST'])
def create_order():
    session_id = get_or_create_session_id()
    
    # Check if user already has an order
    existing_order = Order.query.filter_by(session_id=session_id).first()
    if existing_order:
        if existing_order.confirmed:
            return redirect(url_for('home'))
        return redirect(url_for('payment'))
    
    # Create new order
    order_number = f"ORDER-{secrets.token_hex(6).upper()}"
    new_order = Order(order_number=order_number, session_id=session_id)
    db.session.add(new_order)
    db.session.commit()
    
    return redirect(url_for('payment'))

# Confirm payment (user side)
@app.route('/confirm_payment', methods=['POST'])
def confirm_payment():
    session_id = get_or_create_session_id()
    order = Order.query.filter_by(session_id=session_id).first()
    
    if not order:
        flash('No order found. Please try again.', 'error')
        return redirect(url_for('payment'))
    
    # In a real system, you would verify payment with a payment gateway
    # For now, we'll just redirect to waiting page
    return render_template('waiting.html', order_number=order.order_number)

# Check order status (AJAX endpoint)
@app.route('/check_order_status')
def check_order_status():
    order_number = request.args.get('order_number')
    order = Order.query.filter_by(order_number=order_number).first()
    
    if not order:
        return jsonify({'status': 'error', 'message': 'Order not found'})
    
    return jsonify({
        'status': 'success',
        'confirmed': order.confirmed
    })

# Admin login
@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password) and user.is_admin:
            login_user(user)
            return redirect(url_for('admin'))
        else:
            flash('Login failed. Please check your credentials.', 'error')
    
    return render_template('admin_login.html')

# Admin logout
@app.route('/admin/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Admin dashboard
@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        return redirect(url_for('home'))
    
    orders = Order.query.order_by(Order.created_at.desc()).all()
    now = datetime.now()  # Current time for display
    return render_template('admin.html', orders=orders, now=now)

# Admin confirm order
@app.route('/admin/confirm_order/<order_number>', methods=['POST'])
@login_required
def admin_confirm_order(order_number):
    if not current_user.is_admin:
        return redirect(url_for('home'))
    
    order = Order.query.filter_by(order_number=order_number).first()
    
    if not order:
        flash('Order not found.', 'error')
        return redirect(url_for('admin'))
    
    order.confirmed = True
    order.confirmed_at = datetime.utcnow()
    db.session.commit()
    
    flash(f'Order {order_number} has been confirmed!', 'success')
    return redirect(url_for('admin'))

# Export orders as CSV
@app.route('/export_orders')
@login_required
def export_orders():
    if not current_user.is_admin:
        return redirect(url_for('home'))
    
    # Create a CSV file in memory
    si = io.StringIO()
    writer = csv.writer(si)
    
    # Write header row
    writer.writerow(['订单号', '创建时间', '状态', '确认时间', '会话ID'])
    
    # Write order data
    orders = Order.query.order_by(Order.created_at.desc()).all()
    for order in orders:
        status = '已确认' if order.confirmed else '待确认'
        confirmed_time = order.confirmed_at.strftime('%Y-%m-%d %H:%M:%S') if order.confirmed_at else 'N/A'
        
        writer.writerow([
            order.order_number,
            order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            status,
            confirmed_time,
            order.session_id
        ])
    
    # Create response
    output = si.getvalue()
    filename = f"orders_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

# Create admin user
@app.route('/setup/admin')
def setup_admin():
    # Check if admin exists
    admin = User.query.filter_by(is_admin=True).first()
    if admin:
        return "Admin already exists."
    
    # Create admin user
    hashed_password = generate_password_hash('admin123')
    admin = User(username='admin', password=hashed_password, is_admin=True)
    db.session.add(admin)
    db.session.commit()
    
    return "Admin user created. Username: admin, Password: admin123"

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_static_dirs()
    app.run(debug=True) 