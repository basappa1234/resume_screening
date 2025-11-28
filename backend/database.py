"""
Database module for storing screening history
"""

import sqlite3
import json
from datetime import datetime
from typing import List, Dict
import os


class ScreeningDatabase:
    """Manage screening history in SQLite database"""
    
    def __init__(self, db_path='screening_history.db'):
        """Initialize database connection"""
        # Use absolute path for database to ensure it works in different environments
        if db_path == 'screening_history.db':
            import os
            # For Vercel, we need to use /tmp directory for writable files
            if os.environ.get('VERCEL'):
                db_path = '/tmp/screening_history.db'
            else:
                db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screening_history.db')
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Create database tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_title TEXT NOT NULL,
                company TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_hidden BOOLEAN DEFAULT 0,
                total_candidates INTEGER
            )
        ''')
        
        # Create results table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                resume_id TEXT,
                candidate_name TEXT NOT NULL,
                overall_score REAL,
                skills_match_score REAL,
                experience_score REAL,
                education_score REAL,
                reasoning TEXT,
                strengths TEXT,
                weaknesses TEXT,
                recommendation TEXT,
                rank INTEGER,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_session(self, job_title: str, company: str, results: List[Dict]) -> int:
        """
        Save a screening session and its results
        
        Returns:
            session_id: ID of the created session
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Insert session
        cursor.execute(
            'INSERT INTO sessions (job_title, company, total_candidates) VALUES (?, ?, ?)',
            (job_title, company, len(results))
        )
        session_id = cursor.lastrowid
        
        # Insert results
        for rank, result in enumerate(results, 1):
            cursor.execute('''
                INSERT INTO results (
                    session_id, resume_id, candidate_name, overall_score,
                    skills_match_score, experience_score, education_score,
                    reasoning, strengths, weaknesses, recommendation, rank
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id,
                result.get('resume_id'),
                result.get('candidate_name'),
                result.get('overall_score'),
                result.get('skills_match_score'),
                result.get('experience_score'),
                result.get('education_score'),
                result.get('reasoning'),
                json.dumps(result.get('strengths', [])),
                json.dumps(result.get('weaknesses', [])),
                result.get('recommendation'),
                rank
            ))
        
        conn.commit()
        conn.close()
        
        return session_id
    
    def get_all_sessions(self, include_hidden=False):
        """Get all screening sessions"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if include_hidden:
            cursor.execute('SELECT * FROM sessions ORDER BY timestamp DESC')
        else:
            cursor.execute('SELECT * FROM sessions WHERE is_hidden = 0 ORDER BY timestamp DESC')
        
        sessions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return sessions
    
    def get_session_results(self, session_id: int):
        """Get all results for a specific session"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get session info
        cursor.execute('SELECT * FROM sessions WHERE id = ?', (session_id,))
        session = dict(cursor.fetchone())
        
        # Get results
        cursor.execute('SELECT * FROM results WHERE session_id = ? ORDER BY rank', (session_id,))
        results = []
        for row in cursor.fetchall():
            result = dict(row)
            result['strengths'] = json.loads(result['strengths'])
            result['weaknesses'] = json.loads(result['weaknesses'])
            results.append(result)
        
        conn.close()
        
        return session, results
    
    def hide_session(self, session_id: int):
        """Hide a session from history"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('UPDATE sessions SET is_hidden = 1 WHERE id = ?', (session_id,))
        conn.commit()
        conn.close()
    
    def unhide_session(self, session_id: int):
        """Unhide a session"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('UPDATE sessions SET is_hidden = 0 WHERE id = ?', (session_id,))
        conn.commit()
        conn.close()
    
    def delete_session(self, session_id: int):
        """Permanently delete a session and its results"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM results WHERE session_id = ?', (session_id,))
        cursor.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
        conn.commit()
        conn.close()
    
    def clear_all_history(self):
        """Clear all history (delete all sessions and results)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM results')
        cursor.execute('DELETE FROM sessions')
        conn.commit()
        conn.close()
    
    def get_top_candidates(self, session_id: int, top_n: int = 5):
        """Get top N candidates from a session"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM results 
            WHERE session_id = ? 
            ORDER BY rank 
            LIMIT ?
        ''', (session_id, top_n))
        
        results = []
        for row in cursor.fetchall():
            result = dict(row)
            result['strengths'] = json.loads(result['strengths'])
            result['weaknesses'] = json.loads(result['weaknesses'])
            results.append(result)
        
        conn.close()
        return results
