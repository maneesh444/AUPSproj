
# Before running, make sure to install all required libraries:
# pip install Flask qrcode[pil] opencv-python cvzone numpy

from flask import Flask, render_template, request, redirect, session, url_for, Response
import sqlite3
import os
from datetime import datetime
import io
import base64
import qrcode

# --- OPENCV & VIDEO STREAMING ADDITIONS ---
import cv2
import pickle
import cvzone
import numpy as np
# ------------------------------------------

app = Flask(__name__)
app.secret_key = 'a_more_secure_secret_key_12345'


# --- OPENCV & VIDEO STREAMING SETUP ---
try:
    cap = cv2.VideoCapture('carPark.mp4')
    with open('CarParkPos', 'rb') as f:
        posList = pickle.load(f)
    width, height = 107, 48
    VIDEO_STREAM_AVAILABLE = True
except FileNotFoundError:
    VIDEO_STREAM_AVAILABLE = False
    print("Warning: 'carPark.mp4' or 'CarParkPos' not found. Live feed will be disabled.")
# ------------------------------------


# ---------- DATABASE SETUP ----------
def init_db():
    conn = sqlite3.connect('parking.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            phone TEXT NOT NULL, vehicle_number TEXT NOT NULL UNIQUE
        )''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, mall TEXT,
            vehicle_type TEXT, slot_time TEXT, fare INTEGER, payment_method TEXT,
            booking_time DATETIME, FOREIGN KEY(user_id) REFERENCES users(id)
        )''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS fines (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            reason TEXT, amount INTEGER, date TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')
    conn.commit()
    conn.close()

init_db()


# --- OPENCV & VIDEO STREAMING HELPER FUNCTION ---
def checkParkingSpace(imgPro, img):
    """Checks parking spaces and draws annotations on the image."""
    spaceCounter = 0
    for pos in posList:
        x, y = pos
        imgCrop = imgPro[y:y + height, x:x + width]
        count = cv2.countNonZero(imgCrop)

        if count < 900:
            color = (0, 255, 0)
            thickness = 5
            spaceCounter += 1
        else:
            color = (0, 0, 255)
            thickness = 2

        cv2.rectangle(img, pos, (pos[0] + width, pos[1] + height), color, thickness)
        cvzone.putTextRect(img, str(count), (x, y + height - 3), scale=1,
                           thickness=2, offset=0, colorR=color)

    cvzone.putTextRect(img, f'Free: {spaceCounter}/{len(posList)}', (100, 50), scale=3,
                       thickness=5, offset=20, colorR=(0, 200, 0))
# -----------------------------------------------


# --- ROUTES ---

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        vehicle_number = request.form['vehicle_number'].upper()
        conn = sqlite3.connect('parking.db')
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE vehicle_number = ?', (vehicle_number,))
        user = c.fetchone()
        if user:
            session['user_id'] = user[0]
            session['name'] = user[1]
        else:
            c.execute('INSERT INTO users (name, phone, vehicle_number) VALUES (?, ?, ?)', (name, phone, vehicle_number))
            session['user_id'] = c.lastrowid
            session['name'] = name
        conn.commit()
        conn.close()
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', name=session.get('name'))

@app.route('/book', methods=['GET', 'POST'])
def book():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        mall = request.form['mall']
        vehicle_type = request.form['vehicle_type']
        time_duration = int(request.form['time_duration'])
        fare = 20 * time_duration if vehicle_type == 'Bike' else 40 * time_duration
        conn = sqlite3.connect('parking.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO bookings (user_id, mall, vehicle_type, slot_time, fare, booking_time)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session['user_id'], mall, vehicle_type, f"{time_duration} hour(s)", fare, datetime.now()))
        session['booking_id'] = c.lastrowid
        conn.commit()
        conn.close()
        return redirect(url_for('payment'))
    return render_template('book_slot.html')

@app.route('/payment', methods=['GET', 'POST'])
def payment():
    if 'user_id' not in session or 'booking_id' not in session: return redirect(url_for('login'))
    conn = sqlite3.connect('parking.db')
    c = conn.cursor()
    c.execute('SELECT fare FROM bookings WHERE id = ?', (session['booking_id'],))
    booking = c.fetchone()
    conn.close()
    if not booking: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        session['payment_method'] = request.form['payment_method']
        if session['payment_method'] in ['Credit Card', 'Debit Card']: return redirect(url_for('pay_card'))
        elif session['payment_method'] == 'UPI': return redirect(url_for('pay_upi'))
    return render_template('payment.html', fare=booking[0])

@app.route('/pay/card', methods=['GET', 'POST'])
def pay_card():
    if 'user_id' not in session or 'booking_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        conn = sqlite3.connect('parking.db')
        c = conn.cursor()
        c.execute('UPDATE bookings SET payment_method = ? WHERE id = ?', (session.get('payment_method', 'Card'), session['booking_id']))
        conn.commit()
        conn.close()
        return redirect(url_for('confirmation'))
    return render_template('pay_card.html')

@app.route('/pay/upi', methods=['GET', 'POST'])
def pay_upi():
    if 'user_id' not in session or 'booking_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        conn = sqlite3.connect('parking.db')
        c = conn.cursor()
        c.execute('UPDATE bookings SET payment_method = ? WHERE id = ?', (session.get('payment_method', 'UPI'), session['booking_id']))
        conn.commit()
        conn.close()
        return redirect(url_for('confirmation'))
    return render_template('pay_upi.html')

@app.route('/confirmation')
def confirmation():
    if 'user_id' not in session or 'booking_id' not in session: return redirect(url_for('login'))
    
    conn = sqlite3.connect('parking.db')
    # --- FIX: Enable dictionary access for rows (Solved your blank data issue) ---
    conn.row_factory = sqlite3.Row  
    # -----------------------------------------------------------------------------
    
    c = conn.cursor()
    c.execute('''SELECT b.mall, b.vehicle_type, b.slot_time, b.fare, b.payment_method, u.name, u.vehicle_number 
                 FROM bookings b JOIN users u ON b.user_id = u.id WHERE b.id = ?''', (session['booking_id'],))
    booking = c.fetchone()
    conn.close()
    
    if not booking: return redirect(url_for('dashboard'))
    
    # Using dictionary keys here since row_factory is enabled
    qr_data = f"Booking ID: {session['booking_id']}, Name: {booking['name']}, Vehicle: {booking['vehicle_number']}, Mall: {booking['mall']}"
    
    img = qrcode.make(qr_data)
    buf = io.BytesIO()
    img.save(buf)
    qr_code_data = base64.b64encode(buf.getvalue()).decode('utf-8')
    return render_template('confirmation.html', booking=booking, qr_code_data=qr_code_data)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/history')
def history():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = sqlite3.connect('parking.db')
    c = conn.cursor()
    c.execute('SELECT mall, vehicle_type, slot_time, fare, payment_method, booking_time FROM bookings WHERE user_id = ? ORDER BY booking_time DESC', (session['user_id'],))
    bookings = c.fetchall()
    conn.close()
    return render_template('history.html', bookings=bookings)

# --- FIX: Updated Cancel Booking Logic ---
@app.route('/cancel_booking', methods=['GET', 'POST'])
def cancel_booking():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('parking.db')
    c = conn.cursor()

    if request.method == 'POST':
        # Logic to delete the booking
        booking_id = request.form['booking_id']
        c.execute('DELETE FROM bookings WHERE id = ? AND user_id = ?', (booking_id, session['user_id']))
        conn.commit()
        conn.close()
        return redirect(url_for('cancel_booking'))

    # Logic to fetch bookings so the table is not empty
    # Selecting columns in the order expected by your HTML: [0]id, [1]mall, [2]type, [3]time, [4]fare
    c.execute('''
        SELECT id, mall, vehicle_type, slot_time, fare 
        FROM bookings 
        WHERE user_id = ? 
        ORDER BY booking_time DESC
    ''', (session['user_id'],))
    bookings = c.fetchall()
    conn.close()

    return render_template('cancel_booking.html', bookings=bookings)
# -----------------------------------------

@app.route('/fines')
def fines():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = sqlite3.connect('parking.db')
    c = conn.cursor()
    c.execute('SELECT reason, amount, date FROM fines WHERE user_id = ?', (session['user_id'],))
    fines = c.fetchall()
    conn.close()
    return render_template('fines.html', fines=fines)

@app.route('/availability')
def availability():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = sqlite3.connect('parking.db')
    c = conn.cursor()
    malls = ['AMB Mall', 'Sarath City Capital Mall', 'Inorbit Mall', 'Forum Sujana Mall', 'Manjeera Mall']
    capacity = 193
    slots = {}
    for mall in malls:
        c.execute('SELECT COUNT(*) FROM bookings WHERE mall = ?', (mall,))
        booked = c.fetchone()[0]
        slots[mall] = {'booked': booked, 'available': max(0, capacity - booked)}
    conn.close()
    return render_template('availability.html', slots=slots, capacity=capacity, video_available=VIDEO_STREAM_AVAILABLE)

# --- VIDEO STREAMING FUNCTIONS ---
def generate_frames():
    while True:
        if cap.get(cv2.CAP_PROP_POS_FRAMES) == cap.get(cv2.CAP_PROP_FRAME_COUNT):
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        success, img = cap.read()
        if not success:
            break
        else:
            imgGray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            imgBlur = cv2.GaussianBlur(imgGray, (3, 3), 1)
            imgThreshold = cv2.adaptiveThreshold(imgBlur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                 cv2.THRESH_BINARY_INV, 25, 16)
            imgMedian = cv2.medianBlur(imgThreshold, 5)
            kernel = np.ones((3, 3), np.uint8)
            imgDilate = cv2.dilate(imgMedian, kernel, iterations=1)
            checkParkingSpace(imgDilate, img)
            ret, buffer = cv2.imencode('.jpg', img)
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/live_feed')
def live_feed():
    if not VIDEO_STREAM_AVAILABLE:
        return "Live feed is unavailable.", 503
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5050)
