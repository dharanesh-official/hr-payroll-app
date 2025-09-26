import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from sqlalchemy import or_, func
from weasyprint import HTML
import calendar
import pandas as pd

# --- App and Database Configuration ---
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
# Use environment variable for secret key for production, with a fallback for development
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_very_secret_key_that_should_be_changed')

# Database path that works for both local development and Render's persistent disk
db_path = os.path.join(os.environ.get('RENDER_DISK_PATH', basedir), 'database.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

from payroll import calculate_payslip

MAIN_SUPERVISOR_ID = 'MAIN_SUPERVISOR'

# --- Database Models ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone_number = db.Column(db.String(20))
    address = db.Column(db.String(200))
    date_of_joining = db.Column(db.Date, nullable=False)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), nullable=False)
    salary = db.Column(db.Float, nullable=False, default=0.0)
    supervisor_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    employees = db.relationship('User', backref=db.backref('supervisor', remote_side=[id]), lazy='dynamic')
    leave_requests = db.relationship('LeaveRequest', backref='employee', lazy='dynamic')
    announcements = db.relationship('Announcement', backref='author', lazy='dynamic')
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default='Pending')
    team = db.Column(db.String(100))
    project = db.Column(db.String(100))
    team_leader_name = db.Column(db.String(100))
    team_leader_mobile = db.Column(db.String(20))
    leave_type = db.Column(db.String(50), nullable=False, default='Other')

class Holiday(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50))

class PersonalTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    task_description = db.Column(db.Text, nullable=False)

class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

# --- All Routes and Functions ---
@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

