# Python Backend for Resume Parser

This is a Python Flask-based backend that replaces the Node.js backend with enhanced document parsing capabilities using Docling.

## Features

- **Advanced Document Parsing**: Uses Docling library for superior PDF, DOC, and DOCX parsing
- **Enhanced Information Extraction**: Improved name, email, and phone number extraction using NLTK and regex
- **International Phone Support**: Extracts phone numbers in various international formats including +91, etc.
- **ZIP File Support**: Extracts and processes multiple resumes from ZIP files
- **Batch Processing**: Handles up to 100 resumes per upload
- **Duplicate Detection**: Email-based duplicate removal with timestamp priority
- **CSV Export**: Complete processing reports with all extracted information

## Installation

1. Navigate to the python-backend directory:
```bash
cd python-backend
```

2. Run the setup script:
```bash
chmod +x setup.sh
./setup.sh
```

3. Activate the virtual environment and start the server:
```bash
source venv/bin/activate
python app.py
```

## Manual Installation

If the setup script doesn't work, install manually:

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the server
python app.py
```

## API Endpoints

### Single Document Upload
- **POST** `/upload`
- Upload and parse a single document

### Batch Resume Upload
- **POST** `/upload-resumes`
- Upload multiple resumes (individual files or ZIP)
- Returns parsed candidate information

### Export CSV
- **POST** `/export-csv`
- Export processing results to CSV format

### Update Candidate
- **PUT** `/update-candidate/<id>`
- Update candidate information

### Health Check
- **GET** `/health`
- Check if the server is running

## Enhanced Information Extraction

### Phone Numbers
- Supports international formats: `+91 98765 43210`
- US formats: `(555) 123-4567`, `555-123-4567`
- International with parentheses: `+1 (555) 123-4567`
- 10+ digit numbers with various separators

### Email Addresses
- Standard email regex with full domain validation
- Removes duplicates automatically

### Names
- Uses NLTK Named Entity Recognition (NER)
- Fallback to pattern-based extraction
- Looks for capitalized word sequences in document headers

## Supported File Formats

- PDF (.pdf)
- Microsoft Word (.docx)
- Microsoft Word Legacy (.doc)
- ZIP files containing the above formats

## Configuration

- **Port**: 5001 (to avoid conflicts with Node.js backend)
- **Max File Size**: 50MB
- **Max Files per Upload**: 100
- **Upload Directory**: `temp_uploads/` (created automatically)

## Dependencies

- **Flask**: Web framework
- **Flask-CORS**: Cross-origin resource sharing
- **docling**: Advanced document parsing
- **nltk**: Natural language processing for name extraction
- **python-magic**: File type detection

## Advantages over Node.js Backend

1. **Better Document Parsing**: Docling provides superior text extraction
2. **Enhanced NLP**: NLTK for better name recognition
3. **International Phone Support**: Comprehensive phone number patterns
4. **Robust Error Handling**: Better exception management
5. **Cleaner Code Structure**: Object-oriented design with ResumeParser class

## Usage Notes

- The server automatically downloads required NLTK data on first run
- All temporary files are cleaned up automatically
- Supports concurrent processing with proper resource management
- Maintains compatibility with the existing frontend interface
