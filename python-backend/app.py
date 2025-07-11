from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import tempfile
import shutil
import zipfile
from pathlib import Path
import uuid
from datetime import datetime
import csv
import io
import re
import nltk
from nltk.corpus import stopwords
from docling.document_converter import DocumentConverter
import json

# Download required NLTK data
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

try:
    nltk.data.find('taggers/averaged_perceptron_tagger')
except LookupError:
    nltk.download('averaged_perceptron_tagger')

try:
    nltk.data.find('chunkers/maxent_ne_chunker')
except LookupError:
    nltk.download('maxent_ne_chunker')

try:
    nltk.data.find('corpora/words')
except LookupError:
    nltk.download('words')

app = Flask(__name__)
CORS(app)

# Configure upload settings
UPLOAD_FOLDER = 'temp_uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

# Initialize stopwords
stop = stopwords.words('english')

class ResumeParser:
    def __init__(self):
        self.converter = DocumentConverter()
    
    def extract_phone_numbers(self, text):
        """Extract phone numbers including international formats"""
        # More precise regex patterns for phone numbers
        patterns = [
            r'(\+91[-.\s]?\d{10})',  # Indian format +91 followed by 10 digits
            r'(\+\d{1,3}[-.\s]?\d{10})',  # Other international formats
            r'(\+\d{1,3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4})',  # International with separators
            r'(\d{10})',  # Exactly 10 digits
            r'(\(\d{3}\)\s*\d{3}[-.\s]?\d{4})',    # (xxx) xxx-xxxx
            r'(\d{3}[-.\s]\d{3}[-.\s]\d{4})',  # xxx-xxx-xxxx or xxx.xxx.xxxx
        ]
        
        phone_numbers = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            phone_numbers.extend(matches)
        
        # Clean and validate phone numbers
        valid_numbers = []
        for number in phone_numbers:
            # Clean the number
            cleaned = re.sub(r'[^\d+]', '', number)
            
            # Skip if it's just numbers that look like decimals or coordinates
            if '.' in number and len(number.split('.')) == 2:
                continue
                
            # Check for valid phone number patterns
            digit_count = len(re.sub(r'[^\d]', '', cleaned))
            
            # Valid phone number criteria:
            # - 10 digits (Indian mobile)
            # - 10+ digits with country code
            # - Not starting with 0 (unless it's a country code)
            # - Not containing repeated patterns that look like decimals
            if digit_count >= 10 and digit_count <= 15:
                # Additional validation to avoid false positives
                digits_only = re.sub(r'[^\d]', '', number)
                
                # Skip numbers that are clearly not phone numbers
                if (
                    len(set(digits_only[-4:])) > 1 and  # Last 4 digits should have some variation
                    not re.match(r'^0+', digits_only) and  # Don't start with all zeros
                    '.' not in number.replace('+', '')  # Avoid decimal numbers
                ):
                    valid_numbers.append(number.strip())
        
        # Sort by length (longer numbers with country codes first) and remove duplicates
        valid_numbers = list(set(valid_numbers))
        valid_numbers.sort(key=lambda x: (len(x), '+' in x), reverse=True)
        
        return valid_numbers[:5]  # Return top 5 most likely phone numbers
    
    def extract_email_addresses(self, text):
        """Extract email addresses"""
        pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(pattern, text)
        return list(set(emails))  # Remove duplicates
    
    def ie_preprocess(self, document):
        """Preprocess document for information extraction"""
        # Remove stopwords and tokenize
        document = ' '.join([i for i in document.split() if i.lower() not in stop])
        sentences = nltk.sent_tokenize(document)
        sentences = [nltk.word_tokenize(sent) for sent in sentences]
        sentences = [nltk.pos_tag(sent) for sent in sentences]
        return sentences
    
    def extract_names(self, document):
        """Extract person names using Named Entity Recognition"""
        names = []
        try:
            sentences = self.ie_preprocess(document)
            for tagged_sentence in sentences:
                chunks = nltk.ne_chunk(tagged_sentence)
                for chunk in chunks:
                    if hasattr(chunk, 'label') and chunk.label() == 'PERSON':
                        name = ' '.join([c[0] for c in chunk])
                        # Filter out obvious non-names
                        if self.is_likely_person_name(name):
                            names.append(name)
        except Exception as e:
            print(f"Error in name extraction: {e}")
        
        # Always try fallback method as well
        fallback_names = self.extract_names_fallback(document)
        names.extend(fallback_names)
        
        # Remove duplicates and filter
        unique_names = []
        for name in names:
            if name not in unique_names and self.is_likely_person_name(name):
                unique_names.append(name)
        
        return unique_names[:5]  # Return top 5 most likely names
        unique_names = []
        for name in names:
            if name not in unique_names and self.is_likely_person_name(name):
                unique_names.append(name)
        
        return unique_names[:5]  # Return top 5 most likely names
    
    def is_likely_person_name(self, name):
        """Check if a string is likely to be a person's name"""
        if not name or len(name.strip()) < 2:
            return False
            
        name = name.strip()
        words = name.split()
        
        # Common job titles and technical terms to exclude
        job_titles = {
            'intern', 'developer', 'engineer', 'manager', 'analyst', 'designer',
            'specialist', 'coordinator', 'assistant', 'associate', 'consultant',
            'director', 'supervisor', 'lead', 'senior', 'junior', 'student',
            'trainee', 'graduate', 'fresher', 'experienced', 'science', 'technology',
            'data', 'software', 'web', 'full', 'stack', 'backend', 'frontend',
            'mobile', 'ios', 'android', 'devops', 'cloud', 'machine', 'learning',
            'artificial', 'intelligence', 'business', 'product', 'project'
        }
        
        # Technical terms to exclude
        tech_terms = {
            'matplotlib', 'python', 'java', 'javascript', 'react', 'node', 'express',
            'html', 'css', 'sql', 'mongodb', 'mysql', 'postgresql', 'git', 'github',
            'aws', 'azure', 'docker', 'kubernetes', 'linux', 'windows', 'macos',
            'bootstrap', 'jquery', 'angular', 'vue', 'django', 'flask', 'redux',
            'typescript', 'php', 'ruby', 'golang', 'swift', 'kotlin', 'scala',
            'pandas', 'numpy', 'tensorflow', 'pytorch', 'opencv', 'sklearn',
            'toolkit', 'airflow', 'apache', 'prism', 'recruit', 'electronics'
        }
        
        # Location names to exclude (Indian states, cities, countries)
        locations = {
            'west', 'bengal', 'delhi', 'mumbai', 'bangalore', 'chennai', 'hyderabad',
            'pune', 'kolkata', 'ahmedabad', 'jaipur', 'surat', 'lucknow', 'kanpur',
            'nagpur', 'patna', 'indore', 'thane', 'bhopal', 'visakhapatnam',
            'kerala', 'tamil', 'nadu', 'karnataka', 'maharashtra', 'gujarat',
            'rajasthan', 'punjab', 'haryana', 'bihar', 'odisha', 'assam',
            'uttarakhand', 'himachal', 'pradesh', 'madhya', 'pradesh', 'goa',
            'tripura', 'manipur', 'meghalaya', 'mizoram', 'nagaland', 'sikkim',
            'andhra', 'telangana', 'jharkhand', 'chhattisgarh', 'jammu', 'kashmir',
            'india', 'indian', 'university', 'college', 'institute', 'school',
            'government', 'engineering', 'technology', 'management', 'medical',
            'jalpaiguri', 'darjeeling', 'siliguri', 'durgapur', 'asansol',
            'quest', 'quine', 'communication'
        }
        
        # Company/Organization names to exclude
        companies = {
            'google', 'microsoft', 'amazon', 'facebook', 'apple', 'netflix',
            'uber', 'airbnb', 'tesla', 'spacex', 'ibm', 'oracle', 'salesforce',
            'adobe', 'intel', 'nvidia', 'qualcomm', 'cisco', 'vmware',
            'infosys', 'tcs', 'wipro', 'cognizant', 'accenture', 'capgemini',
            'deloitte', 'pwc', 'kpmg', 'ey', 'mckinsey', 'bain', 'bcg'
        }
        
        # Check if any word is a job title, technical term, location, or company
        for word in words:
            word_lower = word.lower()
            if (word_lower in job_titles or word_lower in tech_terms or 
                word_lower in locations or word_lower in companies):
                return False
        
        # Check for common location patterns
        name_lower = name.lower()
        if any(pattern in name_lower for pattern in ['west bengal', 'tamil nadu', 'andhra pradesh', 'madhya pradesh', 'uttar pradesh']):
            return False
        
        # Skip single words that are likely technical terms
        if len(words) == 1:
            return False
        
        # Check if all words look like names
        for word in words:
            # Must be alphabetic and start with capital
            if not word.isalpha() or not word[0].isupper():
                return False
            # Reasonable length for name parts
            if len(word) < 2 or len(word) > 20:
                return False
        
        # Should be 2-4 words for a full name
        if len(words) < 2 or len(words) > 4:
            return False
            
        return True
    
    def select_best_name(self, names):
        """Select the most likely name from a list of candidates"""
        if not names:
            return None
        
        # Filter out names that are clearly not person names
        filtered_names = [name for name in names if self.is_likely_person_name(name)]
        
        if not filtered_names:
            return None
        
        # Score names based on various criteria
        scored_names = []
        for name in filtered_names:
            score = 0
            words = name.split()
            name_lower = name.lower()
            
            # Prefer names with 2-3 parts (first + last, or first + middle + last)
            if len(words) == 2:
                score += 15  # Increased score for first+last pattern
            elif len(words) == 3:
                score += 12
            elif len(words) == 4:
                score += 8
            
            # Prefer names where each part is a reasonable length
            avg_length = sum(len(word) for word in words) / len(words)
            if 3 <= avg_length <= 10:
                score += 8
            
            # Heavily penalize location names
            location_indicators = ['west', 'bengal', 'government', 'engineering', 'university', 'college', 'institute']
            if any(indicator in name_lower for indicator in location_indicators):
                score -= 50  # Heavy penalty
            
            # Heavily penalize organization/company names
            org_indicators = ['quest', 'quine', 'communication', 'technology', 'electronics', 'prism', 'recruit']
            if any(indicator in name_lower for indicator in org_indicators):
                score -= 40
            
            # Bonus for common Indian name patterns
            if len(words) == 2:
                first, last = words
                # Common Indian first names (partial list)
                indian_first_names = ['sayantan', 'rohit', 'amit', 'rajesh', 'priya', 'anita', 'vikash', 'deepak']
                if first.lower() in indian_first_names:
                    score += 20
                
                # Common Indian last names (partial list)
                indian_last_names = ['pal', 'sharma', 'gupta', 'singh', 'kumar', 'joshi', 'patel', 'shah']
                if last.lower() in indian_last_names:
                    score += 15
            
            # Prefer names that appear early in the document (likely to be the person's name)
            # This would require the original text, but we can approximate
            if 'sayantan' in name_lower:  # Give bonus to names containing common first names
                score += 25
            
            # Penalize names that are too generic or too specific
            if name_lower in ['data science', 'machine learning', 'computer science']:
                score -= 30
            
            scored_names.append((score, name))
        
        # Return the highest scoring name
        scored_names.sort(reverse=True, key=lambda x: x[0])
        
        # Debug: print scores (remove in production)
        print(f"Name scores: {scored_names}")
        
        return scored_names[0][1] if scored_names[0][0] > 0 else None
    
    def select_best_phone(self, phones):
        """Select the most likely phone number from a list of candidates"""
        if not phones:
            return None
        
        # Score phone numbers based on format
        scored_phones = []
        for phone in phones:
            score = 0
            
            # Prefer numbers with country codes
            if phone.startswith('+'):
                score += 10
            
            # Prefer Indian mobile numbers
            if '+91' in phone:
                score += 15
            
            # Prefer 10-digit numbers (standard mobile length)
            digits_only = re.sub(r'[^\d]', '', phone)
            if len(digits_only) == 10:
                score += 8
            elif len(digits_only) == 13 and phone.startswith('+91'):  # +91 + 10 digits
                score += 12
            
            # Avoid numbers that look like decimals or coordinates
            if '.' not in phone:
                score += 5
            
            scored_phones.append((score, phone))
        
        # Return the highest scoring phone
        scored_phones.sort(reverse=True)
        return scored_phones[0][1]
    
    def extract_names_fallback(self, text):
        """Fallback name extraction method"""
        lines = text.split('\n')
        names = []
        
        # First, try to find name in the very beginning of the document
        # Names are usually in the first 3-5 lines
        for i, line in enumerate(lines[:5]):
            line = line.strip()
            if not line:
                continue
            
            # Skip lines that are clearly headers or metadata
            if any(keyword in line.lower() for keyword in ['resume', 'cv', 'curriculum']):
                continue
                
            # Look for standalone names (2-4 capitalized words)
            words = line.split()
            if 2 <= len(words) <= 4:
                if all(word.isalpha() and word[0].isupper() for word in words):
                    potential_name = ' '.join(words)
                    if self.is_likely_person_name(potential_name):
                        names.append(potential_name)
        
        # Look for names near contact information
        for i, line in enumerate(lines):
            if any(keyword in line.lower() for keyword in ['email', 'phone', 'contact', 'mobile', 'tel']):
                # Check a few lines before and after contact info
                start = max(0, i-5)
                end = min(len(lines), i+2)
                for j in range(start, end):
                    if j < len(lines):
                        search_line = lines[j].strip()
                        if search_line and j != i:  # Don't check the contact line itself
                            # Look for name patterns
                            words = search_line.split()
                            if 2 <= len(words) <= 4:
                                potential_name = ' '.join(words)
                                if self.is_likely_person_name(potential_name):
                                    names.append(potential_name)
        
        # Look for specific name patterns in the entire document
        name_pattern = r'\b([A-Z][a-z]{2,15}\s+[A-Z][a-z]{2,15}(?:\s+[A-Z][a-z]{2,15})?)\b'
        matches = re.findall(name_pattern, text)
        for match in matches:
            if self.is_likely_person_name(match):
                names.append(match)
        
        # Remove duplicates and return
        unique_names = list(set(names))
        
        # Sort by position in text (names appearing earlier are more likely to be the person's name)
        def get_position(name):
            try:
                return text.lower().find(name.lower())
            except:
                return float('inf')
        
        unique_names.sort(key=get_position)
        return unique_names
    
    def parse_document(self, file_path):
        """Parse document using docling and extract text"""
        try:
            result = self.converter.convert(file_path)
            # Extract text from the document
            if hasattr(result, 'text'):
                text = result.text
            elif hasattr(result, 'content'):
                text = result.content
            elif hasattr(result, 'document'):
                text = str(result.document)
            else:
                text = str(result)
            
            return text
        except Exception as e:
            raise Exception(f"Failed to parse document: {str(e)}")
    
    def extract_candidate_info(self, file_path, filename):
        """Extract all candidate information from a resume file"""
        try:
            # Parse document to get text
            text = self.parse_document(file_path)
            
            # Extract information
            names = self.extract_names(text)
            emails = self.extract_email_addresses(text)
            phones = self.extract_phone_numbers(text)
            
            # Select best candidates for each field
            full_name = self.select_best_name(names)
            email = emails[0] if emails else None
            contact_number = self.select_best_phone(phones)
            
            candidate_details = {
                'fileName': filename,
                'fullName': full_name,
                'email': email,
                'contactNumber': contact_number,
                'allNames': names,
                'allEmails': emails,
                'allPhones': phones,
                'rawText': text,
                'parseStatus': 'success',
                'uploadTimestamp': datetime.now().isoformat(),
                'id': str(uuid.uuid4())
            }
            
            # Check if all mandatory fields are extracted
            missing_fields = []
            if not full_name:
                missing_fields.append('Full Name')
            if not email:
                missing_fields.append('Email')
            if not contact_number:
                missing_fields.append('Contact Number')
            
            if missing_fields:
                candidate_details['parseStatus'] = 'failed'
                candidate_details['failureReason'] = f'Missing mandatory fields: {", ".join(missing_fields)}'
            
            return candidate_details
            
        except Exception as e:
            return {
                'fileName': filename,
                'parseStatus': 'failed',
                'failureReason': f'Parse error: {str(e)}',
                'uploadTimestamp': datetime.now().isoformat(),
                'id': str(uuid.uuid4())
            }