@app.route('/')
def index(): return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(employee_id=request.form['employee_id']).first()
        if user and user.check_password(request.form['password']):
            login_user(user); return redirect(url_for('dashboard'))
        else: flash('Invalid Employee ID or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    if current_user.role not in ['hr', 'supervisor']:
        flash('You do not have permission to register users.', 'error'); return redirect(url_for('dashboard'))
    supervisors = User.query.filter_by(role='supervisor').all()
    if request.method == 'POST':
        if User.query.filter_by(employee_id=request.form['employee_id']).first() or User.query.filter_by(email=request.form['email']).first():
            flash('Employee ID or email already exists.', 'error'); return redirect(url_for('register'))
        if current_user.role == 'hr':
            new_user_role = request.form.get('role', 'employee')
        else:
            new_user_role = 'employee'
        new_user = User(
            employee_id=request.form['employee_id'], name=request.form['name'], email=request.form['email'],
            phone_number=request.form['phone_number'], address=request.form['address'],
            date_of_joining=datetime.strptime(request.form['date_of_joining'], '%Y-%m-%d').date(),
            salary=float(request.form['salary']), role=new_user_role
        )
        new_user.set_password(request.form['password'])
        if current_user.role == 'supervisor':
            new_user.supervisor_id = current_user.id
        elif current_user.role == 'hr':
            supervisor_id = request.form.get('supervisor_id')
            if supervisor_id:
                new_user.supervisor_id = int(supervisor_id)
        db.session.add(new_user); db.session.commit()
        flash('New user registered successfully!', 'success'); return redirect(url_for('dashboard'))
    return render_template('register.html', supervisors=supervisors)

@app.route('/dashboard')
@login_required
def dashboard():
    announcements = Announcement.query.order_by(Announcement.timestamp.desc()).limit(3).all()
    if current_user.role == 'employee':
        leave_requests = LeaveRequest.query.filter_by(user_id=current_user.id).order_by(LeaveRequest.start_date.desc()).limit(5).all()
        return render_template('employee_dashboard.html', leave_requests=leave_requests, announcements=announcements)
    elif current_user.role == 'supervisor':
        team_members = User.query.filter_by(supervisor_id=current_user.id).all()
        if current_user.employee_id == MAIN_SUPERVISOR_ID:
            pending_requests = LeaveRequest.query.filter_by(status='Pending').all()
            total_employees = User.query.count()
            return render_template('supervisor_dashboard.html', pending_requests=pending_requests, total_employees=total_employees, team_members=team_members, announcements=announcements)
        else:
            team_member_ids = [member.id for member in team_members]
            pending_requests = LeaveRequest.query.filter(LeaveRequest.user_id.in_(team_member_ids), LeaveRequest.status == 'Pending').all()
            return render_template('supervisor_dashboard.html', pending_requests=pending_requests, team_members=team_members, announcements=announcements)
    elif current_user.role == 'hr':
        search_query = request.args.get('search', ''); role_filter = request.args.get('role', '')
        query = User.query
        if search_query: query = query.filter(or_(User.name.ilike(f'%{search_query}%'), User.employee_id.ilike(f'%{search_query}%')))
        if role_filter: query = query.filter(User.role == role_filter)
        all_employees = query.order_by(User.name).all()
        return render_template('hr_dashboard.html', all_employees=all_employees, announcements=announcements)
    else: return "<h1>Invalid Role</h1>"

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_password = request.form.get('current_password'); new_password = request.form.get('new_password'); confirm_password = request.form.get('confirm_password')
        if not current_user.check_password(current_password):
            flash('Your current password is incorrect.', 'error'); return redirect(url_for('profile'))
        if new_password != confirm_password:
            flash('New passwords do not match.', 'error'); return redirect(url_for('profile'))
        current_user.set_password(new_password); db.session.commit()
        flash('Your password has been updated!', 'success'); return redirect(url_for('dashboard'))
    return render_template('profile.html')

@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    user_to_edit = User.query.get_or_404(user_id)
    if current_user.role != 'hr' and user_to_edit.supervisor_id != current_user.id:
        flash('You do not have permission to edit this user.', 'error'); return redirect(url_for('dashboard'))
    supervisors = User.query.filter_by(role='supervisor').all()
    if request.method == 'POST':
        user_to_edit.name = request.form['name']; user_to_edit.email = request.form['email']; user_to_edit.phone_number = request.form['phone_number']
        user_to_edit.address = request.form['address']; user_to_edit.salary = float(request.form['salary'])
        if current_user.role == 'hr':
            user_to_edit.role = request.form['role']; supervisor_id = request.form.get('supervisor_id')
            user_to_edit.supervisor_id = int(supervisor_id) if supervisor_id else None
        db.session.commit()
        flash(f'Details for {user_to_edit.name} updated.', 'success'); return redirect(url_for('dashboard'))
    return render_template('edit_user.html', user_to_edit=user_to_edit, supervisors=supervisors)

@app.route('/remove_user/<int:user_id>', methods=['POST'])
@login_required
def remove_user(user_id):
    user_to_remove = User.query.get_or_404(user_id); can_remove = False
    if current_user.role == 'hr' and user_to_remove.id != current_user.id: can_remove = True
    if current_user.role == 'supervisor' and user_to_remove.supervisor_id == current_user.id: can_remove = True
    if not can_remove:
        flash('You do not have permission to remove this user.', 'error'); return redirect(url_for('dashboard'))
    if user_to_remove.role == 'supervisor':
        for employee in user_to_remove.employees: employee.supervisor_id = None
    LeaveRequest.query.filter_by(user_id=user_to_remove.id).delete()
    db.session.delete(user_to_remove); db.session.commit()
    flash(f'User {user_to_remove.name} has been removed.', 'success'); return redirect(url_for('dashboard'))

@app.route('/apply_leave', methods=['GET', 'POST'])
@login_required
def apply_leave():
    if request.method == 'POST':
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date(); end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()
        if start_date > end_date:
            flash('End date must be after start date.', 'error'); return redirect(url_for('apply_leave'))
        new_request = LeaveRequest(
            user_id=current_user.id, start_date=start_date, end_date=end_date, reason=request.form['reason'],
            team=request.form['team'], project=request.form['project'],
            team_leader_name=request.form['team_leader_name'], team_leader_mobile=request.form['team_leader_mobile'],
            leave_type=request.form.get('leave_type')
        )
        db.session.add(new_request); db.session.commit()
        flash('Leave request submitted!', 'success'); return redirect(url_for('dashboard'))
    return render_template('apply_leave.html')

@app.route('/respond_leave/<int:request_id>/<action>')
@login_required
def respond_leave(request_id, action):
    leave_request = LeaveRequest.query.get_or_404(request_id); is_authorized = False
    if current_user.employee_id == MAIN_SUPERVISOR_ID: is_authorized = True
    if leave_request.employee.supervisor_id == current_user.id: is_authorized = True
    if not is_authorized:
        flash('You do not have permission.', 'error'); return redirect(url_for('dashboard'))
    if action == 'approve':
        leave_request.status = 'Approved'; flash(f"Leave for {leave_request.employee.name} approved.", 'success')
    elif action == 'decline':
        leave_request.status = 'Declined'; flash(f"Leave for {leave_request.employee.name} declined.", 'error')
    db.session.commit(); return redirect(url_for('dashboard'))

@app.route('/holidays', methods=['GET', 'POST'])
@login_required
def holidays():
    if current_user.role != 'hr': flash('You do not have permission.', 'error'); return redirect(url_for('dashboard'))
    if request.method == 'POST':
        new_holiday = Holiday(date=datetime.strptime(request.form['date'], '%Y-%m-%d').date(), name=request.form['name'], type=request.form.get('type'))
        db.session.add(new_holiday); db.session.commit()
        flash('Holiday added!', 'success'); return redirect(url_for('holidays'))
    upcoming_holidays = Holiday.query.filter(Holiday.date >= datetime.today()).order_by(Holiday.date).all()
    return render_template('holidays.html', holidays=upcoming_holidays)

@app.route('/holidays/delete/<int:holiday_id>', methods=['POST'])
@login_required
def delete_holiday(holiday_id):
    if current_user.role != 'hr': flash('You do not have permission.', 'error'); return redirect(url_for('dashboard'))
    holiday = Holiday.query.get_or_404(holiday_id)
    db.session.delete(holiday); db.session.commit()
    flash('Holiday deleted.', 'success'); return redirect(url_for('holidays'))

@app.route('/payslip')
@login_required
def view_payslip():
    today = datetime.today()
    year = request.args.get('year', today.year, type=int); month = request.args.get('month', today.month, type=int)
    payslip_data = calculate_payslip(current_user, year, month, db, Holiday, LeaveRequest)
    return render_template('payslip.html', payslip=payslip_data)

@app.route('/payslip_history')
@login_required
def payslip_history():
    payslips = []
    start_date = current_user.date_of_joining; end_date = datetime.today()
    date_range = pd.date_range(start=start_date, end=end_date, freq='MS')
    for dt in reversed(date_range):
        payslip = calculate_payslip(current_user, dt.year, dt.month, db, Holiday, LeaveRequest)
        payslip['year'] = dt.year; payslip['month'] = dt.month
        payslips.append(payslip)
    return render_template('payslip_history.html', payslip_history=payslips)

@app.route('/payroll_report')
@login_required
def payroll_report():
    if current_user.employee_id != MAIN_SUPERVISOR_ID:
        flash('You do not have permission.', 'error'); return redirect(url_for('dashboard'))
    today = datetime.today(); search_query = request.args.get('search', ''); role_filter = request.args.get('role', '')
    query = User.query
    if search_query: query = query.filter(or_(User.name.ilike(f'%{search_query}%'), User.employee_id.ilike(f'%{search_query}%')))
    if role_filter: query = query.filter(User.role == role_filter)
    employees = query.order_by(User.name).all()
    payroll_data = []
    for employee in employees:
        payslip = calculate_payslip(employee, today.year, today.month, db, Holiday, LeaveRequest)
        payslip['employee_id'] = employee.employee_id
        payroll_data.append(payslip)
    month_year = today.strftime("%B %Y")
    return render_template('payroll_report.html', payroll_data=payroll_data, month_year=month_year)

@app.route('/calendar')
@login_required
def view_calendar(): return render_template('calendar.html')

@app.route('/add_task', methods=['POST'])
@login_required
def add_task():
    new_task = PersonalTask(user_id=current_user.id, date=datetime.strptime(request.form['date'], '%Y-%m-%d').date(), task_description=request.form['task_description'])
    db.session.add(new_task); db.session.commit()
    flash('Task added!', 'success'); return redirect(url_for('view_calendar'))

@app.route('/api/events')
@login_required
def api_events():
    events = []; start = request.args.get('start', '').split('T')[0]; end = request.args.get('end', '').split('T')[0]
    try:
        start_date = datetime.strptime(start, '%Y-%m-%d').date(); end_date = datetime.strptime(end, '%Y-%m-%d').date(); current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() == 6: events.append({'title': 'Sunday Holiday', 'start': current_date.isoformat(), 'allDay': True, 'backgroundColor': '#ffe5e5', 'borderColor': '#ffe5e5', 'display': 'background'})
            current_date += timedelta(days=1)
    except (ValueError, TypeError): pass
    holidays = Holiday.query.all()
    for h in holidays:
        event_data = {'title': h.name, 'start': h.date.isoformat(), 'allDay': True}
        if h.type == 'company_event': event_data['backgroundColor'] = '#D90429'; event_data['borderColor'] = '#D90429'
        else: event_data['display'] = 'list-item'; event_data['backgroundColor'] = '#e76f51'; event_data['borderColor'] = '#e76f51'
        events.append(event_data)
    leaves_query = LeaveRequest.query.filter_by(status='Approved')
    if current_user.role == 'hr' or current_user.employee_id == MAIN_SUPERVISOR_ID: leaves = leaves_query.all()
    elif current_user.role == 'supervisor':
        team_member_ids = [member.id for member in current_user.employees]; team_member_ids.append(current_user.id)
        leaves = leaves_query.filter(LeaveRequest.user_id.in_(team_member_ids)).all()
    else: leaves = leaves_query.filter_by(user_id=current_user.id).all()
    for l in leaves: events.append({'title': f"On Leave: {l.employee.name}", 'start': l.start_date.isoformat(), 'end': l.end_date.isoformat(), 'backgroundColor': '#2a9d8f', 'borderColor': '#2a9d8f'})
    tasks = PersonalTask.query.filter_by(user_id=current_user.id).all()
    for t in tasks: events.append({'title': t.task_description, 'start': t.date.isoformat(), 'allDay': True, 'backgroundColor': '#264653', 'borderColor': '#264653'})
    return jsonify(events)

@app.route('/view_letter/<int:request_id>')
@login_required
def view_letter(request_id):
    leave_request = LeaveRequest.query.get_or_404(request_id)
    if current_user.role == 'employee' and leave_request.user_id != current_user.id:
        flash('You do not have permission.', 'error'); return redirect(url_for('dashboard'))
    today_date = datetime.today().strftime('%d-%b-%Y'); total_days = (leave_request.end_date - leave_request.start_date).days + 1
    return render_template('view_letter.html', leave_request=leave_request, today_date=today_date, total_days=total_days)

@app.route('/download_letter/<int:request_id>')
@login_required
def download_letter(request_id):
    leave_request = LeaveRequest.query.get_or_404(request_id)
    if current_user.role == 'employee' and leave_request.user_id != current_user.id:
        flash('You do not have permission.', 'error'); return redirect(url_for('dashboard'))
    today_date = datetime.today().strftime('%d-%b-%Y'); total_days = (leave_request.end_date - leave_request.start_date).days + 1
    html = render_template('view_letter.html', leave_request=leave_request, today_date=today_date, total_days=total_days)
    pdf = HTML(string=html).write_pdf()
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': f'attachment;filename=leave_request_{leave_request.employee.employee_id}.pdf'})

@app.route('/analytics')
@login_required
def analytics_dashboard():
    if current_user.role not in ['hr', 'supervisor']:
        flash('You do not have permission.', 'error'); return redirect(url_for('dashboard'))
    return render_template('analytics_dashboard.html')

@app.route('/api/dashboard_stats')
@login_required
def dashboard_stats():
    if current_user.role not in ['hr', 'supervisor']:
        return jsonify({"error": "Permission denied"}), 403
    total_employees = User.query.count()
    on_leave_today = LeaveRequest.query.filter(LeaveRequest.status=='Approved', LeaveRequest.start_date <= datetime.today().date(), LeaveRequest.end_date >= datetime.today().date()).count()
    pending_requests = LeaveRequest.query.filter(LeaveRequest.status=='Pending').count()
    today = datetime.today()
    leave_type_data = db.session.query(LeaveRequest.leave_type, func.count(LeaveRequest.id)).filter(
        db.extract('month', LeaveRequest.start_date) == today.month, db.extract('year', LeaveRequest.start_date) == today.year, LeaveRequest.status == 'Approved'
    ).group_by(LeaveRequest.leave_type).all()
    leave_type_breakdown = {'labels': [item[0] for item in leave_type_data], 'data': [item[1] for item in leave_type_data]}
    labels = []; data = []
    for i in range(5, -1, -1):
        target_date = today.replace(day=1) - timedelta(days=i*30)
        labels.append(target_date.strftime("%B %Y"))
        monthly_leaves = LeaveRequest.query.filter(
            db.extract('month', LeaveRequest.start_date) == target_date.month,
            db.extract('year', LeaveRequest.start_date) == target_date.year,
            LeaveRequest.status == 'Approved'
        ).count()
        data.append(monthly_leaves)
    leave_trend = {'labels': labels, 'data': data}
    return jsonify({'total_employees': total_employees, 'on_leave_today': on_leave_today, 'pending_requests': pending_requests, 'leave_type_breakdown': leave_type_breakdown, 'leave_trend': leave_trend})

@app.cli.command("init-db")
def init_db_command():
    """Clears the existing data and creates new tables."""
    db.create_all()
    print("Initialized the database.")