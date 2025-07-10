import React, { useState } from 'react';
import FileUpload from './components/FileUpload';
import DocumentChat from './components/DocumentChat';
import ResumeManager from './components/ResumeManager';

const App = () => {
    const [documentText, setDocumentText] = useState('');
    const [activeTab, setActiveTab] = useState('document');

    const renderContent = () => {
        switch (activeTab) {
            case 'document':
                return (
                    <>
                        <FileUpload onTextParsed={setDocumentText} />
                        {documentText && <DocumentChat documentText={documentText} />}
                    </>
                );
            case 'resume':
                return <ResumeManager />;
            default:
                return null;
        }
    };

    return (
        <div style={{ fontFamily: 'Arial, sans-serif', padding: '20px' }}>
            <h1>AI-Powered Document Summarizer & Resume Parser</h1>
            
            {/* Tab Navigation */}
            <div style={{ 
                display: 'flex', 
                gap: '10px', 
                marginBottom: '30px',
                borderBottom: '2px solid #dee2e6',
                paddingBottom: '10px'
            }}>
                <button
                    onClick={() => setActiveTab('document')}
                    style={{
                        padding: '10px 20px',
                        border: 'none',
                        borderRadius: '5px 5px 0 0',
                        background: activeTab === 'document' ? '#007bff' : '#f8f9fa',
                        color: activeTab === 'document' ? 'white' : '#495057',
                        cursor: 'pointer',
                        fontWeight: '600'
                    }}
                >
                    Document Summarizer
                </button>
                <button
                    onClick={() => setActiveTab('resume')}
                    style={{
                        padding: '10px 20px',
                        border: 'none',
                        borderRadius: '5px 5px 0 0',
                        background: activeTab === 'resume' ? '#007bff' : '#f8f9fa',
                        color: activeTab === 'resume' ? 'white' : '#495057',
                        cursor: 'pointer',
                        fontWeight: '600'
                    }}
                >
                    Resume Parser
                </button>
            </div>

            {renderContent()}
        </div>
    );
};

export default App;
