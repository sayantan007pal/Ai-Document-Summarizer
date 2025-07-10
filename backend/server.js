const express = require('express');
const cors = require('cors');
const fileUpload = require('express-fileupload');
const pdfParse = require('pdf-parse');
const mammoth = require('mammoth');
const AdmZip = require('adm-zip');
const path = require('path');
const fs = require('fs');
const { v4: uuidv4 } = require('uuid');

const app = express();

app.use(cors());
app.use(fileUpload());
app.use(express.json());

app.get('/Picture', (req, res) => {
    res.send('This is the Picture route!');
});


app.post('/upload', async (req, res) => {
    try {
        if (!req.files || !req.files.file) {
            return res.status(400).send('No file uploaded');
        }

        const file = req.files.file;
        const dataBuffer = file.data;
        const parsedData = await pdfParse(dataBuffer);

        res.json({
            text: parsedData.text,
            info: parsedData.info,
        });
    } catch (error) {
        console.error('Error parsing PDF:', error);
        res.status(500).send('Error parsing PDF');
    }
});

// Resume batch upload endpoint
app.post('/upload-resumes', async (req, res) => {
    try {
        if (!req.files) {
            return res.status(400).json({ error: 'No files uploaded' });
        }

        let filesToProcess = [];
        const uploadedFiles = Array.isArray(req.files.files) ? req.files.files : [req.files.files];

        // Process each uploaded file
        for (let file of uploadedFiles) {
            if (file.name.endsWith('.zip')) {
                // Handle zip file
                try {
                    const zip = new AdmZip(file.data);
                    const zipEntries = zip.getEntries();
                    
                    zipEntries.forEach(entry => {
                        if (!entry.isDirectory && isValidFileFormat(entry.entryName)) {
                            filesToProcess.push({
                                name: entry.entryName,
                                data: entry.getData()
                            });
                        }
                    });
                } catch (zipError) {
                    console.error('Error processing zip file:', zipError);
                }
            } else if (isValidFileFormat(file.name)) {
                // Handle individual file
                filesToProcess.push({
                    name: file.name,
                    data: file.data
                });
            }
        }

        // Check file limit
        if (filesToProcess.length > 100) {
            return res.status(400).json({ 
                error: 'Too many files. Maximum 100 resumes per upload.',
                fileCount: filesToProcess.length 
            });
        }

        if (filesToProcess.length === 0) {
            return res.status(400).json({ 
                error: 'No valid resume files found. Supported formats: .pdf, .doc, .docx' 
            });
        }

        // Process resumes sequentially
        const parsedCandidates = [];
        let processedCount = 0;

        for (let file of filesToProcess) {
            try {
                const candidateData = await parseResumeContent(file.data, file.name);
                parsedCandidates.push(candidateData);
                processedCount++;
                
                // Add small delay to ensure stable load
                await new Promise(resolve => setTimeout(resolve, 100));
            } catch (error) {
                console.error(`Error processing ${file.name}:`, error);
                parsedCandidates.push({
                    fileName: file.name,
                    parseStatus: 'failed',
                    failureReason: `Processing error: ${error.message}`,
                    uploadTimestamp: new Date().toISOString(),
                    id: uuidv4()
                });
            }
        }

        // Remove duplicates based on email
        const uniqueCandidates = removeDuplicatesByEmail(parsedCandidates);
        
        const successfullyParsed = uniqueCandidates.filter(c => c.parseStatus === 'success');
        const failedToParse = uniqueCandidates.filter(c => c.parseStatus === 'failed');

        const response = {
            totalUploaded: filesToProcess.length,
            totalProcessed: uniqueCandidates.length,
            successfullyParsed: successfullyParsed.length,
            failedToParse: failedToParse.length,
            candidates: uniqueCandidates,
            summary: {
                totalResumesUploaded: filesToProcess.length,
                successfullyParsed: successfullyParsed.length,
                failedToParse: failedToParse.length,
                duplicatesRemoved: parsedCandidates.length - uniqueCandidates.length
            }
        };

        res.json(response);
    } catch (error) {
        console.error('Error in resume upload:', error);
        res.status(500).json({ error: 'Internal server error during resume processing' });
    }
});

// CSV export endpoint
app.post('/export-csv', (req, res) => {
    try {
        const { candidates } = req.body;
        
        if (!candidates || !Array.isArray(candidates)) {
            return res.status(400).json({ error: 'Invalid candidates data' });
        }

        // Create CSV content
        const csvHeaders = ['File Name', 'Full Name', 'Email', 'Contact Number', 'Parse Status', 'Failure Reason', 'Upload Timestamp'];
        const csvRows = candidates.map(candidate => [
            candidate.fileName || '',
            candidate.fullName || '',
            candidate.email || '',
            candidate.contactNumber || '',
            candidate.parseStatus || '',
            candidate.failureReason || '',
            candidate.uploadTimestamp || ''
        ]);

        const csvContent = [csvHeaders, ...csvRows]
            .map(row => row.map(field => `"${field}"`).join(','))
            .join('\n');

        res.setHeader('Content-Type', 'text/csv');
        res.setHeader('Content-Disposition', 'attachment; filename=resume_parsing_report.csv');
        res.send(csvContent);
    } catch (error) {
        console.error('Error generating CSV:', error);
        res.status(500).json({ error: 'Error generating CSV report' });
    }
});

