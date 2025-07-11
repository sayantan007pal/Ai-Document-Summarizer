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
import time
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
        
        # Filter out invalid emails
        valid_emails = []
        for email in emails:
            if self.is_valid_personal_email(email):
                valid_emails.append(email)
        
        return list(set(valid_emails))  # Remove duplicates
    
    def is_valid_personal_email(self, email):
        """Check if email looks like a personal email, not system/technical email"""
        if not email or len(email) < 5:
            return False
            
        email_lower = email.lower()
        
        # Exclude system/technical emails
        invalid_patterns = [
            'mongodb.net', 'localhost', '127.0.0.1', 'test.com', 'example.com',
            'noreply', 'no-reply', 'admin@', 'system@', 'root@', 'info@',
            'support@', 'help@', 'contact@', 'sales@', 'marketing@'
        ]
        
        for pattern in invalid_patterns:
            if pattern in email_lower:
                return False
        
        # Check for random/generated email patterns
        local_part = email.split('@')[0]
        
        # Too many random characters or numbers
        if len(re.findall(r'[0-9]', local_part)) > len(local_part) * 0.6:
            return False
            
        # Too long random strings (likely generated)
        if len(local_part) > 20 and not any(char.isalpha() for char in local_part[:10]):
            return False
            
        return True
    
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
            'artificial', 'intelligence', 'business', 'product', 'project',
            'warehouse', 'picker', 'cashier', 'customer', 'service', 'representative',
            'sales', 'increasing', 'qualified', 'global', 'markets', 'foodspotting',
            'call', 'logging', 'implementation', 'documentation', 'request',
            'metadata', 'context', 'information', 'details', 'current', 'prompt',
            'flow', 'visual', 'studio', 'code', 'module', 'globally', 'system',
            'command', 'line', 'args'
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
        
        # Resume section headers to exclude
        section_headers = {
            'profile', 'summary', 'objective', 'experience', 'education', 'skills',
            'achievements', 'projects', 'certifications', 'awards', 'references',
            'interests', 'hobbies', 'languages', 'career', 'professional', 'personal',
            'work', 'employment', 'academic', 'qualifications', 'training', 'courses'
        }
        
        # Check if any word is a job title, technical term, location, company, or section header
        for word in words:
            word_lower = word.lower()
            if (word_lower in job_titles or word_lower in tech_terms or 
                word_lower in locations or word_lower in companies or 
                word_lower in section_headers):
                return False
        
        # Check for common section header patterns
        name_lower = name.lower()
        section_patterns = ['profile summary', 'career objective', 'work experience', 
                           'professional experience', 'personal details', 'contact information']
        if any(pattern in name_lower for pattern in section_patterns):
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
        
        # If names come from the enhanced extraction, they're already sorted by priority
        # So we prioritize the first valid name, but still apply some filtering
        
        # Filter out names that are clearly not person names
        filtered_names = [name for name in names if self.is_likely_person_name(name)]
        
        if not filtered_names:
            # If no names pass the filter, return the first name from the original list
            # as the enhanced extraction already prioritized them
            return names[0] if names else None
        
        # Return the first filtered name (highest priority from enhanced extraction)
        return filtered_names[0]
    
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
    
    def select_best_email(self, emails):
        """Select the most likely email from a list of candidates"""
        if not emails:
            return None
        
        # Score emails based on various criteria
        scored_emails = []
        for email in emails:
            score = 0
            email_lower = email.lower()
            
            # Prefer personal emails over generic ones
            if any(domain in email_lower for domain in ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com']):
                score += 10
            
            # Prefer emails with actual names rather than random characters
            local_part = email.split('@')[0]
            if any(char.isalpha() for char in local_part):
                score += 5
            
            # Penalize emails that look system-generated
            if any(pattern in email_lower for pattern in ['test', 'example', 'noreply', 'admin']):
                score -= 20
            
            scored_emails.append((score, email))
        
        # Return the highest scoring email
        scored_emails.sort(reverse=True)
        return scored_emails[0][1] if scored_emails else None
    
    def extract_emails_aggressive(self, text):
        """More aggressive email extraction for hard-to-parse documents"""
        emails = []
        
        # Multiple patterns for different email formats
        patterns = [
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Standard
            r'[A-Za-z0-9._%+-]+\s*@\s*[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}',  # With spaces
            r'[A-Za-z0-9._%+-]+\s*\[\s*at\s*\]\s*[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}',  # [at] format
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            emails.extend(matches)
        
        # Clean up emails
        cleaned_emails = []
        for email in emails:
            # Remove spaces and normalize
            cleaned = re.sub(r'\s+', '', email)
            cleaned = cleaned.replace('[at]', '@').replace('(at)', '@')
            
            if self.is_valid_personal_email(cleaned):
                cleaned_emails.append(cleaned)
        
        return list(set(cleaned_emails))
    
    def extract_names_aggressive(self, text):
        """More aggressive name extraction for hard-to-parse documents"""
        names = []
        
        # Look for name patterns near keywords
        keywords = ['name', 'candidate', 'applicant', 'resume of', 'cv of', 'profile']
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in keywords):
                # Check this line and surrounding lines
                search_lines = lines[max(0, i-2):min(len(lines), i+3)]
                for search_line in search_lines:
                    # Extract potential names
                    words = search_line.strip().split()
                    if 2 <= len(words) <= 4:
                        potential_name = ' '.join(words)
                        if self.is_likely_person_name(potential_name):
                            names.append(potential_name)
        
        # Look for capitalized sequences at document start
        first_lines = '\n'.join(lines[:10])
        name_patterns = [
            r'\b([A-Z][a-z]{2,15}\s+[A-Z][a-z]{2,15})\b',  # First Last
            r'\b([A-Z][a-z]{2,15}\s+[A-Z][a-z]{2,15}\s+[A-Z][a-z]{2,15})\b',  # First Middle Last
        ]
        
        for pattern in name_patterns:
            matches = re.findall(pattern, first_lines)
            for match in matches:
                if self.is_likely_person_name(match):
                    names.append(match)
        
        # Filter out common resume section headers
        filtered_names = []
        section_headers = ['profile summary', 'work experience', 'professional experience', 
                          'education', 'skills', 'objective', 'summary', 'achievements',
                          'career objective', 'personal details', 'references']
        
        for name in names:
            name_lower = name.lower()
            if not any(header in name_lower for header in section_headers):
                filtered_names.append(name)
        
        return list(set(filtered_names))
    
    def extract_phones_aggressive(self, text):
        """More aggressive phone extraction for hard-to-parse documents"""
        phones = []
        
        # More flexible patterns
        patterns = [
            r'(\+?\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})',  # Various formats
            r'(\d{10})',  # Just 10 digits
            r'(phone[:\s]*[\+\d\-\.\s\(\)]+)',  # After "phone:"
            r'(mobile[:\s]*[\+\d\-\.\s\(\)]+)',  # After "mobile:"
            r'(tel[:\s]*[\+\d\-\.\s\(\)]+)',  # After "tel:"
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                # Clean and validate
                cleaned = re.sub(r'[^\d+]', '', match)
                if cleaned and len(cleaned) >= 10:
                    phones.append(match.strip())
        
        return list(set(phones))
    
    def validate_extracted_name(self, name):
        """Validate if the extracted name is actually a person's name"""
        if not name:
            return False
        
        # Check against our existing validation
        if not self.is_likely_person_name(name):
            return False
        
        # Additional validation
        words = name.split()
        
        # Must have at least 2 words
        if len(words) < 2:
            return False
        
        # Each word should be reasonable length
        for word in words:
            if len(word) < 2 or len(word) > 20:
                return False
        
        # Should contain only alphabetic characters
        if not all(word.isalpha() for word in words):
            return False
        
        # Should be properly capitalized
        if not all(word[0].isupper() for word in words):
            return False
        
        return True
    
    def validate_extracted_email(self, email):
        """Validate if the extracted email is actually valid"""
        if not email:
            return False
        
        # Basic format check
        if '@' not in email or '.' not in email:
            return False
        
        # Must have valid structure
        try:
            local, domain = email.rsplit('@', 1)
            if not local or not domain:
                return False
            
            # Domain must have at least one dot
            if '.' not in domain:
                return False
            
            # Local part should be reasonable
            if len(local) < 2 or len(local) > 64:
                return False
            
            # Domain should be reasonable
            if len(domain) < 4 or len(domain) > 255:
                return False
            
        except ValueError:
            return False
        
        # Use our existing validation
        return self.is_valid_personal_email(email)
    
    def validate_extracted_phone(self, phone):
        """Validate if the extracted phone is actually a phone number"""
        if not phone:
            return False
        
        # Extract only digits
        digits_only = re.sub(r'[^\d]', '', phone)
        
        # Must have reasonable number of digits
        if len(digits_only) < 10 or len(digits_only) > 15:
            return False
        
        # Should not be all same digits
        if len(set(digits_only)) <= 2:
            return False
        
        # Should not be sequential (like 1234567890)
        if digits_only in ['1234567890', '0123456789', '9876543210']:
            return False
        
        # For Indian numbers, first digit after country code should be 6-9
        if phone.startswith('+91') and len(digits_only) >= 11:
            first_mobile_digit = digits_only[2]  # After +91
            if first_mobile_digit not in '6789':
                return False
        elif len(digits_only) == 10:
            first_digit = digits_only[0]
            if first_digit not in '6789':
                return False
        
        return True

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
    
    def extract_document_text(self, file_path):
        """Extract plain text from document (fallback method)"""
        try:
            result = self.converter.convert(file_path)
            
            # Extract plain text
            if hasattr(result, 'document'):
                text = result.document.export_to_markdown()
            elif hasattr(result, 'text'):
                text = result.text
            elif hasattr(result, 'content'):
                text = result.content
            else:
                text = str(result)
            
            return text
        except Exception as e:
            return ""
    
    def extract_text_with_formatting(self, file_path):
        """Extract text with formatting information like font sizes from document"""
        try:
            result = self.converter.convert(file_path)
            
            # Extract plain text
            if hasattr(result, 'document'):
                text = result.document.export_to_markdown()
            elif hasattr(result, 'text'):
                text = result.text
            elif hasattr(result, 'content'):
                text = result.content
            else:
                text = str(result)
            
            # Extract formatting information from docling result
            formatted_text = {}
            
            # Try to get structured content with formatting if available
            if hasattr(result, 'document') and result.document and hasattr(result.document, 'body') and result.document.body:
                formatted_text = self._extract_formatting_from_docling_body(result.document.body.children, text)
            
            return text, formatted_text
            
        except Exception as e:
            # Fallback to plain text extraction
            text = self.parse_document(file_path)
            return text, {}
    
    def _extract_formatting_from_docling_body(self, elements, full_text):
        """Extract formatting information from docling body elements"""
        formatting_info = {}
        line_number = 0
        
        try:
            for element in elements:
                if hasattr(element, 'text') and element.text:
                    # Track line position
                    line_number += element.text.count('\n') + 1
                    
                    # Extract font size if available
                    font_size = None
                    if hasattr(element, 'style') and element.style:
                        if hasattr(element.style, 'font_size'):
                            font_size = element.style.font_size
                        elif hasattr(element.style, 'fontSize'):
                            font_size = element.style.fontSize
                    
                    # Store formatting info
                    if element.text.strip():
                        formatting_info[element.text.strip()] = {
                            'line_number': line_number,
                            'font_size': font_size,
                            'position': 'early' if line_number <= 10 else 'later'
                        }
                        
                # Recursively process nested elements
                if hasattr(element, 'children') and element.children:
                    nested_info = self._extract_formatting_from_docling_body(element.children, full_text)
                    formatting_info.update(nested_info)
                    
        except Exception as e:
            # If formatting extraction fails, return empty dict
            pass
            
        return formatting_info
    
    def extract_candidate_info(self, file_path, filename):
        """Extract all candidate information from a resume file"""
        try:
            # Parse document to get text and formatting information
            text, formatted_text = self.extract_text_with_formatting(file_path)
            
            # Extract information with multiple attempts, prioritizing font size and early position
            names = self.extract_names_with_font_priority(text, formatted_text)
            emails = self.extract_email_addresses(text)
            phones = self.extract_phone_numbers(text)
            
            # Try harder to find missing email and phone information
            if not emails:
                emails = self.extract_emails_aggressive(text)
            
            if not phones:
                phones = self.extract_phones_aggressive(text)
            
            # Select best candidates for each field
            full_name = self.select_best_name(names)
            email = self.select_best_email(emails)
            contact_number = self.select_best_phone(phones)
            
            # Validate the extracted information
            valid_name = self.validate_extracted_name(full_name)
            valid_email = self.validate_extracted_email(email)
            valid_phone = self.validate_extracted_phone(contact_number)
            
            candidate_details = {
                'fileName': filename,
                'fullName': full_name if valid_name else None,
                'email': email if valid_email else None,
                'contactNumber': contact_number if valid_phone else None,
                'allNames': names,
                'allEmails': emails,
                'allPhones': phones,
                'rawText': text,
                'parseStatus': 'success',
                'uploadTimestamp': datetime.now().isoformat(),
                'id': str(uuid.uuid4())
            }
            
            # Check if all mandatory fields are extracted AND valid
            missing_fields = []
            if not valid_name or not full_name:
                missing_fields.append('Valid Full Name')
            if not valid_email or not email:
                missing_fields.append('Valid Email')
            if not valid_phone or not contact_number:
                missing_fields.append('Valid Contact Number')
            
            if missing_fields:
                candidate_details['parseStatus'] = 'failed'
                candidate_details['failureReason'] = f'Missing or invalid mandatory fields: {", ".join(missing_fields)}'
                # Set invalid fields to None
                if not valid_name:
                    candidate_details['fullName'] = None
                if not valid_email:
                    candidate_details['email'] = None
                if not valid_phone:
                    candidate_details['contactNumber'] = None
            
            return candidate_details
            
        except Exception as e:
            return {
                'fileName': filename,
                'parseStatus': 'failed',
                'failureReason': f'Parse error: {str(e)}',
                'uploadTimestamp': datetime.now().isoformat(),
                'id': str(uuid.uuid4())
            }

    def extract_names_with_font_priority(self, text, formatted_text=None):
        """Extract names with font size and position prioritization"""
        names = []
        
        # Start with regular name extraction
        regular_names = self.extract_names(text)
        names.extend(regular_names)
        
        # Add aggressive extraction if needed
        if not names:
            aggressive_names = self.extract_names_aggressive(text)
            names.extend(aggressive_names)
        
        # Add fallback extraction
        if not names:
            fallback_names = self.extract_names_fallback(text)
            names.extend(fallback_names)
        
        # Enhance names with formatting information
        if formatted_text:
            enhanced_names = []
            for name in names:
                name_info = {
                    'name': name,
                    'font_size': None,
                    'line_number': None,
                    'is_early': False,
                    'score': 0
                }
                
                # Look for formatting information
                for text_chunk, format_info in formatted_text.items():
                    if name.lower() in text_chunk.lower() or any(part.lower() in text_chunk.lower() for part in name.split()):
                        name_info['font_size'] = format_info.get('font_size')
                        name_info['line_number'] = format_info.get('line_number', 999)
                        name_info['is_early'] = format_info.get('position') == 'early'
                        break
                
                # Calculate priority score
                name_info['score'] = self._calculate_name_score(name_info, text)
                enhanced_names.append(name_info)
            
            # Sort by score (highest first) and return name strings
            enhanced_names.sort(key=lambda x: x['score'], reverse=True)
            return [info['name'] for info in enhanced_names]
        
        return names
    
    def _calculate_name_score(self, name_info, full_text):
        """Calculate priority score for a name based on various factors"""
        score = 0
        name = name_info['name']
        
        # Base score for having a name
        score += 10
        
        # Font size bonus (larger fonts get higher scores)
        if name_info['font_size']:
            try:
                font_size = float(name_info['font_size'])
                score += font_size * 2  # Larger fonts get significant bonus
            except (ValueError, TypeError):
                pass
        
        # Early position bonus (first 10 lines)
        if name_info['is_early'] or (name_info['line_number'] and name_info['line_number'] <= 10):
            score += 50
        
        # Position-based scoring
        if name_info['line_number']:
            if name_info['line_number'] <= 3:
                score += 30  # Very early (likely header)
            elif name_info['line_number'] <= 5:
                score += 20  # Early
            elif name_info['line_number'] <= 10:
                score += 10  # Still early
        
        # Name quality scoring
        parts = name.split()
        if len(parts) >= 2:
            score += 20  # Bonus for full names
        if len(parts) >= 3:
            score += 10  # Bonus for middle names
        
        # Penalize common words that aren't names
        common_words = ['resume', 'cv', 'curriculum', 'profile', 'summary', 'objective']
        if any(word.lower() in name.lower() for word in common_words):
            score -= 30
        
        # Bonus for proper capitalization
        if all(part[0].isupper() for part in parts if part):
            score += 15
        
        # Check if name appears multiple times (likely important)
        name_occurrences = full_text.lower().count(name.lower())
        if name_occurrences > 1:
            score += min(name_occurrences * 5, 20)  # Cap the bonus
        
        return score
    
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
