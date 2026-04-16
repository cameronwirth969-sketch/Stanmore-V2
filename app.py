#!/usr/bin/env python3
"""
Stanmore V2 - School Resource Website
Single-file Flask application for Render.com deployment
Hidden admin login at /login | Credentials: admin / cocopops18@
"""

import os
import uuid
import secrets
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (
    Flask, render_template_string, request, redirect, url_for, 
    flash, send_from_directory, abort, session, jsonify
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm, CSRFProtect
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, SelectField, IntegerField, SubmitField, PasswordField
from wtforms.validators import DataRequired, NumberRange, Length

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', secrets.token_urlsafe(32))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max upload
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    ALLOWED_EXTENSIONS = {'pdf'}
    
    # Admin credentials (use env vars in production)
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD_HASH = os.getenv('ADMIN_PASSWORD_HASH')
    
    @staticmethod
    def init_app(app):
        os.makedirs(os.path.join(Config.UPLOAD_FOLDER, 'pdfs'), exist_ok=True)
        os.makedirs(os.path.join(Config.UPLOAD_FOLDER, 'timetables'), exist_ok=True)

# ============================================================================
# EXTENSIONS
# ============================================================================

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth_login'
csrf = CSRFProtect()

# ============================================================================
# MODELS
# ============================================================================

class Admin(UserMixin, db.Model):
    __tablename__ = 'admin'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Grade(db.Model):
    __tablename__ = 'grades'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(10), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    
    def __repr__(self):
        return f'<Grade {self.name}>'


class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    grade_id = db.Column(db.Integer, db.ForeignKey('grades.id'), nullable=False)
    
    __table_args__ = (db.UniqueConstraint('name', 'grade_id', name='uq_subject_grade'),)


class Resource(db.Model):
    __tablename__ = 'resources'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    term = db.Column(db.Integer, db.CheckConstraint('term BETWEEN 1 AND 4'), nullable=False)
    resource_type = db.Column(db.String(50), default='note')
    display_order = db.Column(db.Integer, default=0)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    subject = db.relationship('Subject', backref='resources')
    
    def __repr__(self):
        return f'<Resource {self.title}>'


class ExamTimetable(db.Model):
    __tablename__ = 'exam_timetables'
    id = db.Column(db.Integer, primary_key=True)
    grade_id = db.Column(db.Integer, db.ForeignKey('grades.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    academic_year = db.Column(db.Integer, default=2026)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    grade = db.relationship('Grade', backref='timetables')


# ============================================================================
# FORMS
# ============================================================================

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class PDFUploadForm(FlaskForm):
    title = StringField('Resource Title', validators=[DataRequired(), Length(max=200)])
    grade = SelectField('Grade', choices=[
        ('8', 'Grade 8'), ('9', 'Grade 9'), 
        ('10', 'Grade 10'), ('11', 'Grade 11'), ('12', 'Grade 12')
    ], validators=[DataRequired()])
    subject = SelectField('Subject', choices=[], validators=[DataRequired()])
    term = SelectField('Term', choices=[(1,'Term 1'),(2,'Term 2'),(3,'Term 3'),(4,'Term 4')], validators=[DataRequired()])
    resource_type = SelectField('Type', choices=[
        ('note', 'Study Notes'), ('worksheet', 'Worksheet'), 
        ('exam', 'Exam Paper'), ('memo', 'Memo')
    ], default='note')
    display_order = IntegerField('Display Order (0 = auto)', default=0)
    pdf_file = FileField('PDF File', validators=[FileRequired(), FileAllowed(['pdf'], 'PDF files only!')])
    submit = SubmitField('Upload Resource')


class TimetableUploadForm(FlaskForm):
    grade = SelectField('Grade', choices=[
        ('10', 'Grade 10'), ('11', 'Grade 11'), ('12', 'Grade 12')
    ], validators=[DataRequired()])
    academic_year = IntegerField('Academic Year', default=2026, validators=[NumberRange(min=2020, max=2030)])
    timetable_file = FileField('Exam Timetable PDF', validators=[FileRequired(), FileAllowed(['pdf'], 'PDF files only!')])
    submit = SubmitField('Upload Timetable')


# ============================================================================
# UTILITIES
# ============================================================================

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def generate_secure_filename(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'pdf'
    return f"{uuid.uuid4().hex}.{ext}"


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function


def init_database():
    """Initialize database with default grades and subjects"""
    grades_data = [('8', False), ('9', False), ('10', True), ('11', True), ('12', True)]
    for name, is_active in grades_data:
        if not Grade.query.filter_by(name=name).first():
            db.session.add(Grade(name=name, is_active=is_active))
    db.session.commit()
    
    subjects_list = [
        'Mathematics', 'Mathematical Literacy', 'Information Technology',
        'Accounting', 'English', 'Life Sciences', 'Geography', 'Business Studies',
        'Afrikaans', 'IsiZulu', 'Life Orientation', 'Economics', 'History',
        'IsiXhosa', 'Physics'
    ]
    
    for grade_name in ['10', '11', '12']:
        grade = Grade.query.filter_by(name=grade_name).first()
        if grade:
            for subj_name in subjects_list:
                if not Subject.query.filter_by(name=subj_name, grade_id=grade.id).first():
                    db.session.add(Subject(name=subj_name, grade_id=grade.id))
    db.session.commit()


def create_admin():
    """Create default admin user if not exists"""
    if not Admin.query.filter_by(username=Config.ADMIN_USERNAME).first():
        admin = Admin(username=Config.ADMIN_USERNAME)
        admin.set_password('cocopops18@')
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin user created: admin / cocopops18@")


# ============================================================================
# TEMPLATES (Embedded HTML)
# ============================================================================

BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Stanmore V2{% endblock %}</title>
    <style>
        :root{--primary:#1a3a6c;--secondary:#e63946;--light:#f8f9fa;--dark:#212529;--success:#28a745;--warning:#ffc107}
        *{box-sizing:border-box;margin:0;padding:0}body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;line-height:1.6;color:var(--dark);background:var(--light)}
        .navbar{background:var(--primary);padding:1rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap}
        .navbar-brand{color:white;font-weight:bold;font-size:1.5rem;text-decoration:none}
        .nav-links a{color:rgba(255,255,255,0.9);margin-left:1.5rem;text-decoration:none;font-weight:500}
        .nav-links a:hover{color:white}.nav-links a.btn-login{background:var(--secondary);padding:0.5rem 1rem;border-radius:4px}
        .container{max-width:1200px;margin:0 auto;padding:2rem 1rem}
        .coming-soon{background:var(--warning);color:var(--dark);padding:0.25rem 0.75rem;border-radius:20px;font-size:0.85rem;font-weight:600;display:inline-block;margin-left:0.5rem}
        .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:1.5rem;padding:1rem}
        .card{background:white;border-radius:8px;padding:1.5rem;box-shadow:0 2px 8px rgba(0,0,0,0.1);transition:transform 0.2s}
        .card:hover{transform:translateY(-3px)}.card h3{color:var(--primary);margin-bottom:0.5rem}
        .meta{font-size:0.9rem;color:#666;margin:0.5rem 0}.btn{display:inline-block;background:var(--primary);color:white;padding:0.5rem 1.25rem;border-radius:4px;text-decoration:none;font-weight:500;margin-top:1rem;border:none;cursor:pointer}
        .btn:hover{background:#152e55}.btn-danger{background:var(--secondary)}.btn-danger:hover{background:#c1121f}
        .form-group{margin-bottom:1rem}.form-group label{display:block;margin-bottom:0.5rem;font-weight:500}
        .form-group input,.form-group select{width:100%;padding:0.75rem;border:1px solid #ddd;border-radius:4px;font-size:1rem}
        .flash{padding:1rem;margin-bottom:1rem;border-radius:4px}.flash.success{background:#d4edda;color:#155724;border:1px solid #c3e6cb}
        .flash.error{background:#f8d7da;color:#721c24;border:1px solid #f5c6cb}.flash.info{background:#cce5ff;color:#004085;border:1px solid #b8daff}
        .drag-handle{cursor:move;padding:0.5rem;color:#999;margin-right:0.5rem}.draggable{background:white;border:1px solid #ddd;border-radius:6px;padding:1rem;margin-bottom:0.75rem;display:flex;align-items:center;justify-content:space-between}
        .term-section{margin-bottom:2rem}.term-title{background:var(--primary);color:white;padding:0.75rem 1rem;border-radius:4px;margin-bottom:1rem}
        .resource-list{list-style:none}.resource-list li{padding:0.75rem;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center}
        .resource-list li:last-child{border-bottom:none}
        @media(max-width:768px){.navbar{flex-direction:column;align-items:flex-start}.nav-links{margin-top:1rem;display:flex;flex-wrap:wrap;gap:0.75rem}.nav-links a{margin-left:0}.grid{grid-template-columns:1fr}}
    </style>
</head>
<body>
    <nav class="navbar">
        <a href="/" class="navbar-brand">🎓 Stanmore V2</a>
        <div class="nav-links">
            <a href="/">Home</a>
            <a href="/grades">Grades</a>
            <a href="/exam-timetables">Exam Timetable</a>
            {% if current_user.is_authenticated %}
                <a href="/admin/dashboard">Admin</a>
                <a href="/login/logout">Logout</a>
            {% endif %}
        </div>
    </nav>
    
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash {{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        {% block content %}{% endblock %}
    </div>
    
    <script>
        // Drag & drop reordering for admin
        document.addEventListener('DOMContentLoaded', function() {
            const draggables = document.querySelectorAll('.draggable');
            draggables.forEach(draggable => {
                draggable.addEventListener('dragstart', () => draggable.classList.add('dragging'));
                draggable.addEventListener('dragend', () => {
                    draggable.classList.remove('dragging');
                    // Save new order via AJAX
                    const items = document.querySelectorAll('.draggable');
                    const order = Array.from(items).map((item, index) => ({
                        id: item.dataset.id,
                        order: index
                    }));
                    fetch('/admin/reorder-pdfs', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({items: order})
                    });
                });
            });
        });
        
        // Dynamic subject loading based on grade selection
        function loadSubjects(gradeId, subjectSelectId) {
            fetch(`/admin/subjects?grade=${gradeId}`)
                .then(r => r.json())
                .then(data => {
                    const select = document.getElementById(subjectSelectId);
                    select.innerHTML = '<option value="">Select Subject</option>';
                    data.subjects.forEach(s => {
                        const opt = document.createElement('option');
                        opt.value = s.id;
                        opt.textContent = s.name;
                        select.appendChild(opt);
                    });
                });
        }
    </script>
    {% block scripts %}{% endblock %}
</body>
</html>
'''

LOGIN_TEMPLATE = '''
{% extends "base" %}
{% block title %}Admin Login - Stanmore V2{% endblock %}
{% block content %}
<div style="max-width:400px;margin:3rem auto;background:white;padding:2rem;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,0.1)">
    <h2 style="color:var(--primary);margin-bottom:1.5rem;text-align:center">🔐 Admin Login</h2>
    <form method="POST">
        {{ form.csrf_token }}
        <div class="form-group">
            <label for="username">Username</label>
            {{ form.username(class="form-control", id="username") }}
        </div>
        <div class="form-group">
            <label for="password">Password</label>
            {{ form.password(class="form-control", id="password") }}
        </div>
        {{ form.submit(class="btn", style="width:100%") }}
    </form>
    <p style="margin-top:1rem;font-size:0.9rem;color:#666;text-align:center">
        ⚠️ This page is hidden from public navigation
    </p>
</div>
{% endblock %}
'''

INDEX_TEMPLATE = '''
{% extends "base" %}
{% block content %}
<div style="text-align:center;padding:3rem 1rem">
    <h1 style="color:var(--primary);font-size:2.5rem;margin-bottom:1rem">Welcome to Stanmore V2</h1>
    <p style="font-size:1.2rem;color:#555;margin-bottom:2rem">Your trusted source for Grade 10-12 study resources</p>
    
    <div style="display:flex;gap:1rem;justify-content:center;flex-wrap:wrap;margin-bottom:3rem">
        <a href="/grades" class="btn">📚 Browse by Grade</a>
        <a href="/exam-timetables" class="btn">🗓️ Exam Timetables</a>
    </div>
    
    <h3 style="color:var(--primary);margin:2rem 0 1rem">Available Grades</h3>
    <div class="grid">
        {% for grade in active_grades %}
        <div class="card">
            <h3>Grade {{ grade.name }}</h3>
            <p class="meta">{{ grade.subjects|length }} subjects available</p>
            <a href="/grade/{{ grade.name }}" class="btn">View Resources</a>
        </div>
        {% endfor %}
        {% for grade in coming_soon %}
        <div class="card" style="opacity:0.7">
            <h3>Grade {{ grade.name }} <span class="coming-soon">Coming Soon</span></h3>
            <p class="meta">Resources being prepared</p>
            <button class="btn" disabled>Not Available</button>
        </div>
        {% endfor %}
    </div>
</div>
{% endblock %}
'''

GRADES_TEMPLATE = '''
{% extends "base" %}
{% block title %}Grades - Stanmore V2{% endblock %}
{% block content %}
<h2 style="color:var(--primary);margin-bottom:1.5rem">📚 Select a Grade</h2>
<div class="grid">
    {% for grade in grades %}
    <div class="card">
        <h3>
            Grade {{ grade.name }}
            {% if not grade.is_active %}<span class="coming-soon">Coming Soon</span>{% endif %}
        </h3>
        {% if grade.is_active %}
        <p class="meta">{{ grade.subjects|length }} subjects • Terms 1-4</p>
        <a href="/grade/{{ grade.name }}" class="btn">Browse Subjects</a>
        {% else %}
        <p class="meta">Study materials coming soon for Grade {{ grade.name }}</p>
        <button class="btn" disabled>Coming Soon</button>
        {% endif %}
    </div>
    {% endfor %}
</div>
{% endblock %}
'''

SUBJECTS_TEMPLATE = '''
{% extends "base" %}
{% block title %}{{ grade.name }} Subjects - Stanmore V2{% endblock %}
{% block content %}
<h2 style="color:var(--primary);margin-bottom:1.5rem">📖 Grade {{ grade.name }} Subjects</h2>
<p style="margin-bottom:2rem"><a href="/grades" style="color:var(--primary)">← Back to Grades</a></p>

<div class="grid">
    {% for subject in subjects %}
    <div class="card">
        <h3>{{ subject.name }}</h3>
        <p class="meta">Terms 1-4 available</p>
        <a href="/grade/{{ grade.name }}/subject/{{ subject.name }}" class="btn">View Resources</a>
    </div>
    {% endfor %}
</div>
{% endblock %}
'''

RESOURCES_TEMPLATE = '''
{% extends "base" %}
{% block title %}{{ subject.name }} - Grade {{ grade.name }}{% endblock %}
{% block content %}
<h2 style="color:var(--primary);margin-bottom:0.5rem">{{ subject.name }}</h2>
<p style="margin-bottom:2rem;color:#666">Grade {{ grade.name }} • Select a Term</p>
<p style="margin-bottom:1rem"><a href="/grade/{{ grade.name }}" style="color:var(--primary)">← Back to Subjects</a></p>

{% for term_num in [1,2,3,4] %}
<div class="term-section">
    <h3 class="term-title">Term {{ term_num }}</h3>
    {% if terms[term_num] %}
    <ul class="resource-list">
        {% for resource in terms[term_num] %}
        <li>
            <div>
                <strong>{{ resource.title }}</strong>
                <span class="meta" style="margin-left:0.5rem">[{{ resource.resource_type }}]</span>
            </div>
            <a href="/download/{{ resource.filename|replace('pdfs/','') }}" class="btn" style="padding:0.35rem 0.75rem;font-size:0.9rem">Download</a>
        </li>
        {% endfor %}
    </ul>
    {% else %}
    <p style="color:#666;padding:0.5rem 0">No resources available for this term yet.</p>
    {% endif %}
</div>
{% endfor %}
{% endblock %}
'''

TIMETABLES_TEMPLATE = '''
{% extends "base" %}
{% block title %}Exam Timetables - Stanmore V2{% endblock %}
{% block content %}
<h2 style="color:var(--primary);margin-bottom:1.5rem">🗓️ Exam Timetables</h2>

<div style="background:white;padding:1.5rem;border-radius:8px;margin-bottom:2rem">
    <label style="font-weight:500;margin-right:1rem">Select Grade:</label>
    {% for g in grades %}
    <a href="/exam-timetables?grade={{ g.id }}" 
       style="display:inline-block;padding:0.5rem 1rem;margin:0.25rem;border-radius:4px;text-decoration:none;background:{% if selected_grade==g.id %}var(--primary);color:white{% else %}#eee;color:var(--dark){% endif %}">
        Grade {{ g.name }}
    </a>
    {% endfor %}
</div>

{% if selected_grade %}
    {% if timetable %}
    <div class="card">
        <h3 style="color:var(--primary);margin-bottom:1rem">📄 {{ timetable.original_filename }}</h3>
        <p class="meta">Academic Year: {{ timetable.academic_year }} • Uploaded: {{ timetable.uploaded_at.strftime('%Y-%m-%d') }}</p>
        <a href="/download-timetable/{{ timetable.filename|replace('timetables/','') }}" class="btn">Download Timetable</a>
    </div>
    {% else %}
    <div class="card" style="text-align:center;padding:2rem">
        <p style="color:#666;margin-bottom:1rem">No exam timetable uploaded yet for Grade {{ selected_grade }}.</p>
        <p style="font-size:0.9rem;color:#999">Check back soon or contact your teacher.</p>
    </div>
    {% endif %}
{% else %}
<p style="color:#666">Select a grade above to view its exam timetable.</p>
{% endif %}

{% if selected_grade and selected_grade in [8,9] %}
<div class="card" style="margin-top:1rem;background:#fff3cd;border-left:4px solid #ffc107">
    <strong>⚠️ Note:</strong> Grade {{ selected_grade }} exam timetables are <span class="coming-soon">Coming Soon</span>
</div>
{% endif %}
{% endblock %}
'''

ADMIN_DASHBOARD_TEMPLATE = '''
{% extends "base" %}
{% block title %}Admin Dashboard - Stanmore V2{% endblock %}
{% block content %}
<h2 style="color:var(--primary);margin-bottom:1.5rem">👨‍💼 Admin Dashboard</h2>

<div class="grid" style="margin-bottom:2rem">
    <div class="card">
        <h3>📊 Statistics</h3>
        <p class="meta"><strong>{{ stats.total_resources }}</strong> resources uploaded</p>
        <p class="meta"><strong>{{ stats.active_grades }}</strong> active grades</p>
        <p class="meta"><strong>{{ stats.timetables }}</strong> exam timetables</p>
    </div>
    <div class="card">
        <h3>⚡ Quick Actions</h3>
        <a href="/admin/upload-pdf" class="btn" style="margin:0.25rem 0">📤 Upload PDF</a>
        <a href="/admin/manage-pdfs" class="btn" style="margin:0.25rem 0">📋 Manage Resources</a>
        <a href="/admin/timetables" class="btn" style="margin:0.25rem 0">🗓️ Manage Timetables</a>
    </div>
</div>

<h3 style="color:var(--primary);margin:1.5rem 0 1rem">Recent Uploads</h3>
{% if recent %}
<div style="background:white;border-radius:8px;overflow:hidden">
    {% for r in recent %}
    <div style="padding:1rem;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center">
        <div>
            <strong>{{ r.title }}</strong>
            <span class="meta" style="margin-left:0.5rem">Grade {{ r.subject.grade.name }} • {{ r.subject.name }} • Term {{ r.term }}</span>
        </div>
        <span style="font-size:0.85rem;color:#666">{{ r.uploaded_at.strftime('%Y-%m-%d') }}</span>
    </div>
    {% endfor %}
</div>
{% else %}
<p style="color:#666">No resources uploaded yet.</p>
{% endif %}
{% endblock %}
'''

UPLOAD_PDF_TEMPLATE = '''
{% extends "base" %}
{% block title %}Upload PDF - Admin{% endblock %}
{% block content %}
<h2 style="color:var(--primary);margin-bottom:1.5rem">📤 Upload New Resource</h2>
<p style="margin-bottom:1.5rem"><a href="/admin/dashboard" style="color:var(--primary)">← Back to Dashboard</a></p>

<div class="card" style="max-width:600px;margin:0 auto">
    <form method="POST" enctype="multipart/form-data">
        {{ form.csrf_token }}
        
        <div class="form-group">
            <label for="title">Resource Title *</label>
            {{ form.title(class="form-control") }}
        </div>
        
        <div class="form-group">
            <label for="grade">Grade *</label>
            {{ form.grade(class="form-control", onchange="loadSubjects(this.value, 'subject')") }}
        </div>
        
        <div class="form-group">
            <label for="subject">Subject *</label>
            {{ form.subject(class="form-control", id="subject") }}
        </div>
        
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
            <div class="form-group">
                <label for="term">Term *</label>
                {{ form.term(class="form-control") }}
            </div>
            <div class="form-group">
                <label for="resource_type">Type</label>
                {{ form.resource_type(class="form-control") }}
            </div>
        </div>
        
        <div class="form-group">
            <label for="display_order">Display Order (0 = auto-sort)</label>
            {{ form.display_order(class="form-control") }}
        </div>
        
        <div class="form-group">
            <label for="pdf_file">PDF File *</label>
            {{ form.pdf_file(class="form-control", accept=".pdf") }}
            <small style="color:#666">Max 50MB • PDF only</small>
        </div>
        
        {{ form.submit(class="btn", style="width:100%") }}
    </form>
</div>

<script>
    // Auto-load subjects if grade is pre-selected
    const gradeSelect = document.querySelector('select[name="grade"]');
    if(gradeSelect.value) loadSubjects(gradeSelect.value, 'subject');
</script>
{% endblock %}
'''

MANAGE_PDFS_TEMPLATE = '''
{% extends "base" %}
{% block title %}Manage Resources - Admin{% endblock %}
{% block content %}
<h2 style="color:var(--primary);margin-bottom:1.5rem">📋 Manage Resources</h2>
<p style="margin-bottom:1.5rem">
    <a href="/admin/dashboard" style="color:var(--primary)">← Dashboard</a> | 
    <a href="/admin/upload-pdf" style="color:var(--primary)">+ Upload New</a>
</p>

<p style="color:#666;margin-bottom:1rem"><strong>💡 Tip:</strong> Drag items to reorder, or set numeric display order during upload.</p>

<div style="background:white;border-radius:8px;padding:1rem">
    {% if resources %}
        {% for resource in resources|sort(attribute='display_order') %}
        <div class="draggable" data-id="{{ resource.id }}" draggable="true">
            <div style="display:flex;align-items:center">
                <span class="drag-handle">☰</span>
                <div>
                    <strong>{{ resource.title }}</strong>
                    <div class="meta">
                        Grade {{ resource.subject.grade.name }} • {{ resource.subject.name }} • Term {{ resource.term }} • {{ resource.resource_type }}
                    </div>
                </div>
            </div>
            <div style="display:flex;gap:0.5rem">
                <a href="/download/{{ resource.filename|replace('pdfs/','') }}" class="btn" style="padding:0.35rem 0.75rem;font-size:0.85rem">View</a>
                <form method="POST" action="/admin/delete-pdf/{{ resource.id }}" style="display:inline" onsubmit="return confirm('Delete this resource?');">
                    <button type="submit" class="btn btn-danger" style="padding:0.35rem 0.75rem;font-size:0.85rem">Delete</button>
                </form>
            </div>
        </div>
        {% endfor %}
    {% else %}
        <p style="color:#666;text-align:center;padding:2rem">No resources uploaded yet.</p>
    {% endif %}
</div>
{% endblock %}
'''

MANAGE_TIMETABLES_TEMPLATE = '''
{% extends "base" %}
{% block title %}Manage Timetables - Admin{% endblock %}
{% block content %}
<h2 style="color:var(--primary);margin-bottom:1.5rem">🗓️ Manage Exam Timetables</h2>
<p style="margin-bottom:1.5rem"><a href="/admin/dashboard" style="color:var(--primary)">← Back to Dashboard</a></p>

<div class="card" style="max-width:600px;margin-bottom:2rem">
    <h3 style="margin-bottom:1rem">Upload New Timetable</h3>
    <form method="POST" enctype="multipart/form-data">
        {{ form.csrf_token }}
        
        <div class="form-group">
            <label for="grade">Grade *</label>
            {{ form.grade(class="form-control") }}
        </div>
        
        <div class="form-group">
            <label for="academic_year">Academic Year</label>
            {{ form.academic_year(class="form-control") }}
        </div>
        
        <div class="form-group">
            <label for="timetable_file">Timetable PDF *</label>
            {{ form.timetable_file(class="form-control", accept=".pdf") }}
        </div>
        
        {{ form.submit(class="btn", style="width:100%") }}
    </form>
</div>

<h3 style="color:var(--primary);margin:1.5rem 0 1rem">Uploaded Timetables</h3>
{% if timetables %}
<div style="background:white;border-radius:8px;overflow:hidden">
    {% for t in timetables %}
    <div style="padding:1rem;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center">
        <div>
            <strong>Grade {{ t.grade.name }}</strong>
            <span class="meta" style="margin-left:0.5rem">{{ t.original_filename }} • {{ t.academic_year }}</span>
        </div>
        <div style="display:flex;gap:0.5rem">
            <a href="/download-timetable/{{ t.filename|replace('timetables/','') }}" class="btn" style="padding:0.35rem 0.75rem;font-size:0.85rem">Download</a>
            <form method="POST" action="/admin/delete-timetable/{{ t.id }}" style="display:inline" onsubmit="return confirm('Delete this timetable?');">
                <button type="submit" class="btn btn-danger" style="padding:0.35rem 0.75rem;font-size:0.85rem">Delete</button>
            </form>
        </div>
    </div>
    {% endfor %}
</div>
{% else %}
<p style="color:#666">No timetables uploaded yet.</p>
{% endif %}
{% endblock %}
'''

# Template mapping
TEMPLATES = {
    'base': BASE_TEMPLATE,
    'login': LOGIN_TEMPLATE,
    'index': INDEX_TEMPLATE,
    'grades': GRADES_TEMPLATE,
    'subjects': SUBJECTS_TEMPLATE,
    'resources': RESOURCES_TEMPLATE,
    'timetables': TIMETABLES_TEMPLATE,
    'admin/dashboard': ADMIN_DASHBOARD_TEMPLATE,
    'admin/upload_pdf': UPLOAD_PDF_TEMPLATE,
    'admin/manage_pdfs': MANAGE_PDFS_TEMPLATE,
    'admin/timetables': MANAGE_TIMETABLES_TEMPLATE,
}


def render_template(template_name, **context):
    """Custom render using embedded templates"""
    template_str = TEMPLATES.get(template_name, TEMPLATES['base'])
    # Simple template rendering (production should use Jinja2 properly)
    from jinja2 import Template
    return Template(template_str).render(
        **context,
        render_template_string=lambda t, **kw: Template(t).render(**kw),
        get_flashed_messages=lambda with_categories=False: []
    )


# ============================================================================
# FLASK APP & ROUTES
# ============================================================================

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    Config.init_app(app)
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    
    # Create tables and init data
    with app.app_context():
        db.create_all()
        init_database()
        create_admin()
    
    # ========================================================================
    # AUTH ROUTES
    # ========================================================================
    
    @app.route('/login', methods=['GET', 'POST'])
    def auth_login():
        if current_user.is_authenticated:
            return redirect(url_for('admin_dashboard'))
        
        form = LoginForm()
        if form.validate_on_submit():
            admin = Admin.query.filter_by(username=form.username.data).first()
            if admin and admin.check_password(form.password.data):
                login_user(admin)
                flash('Welcome back, Admin!', 'success')
                return redirect(url_for('admin_dashboard'))
            flash('Invalid credentials', 'error')
        return render_template('login', form=form)
    
    @app.route('/login/logout')
    @login_required
    def auth_logout():
        logout_user()
        flash('Logged out successfully', 'info')
        return redirect(url_for('public_index'))
    
    # ========================================================================
    # PUBLIC ROUTES
    # ========================================================================
    
    @app.route('/')
    def public_index():
        active = Grade.query.filter_by(is_active=True).all()
        coming = Grade.query.filter_by(is_active=False).all()
        return render_template('index', active_grades=active, coming_soon=coming)
    
    @app.route('/grades')
    def public_grades():
        grades = Grade.query.order_by(Grade.name).all()
        return render_template('grades', grades=grades)
    
    @app.route('/grade/<grade_name>')
    def public_grade_subjects(grade_name):
        grade = Grade.query.filter_by(name=grade_name).first_or_404()
        subjects = Subject.query.filter_by(grade_id=grade.id).all()
        return render_template('subjects', grade=grade, subjects=subjects)
    
    @app.route('/grade/<grade_name>/subject/<subject_name>')
    def public_subject_resources(grade_name, subject_name):
        grade = Grade.query.filter_by(name=grade_name).first_or_404()
        subject = Subject.query.filter_by(name=subject_name, grade_id=grade.id).first_or_404()
        terms = {1: [], 2: [], 3: [], 4: []}
        for r in Resource.query.filter_by(subject_id=subject.id).order_by(Resource.display_order).all():
            terms[r.term].append(r)
        return render_template('resources', grade=grade, subject=subject, terms=terms)
    
    @app.route('/download/<path:filename>')
    def public_download(filename):
        resource = Resource.query.filter_by(filename=f"pdfs/{filename}").first()
        if not resource:
            abort(404)
        return send_from_directory(
            os.path.join(Config.UPLOAD_FOLDER, 'pdfs'),
            filename,
            as_attachment=True,
            download_name=resource.original_filename
        )
    
    @app.route('/exam-timetables')
    def public_timetables():
        grades = Grade.query.filter(Grade.name.in_(['10','11','12'])).all()
        selected = request.args.get('grade', type=int)
        timetable = ExamTimetable.query.filter_by(grade_id=selected).first() if selected else None
        return render_template('timetables', grades=grades, selected_grade=selected, timetable=timetable)
    
    @app.route('/download-timetable/<path:filename>')
    def public_download_timetable(filename):
        tt = ExamTimetable.query.filter_by(filename=f"timetables/{filename}").first_or_404()
        return send_from_directory(
            os.path.join(Config.UPLOAD_FOLDER, 'timetables'),
            filename,
            as_attachment=True,
            download_name=tt.original_filename
        )
    
    # ========================================================================
    # ADMIN ROUTES
    # ========================================================================
    
    @app.route('/admin/dashboard')
    @admin_required
    def admin_dashboard():
        stats = {
            'total_resources': Resource.query.count(),
            'active_grades': Grade.query.filter_by(is_active=True).count(),
            'timetables': ExamTimetable.query.count()
        }
        recent = Resource.query.order_by(Resource.uploaded_at.desc()).limit(5).all()
        return render_template('admin/dashboard', stats=stats, recent=recent)
    
    @app.route('/admin/subjects')
    @admin_required
    def admin_get_subjects():
        """AJAX: Get subjects for a grade"""
        grade_id = request.args.get('grade', type=int)
        subjects = Subject.query.filter_by(grade_id=grade_id).all()
        return jsonify({'subjects': [{'id': s.id, 'name': s.name} for s in subjects]})
    
    @app.route('/admin/upload-pdf', methods=['GET', 'POST'])
    @admin_required
    def admin_upload_pdf():
        form = PDFUploadForm()
        # Populate subjects dynamically via JS, but provide fallback
        if request.method == 'POST' and form.validate_on_submit():
            file = request.files['pdf_file']
            if file and allowed_file(file.filename):
                secure_name = generate_secure_filename(file.filename)
                filepath = f"pdfs/{secure_name}"
                file.save(os.path.join(Config.UPLOAD_FOLDER, filepath))
                
                resource = Resource(
                    title=form.title.data,
                    filename=filepath,
                    original_filename=secure_filename(file.filename),
                    subject_id=form.subject.data,
                    term=form.term.data,
                    resource_type=form.resource_type.data,
                    display_order=form.display_order.data or Resource.query.count() + 1
                )
                db.session.add(resource)
                db.session.commit()
                flash(f'✅ {form.title.data} uploaded!', 'success')
                return redirect(url_for('admin_manage_pdfs'))
        return render_template('admin/upload_pdf', form=form)
    
    @app.route('/admin/manage-pdfs')
    @admin_required
    def admin_manage_pdfs():
        resources = Resource.query.order_by(Resource.display_order).all()
        return render_template('admin/manage_pdfs', resources=resources)
    
    @app.route('/admin/reorder-pdfs', methods=['POST'])
    @admin_required
    def admin_reorder_pdfs():
        data = request.get_json()
        for item in data.get('items', []):
            r = Resource.query.get(item['id'])
            if r:
                r.display_order = item['order']
        db.session.commit()
        return jsonify({'success': True})
    
    @app.route('/admin/delete-pdf/<int:resource_id>', methods=['POST'])
    @admin_required
    def admin_delete_pdf(resource_id):
        resource = Resource.query.get_or_404(resource_id)
        # Note: Add actual file deletion in production
        db.session.delete(resource)
        db.session.commit()
        flash('Resource deleted', 'info')
        return redirect(url_for('admin_manage_pdfs'))
    
    @app.route('/admin/timetables', methods=['GET', 'POST'])
    @admin_required
    def admin_manage_timetables():
        form = TimetableUploadForm()
        if form.validate_on_submit():
            file = request.files['timetable_file']
            if file and allowed_file(file.filename):
                secure_name = generate_secure_filename(f"tt_g{form.grade.data}_{form.academic_year.data}.pdf")
                filepath = f"timetables/{secure_name}"
                file.save(os.path.join(Config.UPLOAD_FOLDER, filepath))
                
                ExamTimetable.query.filter_by(
                    grade_id=form.grade.data,
                    academic_year=form.academic_year.data
                ).delete()
                
                tt = ExamTimetable(
                    grade_id=form.grade.data,
                    filename=filepath,
                    original_filename=secure_filename(file.filename),
                    academic_year=form.academic_year.data
                )
                db.session.add(tt)
                db.session.commit()
                flash('✅ Timetable uploaded!', 'success')
                return redirect(url_for('admin_manage_timetables'))
        
        timetables = ExamTimetable.query.all()
        return render_template('admin/timetables', form=form, timetables=timetables)
    
    @app.route('/admin/delete-timetable/<int:tt_id>', methods=['POST'])
    @admin_required
    def admin_delete_timetable(tt_id):
        tt = ExamTimetable.query.get_or_404(tt_id)
        db.session.delete(tt)
        db.session.commit()
        flash('Timetable deleted', 'info')
        return redirect(url_for('admin_manage_timetables'))
    
    return app


# ============================================================================
# ENTRY POINT
# ============================================================================

app = create_app()

if __name__ == '__main__':
    # Development server
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))