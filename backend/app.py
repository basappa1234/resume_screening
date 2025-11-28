"""
Flask Web Application for Resume Screening Agent
Allows users to upload resumes and job descriptions via web interface
"""

import os
import json
# Load environment variables safely
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception as e:
    print(f"Warning: Could not load .env file: {e}")

from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from werkzeug.utils import secure_filename
from resume_screening_agent import ResumeScreeningAgent, Resume, JobDescription
from file_parser import FileParser
from database import ScreeningDatabase
from export_utils import export_to_pdf, export_to_excel
from email_utils import EmailNotifier
from groq import Groq
from dataclasses import asdict
from datetime import datetime

# Set paths for templates and static files
template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'templates')
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'static')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'docx', 'doc', 'txt'}

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize database with absolute path
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screening_history.db')
db = ScreeningDatabase(db_path=db_path)


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def parse_resume_with_ai(text, filename, agent):
    """
    Use AI to extract structured information from resume text
    
    Args:
        text: Resume text content
        filename: Original filename
        agent: ResumeScreeningAgent instance
        
    Returns:
        Resume object with extracted information
    """
    prompt = f"""Extract the following information from this resume and return ONLY valid JSON:

RESUME TEXT:
{text}

Return JSON in this exact format:
{{
    "name": "Full Name",
    "email": "email@example.com",
    "phone": "+1-234-567-8900",
    "skills": ["skill1", "skill2", ...],
    "experience": [
        {{
            "title": "Job Title",
            "company": "Company Name",
            "duration": "2020-2023",
            "description": "Brief description"
        }}
    ],
    "education": [
        {{
            "degree": "Degree Name",
            "field": "Field of Study",
            "institution": "University Name",
            "year": "2020"
        }}
    ],
    "summary": "Brief professional summary"
}}

Extract what you can. Use "N/A" for missing information. Return ONLY valid JSON, no markdown."""

    try:
        response = agent.client.chat.completions.create(
            model=agent.model,
            messages=[
                {"role": "system", "content": "You are a resume parsing expert. Extract information and return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=1500
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Extract JSON from response
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()
        
        data = json.loads(result_text)
        
        return Resume(
            id=filename.replace('.', '_'),
            name=data.get('name', 'Candidate'),
            email=data.get('email', ''),
            phone=data.get('phone', ''),
            skills=data.get('skills', []),
            experience=data.get('experience', []),
            education=data.get('education', []),
            summary=data.get('summary', text[:300])
        )
    except Exception as e:
        print(f"Error parsing resume with AI: {e}")
        # Fallback to basic parsing
        return Resume(
            id=filename.replace('.', '_'),
            name=filename.replace('_', ' ').replace('.pdf', '').replace('.docx', '').replace('.txt', ''),
            email='',
            phone='',
            skills=[],
            experience=[],
            education=[],
            summary=text[:300] if len(text) > 300 else text
        )


def parse_job_description_with_ai(text, agent):
    """
    Use AI to extract structured information from job description text
    
    Args:
        text: Job description text content
        agent: ResumeScreeningAgent instance
        
    Returns:
        JobDescription object with extracted information
    """
    prompt = f"""Extract the following information from this job description and return ONLY valid JSON:

JOB DESCRIPTION TEXT:
{text}

Return JSON in this exact format:
{{
    "title": "Job Title",
    "company": "Company Name",
    "required_skills": ["skill1", "skill2", ...],
    "preferred_skills": ["skill1", "skill2", ...],
    "experience_years": 5,
    "responsibilities": ["responsibility1", "responsibility2", ...],
    "qualifications": ["qualification1", "qualification2", ...],
    "description": "Full job description text"
}}

Extract what you can. Use reasonable defaults for missing information. Return ONLY valid JSON, no markdown."""

    try:
        response = agent.client.chat.completions.create(
            model=agent.model,
            messages=[
                {"role": "system", "content": "You are a job description parser. Extract information and return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=2000
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Extract JSON from response
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()
        
        data = json.loads(result_text)
        
        return JobDescription(
            title=data.get('title', 'Position'),
            company=data.get('company', 'Company'),
            required_skills=data.get('required_skills', []),
            preferred_skills=data.get('preferred_skills', []),
            experience_years=int(data.get('experience_years', 0)),
            responsibilities=data.get('responsibilities', []),
            qualifications=data.get('qualifications', []),
            description=data.get('description', text)
        )
    except Exception as e:
        print(f"Error parsing job description with AI: {e}")
        # Fallback to basic parsing
        return JobDescription(
            title='Position',
            company='Company',
            required_skills=[],
            preferred_skills=[],
            experience_years=0,
            responsibilities=[],
            qualifications=[],
            description=text
        )


@app.route('/')
def index():
    """Display upload form"""
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_files():
    """Handle file uploads and process resumes"""
    try:
        # Check for job description (text or file)
        job_text = None
        job_description_text = request.form.get('job_description_text', '').strip()
        
        if job_description_text:
            # Use pasted text
            job_text = job_description_text
        elif 'job_description' in request.files:
            # Use uploaded file
            job_file = request.files['job_description']
            if job_file.filename != '':
                if not allowed_file(job_file.filename):
                    return render_template('index.html', error='Job description file type not supported. Use PDF, DOCX, or TXT')
                
                job_filename = secure_filename(job_file.filename)
                job_path = os.path.join(app.config['UPLOAD_FOLDER'], job_filename)
                job_file.save(job_path)
                job_text = FileParser.parse_file(job_path)
                os.remove(job_path)
        
        if not job_text:
            return render_template('index.html', error='Please provide a job description (either paste text or upload a file)')
        
        # Check for resumes
        if 'resumes' not in request.files:
            return render_template('index.html', error='Please upload resume files')
        
        resume_files = request.files.getlist('resumes')
        
        if not resume_files or resume_files[0].filename == '':
            return render_template('index.html', error='Please select at least one resume file')
        
        for resume_file in resume_files:
            if not allowed_file(resume_file.filename):
                return render_template('index.html', error=f'Resume file type not supported: {resume_file.filename}. Use PDF, DOCX, or TXT')
        
        # Initialize agent
        agent = ResumeScreeningAgent()
        
        # Parse job description
        job_description = parse_job_description_with_ai(job_text, agent)
        
        # Save and parse resumes
        resumes = []
        for resume_file in resume_files:
            resume_filename = secure_filename(resume_file.filename)
            resume_path = os.path.join(app.config['UPLOAD_FOLDER'], resume_filename)
            resume_file.save(resume_path)
            
            resume_text = FileParser.parse_file(resume_path)
            resume = parse_resume_with_ai(resume_text, resume_filename, agent)
            resumes.append(resume)
        
        # Screen and rank resumes
        ranked_results = agent.rank_resumes(resumes, job_description)
        
        # Save to database
        results_data = [asdict(score) for score in ranked_results]
        session_id = db.save_session(job_description.title, job_description.company, results_data)
        
        # Clean up uploaded files
        for resume_file in resume_files:
            resume_filename = secure_filename(resume_file.filename)
            resume_path = os.path.join(app.config['UPLOAD_FOLDER'], resume_filename)
            if os.path.exists(resume_path):
                os.remove(resume_path)
        
        # Display results (without automatic email notifications)
        return render_template('results.html', 
                             results=ranked_results,
                             job_title=job_description.title,
                             session_id=session_id)
    
    except ValueError as e:
        return render_template('index.html', error=str(e))
    except Exception as e:
        return render_template('index.html', error=f'An error occurred: {str(e)}')


@app.route('/history')
def history():
    """Display screening history"""
    sessions = db.get_all_sessions()
    return render_template('history.html', sessions=sessions)


@app.route('/history/<int:session_id>')
def view_session(session_id):
    """View specific session results"""
    session_info, results = db.get_session_results(session_id)
    
    # Convert results to ResumeScore-like objects for template
    from resume_screening_agent import ResumeScore
    score_objects = []
    for result in results:
        score = ResumeScore(
            resume_id=result['resume_id'],
            candidate_name=result['candidate_name'],
            overall_score=result['overall_score'],
            skills_match_score=result['skills_match_score'],
            experience_score=result['experience_score'],
            education_score=result['education_score'],
            reasoning=result['reasoning'],
            strengths=result['strengths'],
            weaknesses=result['weaknesses'],
            recommendation=result['recommendation']
        )
        score_objects.append(score)
    
    return render_template('results.html',
                         results=score_objects,
                         job_title=session_info['job_title'],
                         session_id=session_id,
                         from_history=True)


@app.route('/history/hide/<int:session_id>', methods=['POST'])
def hide_session(session_id):
    """Hide a session from history"""
    db.hide_session(session_id)
    return redirect(url_for('history'))


@app.route('/history/delete/<int:session_id>', methods=['POST'])
def delete_session(session_id):
    """Delete a session permanently"""
    db.delete_session(session_id)
    return redirect(url_for('history'))


@app.route('/history/clear', methods=['POST'])
def clear_history():
    """Clear all history"""
    db.clear_all_history()
    return redirect(url_for('history'))


@app.route('/send-emails', methods=['POST'])
def send_emails():
    """Send email notifications to candidates"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        threshold = data.get('threshold', 70.0)
        job_title = data.get('job_title', 'Position')
        company_name = data.get('company_name', 'Company')
        
        if not session_id:
            return jsonify({'success': False, 'error': 'Session ID is required'}), 400
        
        # Get session results
        session_info, results = db.get_session_results(session_id)
        
        # Send email notifications
        email_notifier = EmailNotifier()
        stats = email_notifier.notify_candidates(
            results=results,
            job_title=job_title,
            company=company_name,
            threshold=threshold
        )
        
        return jsonify({'success': True, 'stats': stats})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/export/<int:session_id>/<format>')
def export_session(session_id, format):
    """Export session to PDF or Excel"""
    # Get top_n from query params
    top_n = request.args.get('top_n', type=int)
    
    session_info, results = db.get_session_results(session_id)
    
    # Sanitize job title for filename
    job_title = session_info['job_title'].replace(' ', '_').replace('/', '_').replace('\\', '_')
    # Remove any non-alphanumeric characters except underscores and hyphens
    job_title = ''.join(c for c in job_title if c.isalnum() or c in ['_', '-'])
    
    if format == 'pdf':
        buffer = export_to_pdf(session_info, results, top_n)
        filename = f"screening_results_{job_title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        response = send_file(buffer, download_name=filename, as_attachment=True, mimetype='application/pdf')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'"
        return response
    
    elif format == 'excel':
        buffer = export_to_excel(session_info, results, top_n)
        filename = f"screening_results_{job_title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response = send_file(buffer, download_name=filename, as_attachment=True, 
                           mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'"
        return response
    
    else:
        return "Invalid format", 400


if __name__ == '__main__':
    # Get port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)

# Vercel requires this for serverless functions
app = app