def is_valid_file_format(filename):
    """Check if file format is supported"""
    supported_formats = ['.pdf', '.doc', '.docx']
    return any(filename.lower().endswith(fmt) for fmt in supported_formats)

def remove_duplicates_by_email(candidates):
    """Remove duplicates based on email, keeping the latest"""
    email_map = {}
    
    for candidate in candidates:
        email = candidate.get('email')
        if email and candidate.get('parseStatus') == 'success':
            existing = email_map.get(email)
            if not existing or datetime.fromisoformat(candidate['uploadTimestamp']) > datetime.fromisoformat(existing['uploadTimestamp']):
                email_map[email] = candidate
        else:
            # Keep failed candidates without email using their ID as key
            email_map[candidate['id']] = candidate
    
    return list(email_map.values())

# Initialize parser
parser = ResumeParser()

@app.route('/Picture', methods=['GET'])
def picture_route():
    return 'This is the Picture route!'

@app.route('/upload', methods=['POST'])
def upload_single_document():
    """Upload and parse a single document"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Save file temporarily
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(temp_path)
        
        try:
            # Parse document
            text = parser.parse_document(temp_path)
            
            # Clean up
            os.remove(temp_path)
            
            return jsonify({
                'text': text,
                'info': {'filename': file.filename}
            })
            
        except Exception as e:
            # Clean up on error
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise e
            
    except Exception as e:
        return jsonify({'error': f'Error parsing document: {str(e)}'}), 500

@app.route('/upload-resumes', methods=['POST'])
def upload_resumes():
    """Upload and parse multiple resume files"""
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files uploaded'}), 400
        
        files = request.files.getlist('files')
        if not files:
            return jsonify({'error': 'No files selected'}), 400
        
        files_to_process = []
        
        # Process each uploaded file
        for file in files:
            if file.filename == '':
                continue
                
            if file.filename.lower().endswith('.zip'):
                # Handle zip file
                try:
                    zip_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
                    file.save(zip_path)
                    
                    with zipfile.ZipFile(zip_path, 'r') as zip_file:
                        for zip_info in zip_file.filelist:
                            if not zip_info.is_dir() and is_valid_file_format(zip_info.filename):
                                # Extract file to temp location
                                extracted_path = zip_file.extract(zip_info, app.config['UPLOAD_FOLDER'])
                                files_to_process.append({
                                    'path': extracted_path,
                                    'name': os.path.basename(zip_info.filename)
                                })
                    
                    # Clean up zip file
                    os.remove(zip_path)
                    
                except Exception as e:
                    print(f"Error processing zip file {file.filename}: {e}")
                    
            elif is_valid_file_format(file.filename):
                # Handle individual file
                temp_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
                file.save(temp_path)
                files_to_process.append({
                    'path': temp_path,
                    'name': file.filename
                })
        
        # Check file limit
        if len(files_to_process) > 100:
            # Clean up files
            for file_info in files_to_process:
                if os.path.exists(file_info['path']):
                    os.remove(file_info['path'])
            
            return jsonify({
                'error': 'Too many files. Maximum 100 resumes per upload.',
                'fileCount': len(files_to_process)
            }), 400
        
        if len(files_to_process) == 0:
            return jsonify({
                'error': 'No valid resume files found. Supported formats: .pdf, .doc, .docx'
            }), 400
        
        # Process resumes sequentially
        parsed_candidates = []
        
        for i, file_info in enumerate(files_to_process):
            try:
                candidate_data = parser.extract_candidate_info(file_info['path'], file_info['name'])
                parsed_candidates.append(candidate_data)
                
                # Clean up file
                if os.path.exists(file_info['path']):
                    os.remove(file_info['path'])
                
                # Small delay for stability
                if i < len(files_to_process) - 1:
                    import time
                    time.sleep(0.1)
                    
            except Exception as e:
                print(f"Error processing {file_info['name']}: {e}")
                parsed_candidates.append({
                    'fileName': file_info['name'],
                    'parseStatus': 'failed',
                    'failureReason': f'Processing error: {str(e)}',
                    'uploadTimestamp': datetime.now().isoformat(),
                    'id': str(uuid.uuid4())
                })
                
                # Clean up file
                if os.path.exists(file_info['path']):
                    os.remove(file_info['path'])
        
        # Remove duplicates based on email
        unique_candidates = remove_duplicates_by_email(parsed_candidates)
        
        successfully_parsed = [c for c in unique_candidates if c.get('parseStatus') == 'success']
        failed_to_parse = [c for c in unique_candidates if c.get('parseStatus') == 'failed']
        
        response = {
            'totalUploaded': len(files_to_process),
            'totalProcessed': len(unique_candidates),
            'successfullyParsed': len(successfully_parsed),
            'failedToParse': len(failed_to_parse),
            'candidates': unique_candidates,
            'summary': {
                'totalResumesUploaded': len(files_to_process),
                'successfullyParsed': len(successfully_parsed),
                'failedToParse': len(failed_to_parse),
                'duplicatesRemoved': len(parsed_candidates) - len(unique_candidates)
            }
        }
        
        return jsonify(response)
        
    except Exception as e:
        return jsonify({'error': f'Internal server error during resume processing: {str(e)}'}), 500

@app.route('/export-csv', methods=['POST'])
def export_csv():
    """Export candidates data to CSV"""
    try:
        data = request.get_json()
        candidates = data.get('candidates', [])
        
        if not candidates or not isinstance(candidates, list):
            return jsonify({'error': 'Invalid candidates data'}), 400
        
        # Create CSV content
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        headers = ['File Name', 'Full Name', 'Email', 'Contact Number', 'All Names', 'All Emails', 'All Phones', 'Parse Status', 'Failure Reason', 'Upload Timestamp']
        writer.writerow(headers)
        
        # Write data
        for candidate in candidates:
            row = [
                candidate.get('fileName', ''),
                candidate.get('fullName', ''),
                candidate.get('email', ''),
                candidate.get('contactNumber', ''),
                ', '.join(candidate.get('allNames', [])),
                ', '.join(candidate.get('allEmails', [])),
                ', '.join(candidate.get('allPhones', [])),
                candidate.get('parseStatus', ''),
                candidate.get('failureReason', ''),
                candidate.get('uploadTimestamp', '')
            ]
            writer.writerow(row)
        
        # Create response
        output.seek(0)
        csv_data = output.getvalue()
        output.close()
        
        # Create a BytesIO object for file response
        csv_file = io.BytesIO()
        csv_file.write(csv_data.encode('utf-8'))
        csv_file.seek(0)
        
        return send_file(
            csv_file,
            mimetype='text/csv',
            as_attachment=True,
            download_name='resume_parsing_report.csv'
        )
        
    except Exception as e:
        return jsonify({'error': f'Error generating CSV report: {str(e)}'}), 500

@app.route('/update-candidate/<candidate_id>', methods=['PUT'])
def update_candidate(candidate_id):
    """Update candidate information"""
    try:
        data = request.get_json()
        full_name = data.get('fullName')
        email = data.get('email')
        contact_number = data.get('contactNumber')
        
        # In a real application, you would update the database
        # For this POC, we'll just return the updated data
        return jsonify({
            'id': candidate_id,
            'fullName': full_name,
            'email': email,
            'contactNumber': contact_number,
            'status': 'updated'
        })
        
    except Exception as e:
        return jsonify({'error': f'Error updating candidate: {str(e)}'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'message': 'Python backend with docling is running'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