// Update candidate endpoint
app.put('/update-candidate/:id', (req, res) => {
    try {
        const { id } = req.params;
        const { fullName, email, contactNumber } = req.body;
        
        // In a real application, you would update the database
        // For this POC, we'll just return the updated data
        res.json({
            id,
            fullName,
            email,
            contactNumber,
            status: 'updated'
        });
    } catch (error) {
        console.error('Error updating candidate:', error);
        res.status(500).json({ error: 'Error updating candidate' });
    }
});

// Utility functions for resume parsing
function extractEmail(text) {
    const emailRegex = /\b[A-Za-z0-9._%+-]+@[A-ZaZ0-9.-]+\.[A-Z|a-z]{2,}\b/g;
    const emails = text.match(emailRegex);
    return emails ? emails[0] : null;
}

function extractPhone(text) {
    // Various phone number patterns
    const phoneRegex = /(?:\+?1[-.\s]?)?(?:\(?[0-9]{3}\)?[-.\s]?)?[0-9]{3}[-.\s]?[0-9]{4}|\b\d{10}\b/g;
    const phones = text.match(phoneRegex);
    return phones ? phones[0] : null;
}

function extractName(text) {
    // Simple name extraction - looks for capitalized words at the beginning
    const lines = text.split('\n').filter(line => line.trim().length > 0);
    for (let line of lines.slice(0, 5)) { // Check first 5 lines
        const words = line.trim().split(/\s+/);
        if (words.length >= 2 && words.length <= 4) {
            // Check if words are likely to be names (capitalized, no numbers/special chars)
            const isLikelyName = words.every(word => 
                /^[A-Z][a-z]+$/.test(word) && word.length > 1
            );
            if (isLikelyName) {
                return words.join(' ');
            }
        }
    }
    return null;
}

async function parseResumeContent(fileBuffer, fileName) {
    try {
        let text = '';
        const extension = path.extname(fileName).toLowerCase();
        
        if (extension === '.pdf') {
            const parsedData = await pdfParse(fileBuffer);
            text = parsedData.text || '';
        } else if (extension === '.docx') {
            const result = await mammoth.extractRawText({ buffer: fileBuffer });
            text = result.value || '';
        } else if (extension === '.doc') {
            // For .doc files, we'll try to extract as text (limited support)
            text = fileBuffer.toString('utf8').replace(/[^\x20-\x7E\n\r\t]/g, ' ');
        } else {
            throw new Error('Unsupported file format');
        }
        
        const candidateDetails = {
            fileName: fileName,
            fullName: extractName(text),
            email: extractEmail(text),
            contactNumber: extractPhone(text),
            rawText: text,
            parseStatus: 'success',
            uploadTimestamp: new Date().toISOString(),
            id: uuidv4()
        };

        // Check if all mandatory fields are extracted
        if (!candidateDetails.fullName || !candidateDetails.email || !candidateDetails.contactNumber) {
            candidateDetails.parseStatus = 'failed';
            candidateDetails.failureReason = 'Missing mandatory fields: ' + 
                [
                    !candidateDetails.fullName ? 'Full Name' : null,
                    !candidateDetails.email ? 'Email' : null,
                    !candidateDetails.contactNumber ? 'Contact Number' : null
                ].filter(Boolean).join(', ');
        }

        return candidateDetails;
    } catch (error) {
        return {
            fileName: fileName,
            parseStatus: 'failed',
            failureReason: `Parse error: ${error.message}`,
            uploadTimestamp: new Date().toISOString(),
            id: uuidv4()
        };
    }
}

function isValidFileFormat(fileName) {
    const supportedFormats = ['.pdf', '.doc', '.docx'];
    const extension = path.extname(fileName).toLowerCase();
    return supportedFormats.includes(extension);
}

function removeDuplicatesByEmail(candidates) {
    const emailMap = new Map();
    
    candidates.forEach(candidate => {
        if (candidate.email && candidate.parseStatus === 'success') {
            const existing = emailMap.get(candidate.email);
            if (!existing || new Date(candidate.uploadTimestamp) > new Date(existing.uploadTimestamp)) {
                emailMap.set(candidate.email, candidate);
            }
        } else if (!candidate.email) {
            // Keep failed candidates without email
            emailMap.set(candidate.id, candidate);
        }
    });
    
    return Array.from(emailMap.values());
}

const PORT = 5001;
app.listen(PORT, () => {
    console.log(`Server running on http://localhost:${PORT}`);
});
