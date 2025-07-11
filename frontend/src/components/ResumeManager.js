import React, { useState } from 'react';
import axios from 'axios';
import './ResumeManager.css';

const ResumeManager = () => {
    const [files, setFiles] = useState([]);
    const [uploading, setUploading] = useState(false);
    const [candidates, setCandidates] = useState([]);
    const [summary, setSummary] = useState(null);
    const [currentPage, setCurrentPage] = useState(1);
    const [itemsPerPage] = useState(10);
    const [editingCandidate, setEditingCandidate] = useState(null);
    const [showRawText, setShowRawText] = useState({});

    const handleFileChange = (e) => {
        const selectedFiles = Array.from(e.target.files);
        setFiles(selectedFiles);
    };

    const handleDrop = (e) => {
        e.preventDefault();
        const droppedFiles = Array.from(e.dataTransfer.files);
        setFiles(droppedFiles);
    };

    const handleUpload = async () => {
        if (files.length === 0) {
            alert('Please select files to upload.');
            return;
        }

        if (files.length > 100) {
            alert('Maximum 100 files allowed per upload.');
            return;
        }

        setUploading(true);
        const formData = new FormData();
        
        files.forEach(file => {
            formData.append('files', file);
        });

        try {
            const response = await axios.post('http://localhost:5001/upload-resumes', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });

            setCandidates(response.data.candidates);
            setSummary(response.data.summary);
            setCurrentPage(1);
        } catch (error) {
            console.error('Error uploading files:', error);
            alert('Failed to upload files: ' + (error.response?.data?.error || error.message));
        } finally {
            setUploading(false);
        }
    };

    const handleEdit = (candidate) => {
        setEditingCandidate({ ...candidate });
    };

    const handleSave = async () => {
        try {
            await axios.put(`http://localhost:5001/update-candidate/${editingCandidate.id}`, {
                fullName: editingCandidate.fullName,
                email: editingCandidate.email,
                contactNumber: editingCandidate.contactNumber
            });

            setCandidates(candidates.map(c => 
                c.id === editingCandidate.id ? editingCandidate : c
            ));
            setEditingCandidate(null);
        } catch (error) {
            console.error('Error updating candidate:', error);
            alert('Failed to update candidate');
        }
    };

    const handleExportCSV = async () => {
        try {
            const response = await axios.post('http://localhost:5001/export-csv', 
                { candidates }, 
                { responseType: 'blob' }
            );

            const blob = new Blob([response.data], { type: 'text/csv' });
            const url = window.URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = 'resume_parsing_report.csv';
            link.click();
            window.URL.revokeObjectURL(url);
        } catch (error) {
            console.error('Error exporting CSV:', error);
            alert('Failed to export CSV');
        }
    };

    const toggleRawText = (candidateId) => {
        setShowRawText(prev => ({
            ...prev,
            [candidateId]: !prev[candidateId]
        }));
    };

    // Pagination logic
    const indexOfLastItem = currentPage * itemsPerPage;
    const indexOfFirstItem = indexOfLastItem - itemsPerPage;
    const currentCandidates = candidates.slice(indexOfFirstItem, indexOfLastItem);
    const totalPages = Math.ceil(candidates.length / itemsPerPage);

    const paginate = (pageNumber) => setCurrentPage(pageNumber);

    return (
        <div className="resume-manager">
            <h2>Resume Batch Upload & Processing</h2>
            
            {/* Upload Section */}
            <div className="upload-section">
                <div 
                    className="file-drop-zone"
                    onDrop={handleDrop}
                    onDragOver={(e) => e.preventDefault()}
                >
                    <p>Drag & drop files here or click to select</p>
                    <p className="supported-formats">Supported: PDF, DOC, DOCX files and ZIP archives containing resumes</p>
                    <input
                        type="file"
                        multiple
                        accept=".pdf,.doc,.docx,.zip"
                        onChange={handleFileChange}
                        className="file-input"
                    />
                </div>
                
                {files.length > 0 && (
                    <div className="file-list">
                        <h4>Selected Files ({files.length}):</h4>
                        <ul>
                            {files.slice(0, 5).map((file, index) => (
                                <li key={index}>{file.name}</li>
                            ))}
                            {files.length > 5 && <li>... and {files.length - 5} more files</li>}
                        </ul>
                    </div>
                )}
                
                <button 
                    onClick={handleUpload} 
                    disabled={uploading || files.length === 0}
                    className="upload-button"
                >
                    {uploading ? 'Processing...' : 'Upload & Process Resumes'}
                </button>
            </div>

            {/* Summary Section */}
            {summary && (
                <div className="summary-section">
                    <h3>Processing Summary</h3>
                    <div className="summary-stats">
                        <div className="stat">
                            <span className="stat-number">{summary.totalResumesUploaded}</span>
                            <span className="stat-label">Total Uploaded</span>
                        </div>
                        <div className="stat success">
                            <span className="stat-number">{summary.successfullyParsed}</span>
                            <span className="stat-label">Successfully Parsed</span>
                        </div>
                        <div className="stat error">
                            <span className="stat-number">{summary.failedToParse}</span>
                            <span className="stat-label">Failed to Parse</span>
                        </div>
                        <div className="stat warning">
                            <span className="stat-number">{summary.duplicatesRemoved}</span>
                            <span className="stat-label">Duplicates Removed</span>
                        </div>
                    </div>
                    <button onClick={handleExportCSV} className="export-button">
                        Export CSV Report
                    </button>
                </div>
            )}

            {/* Candidates Table */}
            {candidates.length > 0 && (
                <div className="candidates-section">
                    <h3>Extracted Candidate Details</h3>
                    <div className="table-container">
                        <table className="candidates-table">
                            <thead>
                                <tr>
                                    <th>File Name</th>
                                    <th>Full Name</th>
                                    <th>Email</th>
                                    <th>Contact Number</th>
                                    <th>Status</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {currentCandidates.map((candidate) => (
                                    <React.Fragment key={candidate.id}>
                                        <tr className={candidate.parseStatus === 'failed' ? 'failed-row' : 'success-row'}>
                                            <td>{candidate.fileName}</td>
                                            <td>
                                                {editingCandidate?.id === candidate.id ? (
                                                    <input
                                                        value={editingCandidate.fullName || ''}
                                                        onChange={(e) => setEditingCandidate({
                                                            ...editingCandidate,
                                                            fullName: e.target.value
                                                        })}
                                                    />
                                                ) : (
                                                    candidate.fullName || 'N/A'
                                                )}
                                            </td>
                                            <td>
                                                {editingCandidate?.id === candidate.id ? (
                                                    <input
                                                        value={editingCandidate.email || ''}
                                                        onChange={(e) => setEditingCandidate({
                                                            ...editingCandidate,
                                                            email: e.target.value
                                                        })}
                                                    />
                                                ) : (
                                                    candidate.email || 'N/A'
                                                )}
                                            </td>
                                            <td>
                                                {editingCandidate?.id === candidate.id ? (
                                                    <input
                                                        value={editingCandidate.contactNumber || ''}
                                                        onChange={(e) => setEditingCandidate({
                                                            ...editingCandidate,
                                                            contactNumber: e.target.value
                                                        })}
                                                    />
                                                ) : (
                                                    candidate.contactNumber || 'N/A'
                                                )}
                                            </td>
                                            <td>
                                                <span className={`status ${candidate.parseStatus}`}>
                                                    {candidate.parseStatus}
                                                </span>
                                                {candidate.failureReason && (
                                                    <div className="failure-reason">
                                                        {candidate.failureReason}
                                                    </div>
                                                )}
                                            </td>
                                            <td>
                                                {editingCandidate?.id === candidate.id ? (
                                                    <div className="edit-actions">
                                                        <button onClick={handleSave} className="save-btn">Save</button>
                                                        <button onClick={() => setEditingCandidate(null)} className="cancel-btn">Cancel</button>
                                                    </div>
                                                ) : (
                                                    <div className="row-actions">
                                                        <button onClick={() => handleEdit(candidate)} className="edit-btn">Edit</button>
                                                        <button 
                                                            onClick={() => toggleRawText(candidate.id)} 
                                                            className="view-btn"
                                                        >
                                                            {showRawText[candidate.id] ? 'Hide' : 'View'} Raw Text
                                                        </button>
                                                    </div>
                                                )}
                                            </td>
                                        </tr>
                                        {showRawText[candidate.id] && candidate.rawText && (
                                            <tr>
                                                <td colSpan="6">
                                                    <div className="raw-text-container">
                                                        <strong>Raw Extracted Text:</strong>
                                                        <pre className="raw-text">{candidate.rawText}</pre>
                                                    </div>
                                                </td>
                                            </tr>
                                        )}
                                    </React.Fragment>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    {/* Pagination */}
                    {totalPages > 1 && (
                        <div className="pagination">
                            <button 
                                onClick={() => paginate(currentPage - 1)} 
                                disabled={currentPage === 1}
                            >
                                Previous
                            </button>
                            
                            {[...Array(totalPages)].map((_, index) => (
                                <button
                                    key={index + 1}
                                    onClick={() => paginate(index + 1)}
                                    className={currentPage === index + 1 ? 'active' : ''}
                                >
                                    {index + 1}
                                </button>
                            ))}
                            
                            <button 
                                onClick={() => paginate(currentPage + 1)} 
                                disabled={currentPage === totalPages}
                            >
                                Next
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default ResumeManager;
