import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

// In production, we use relative paths to hit the NGINX proxy.
// In local development, we hit the FastAPI server directly on port 8000.
const API_BASE_URL = import.meta.env.PROD ? '/api/v1' : 'http://localhost:8000/api/v1';

function App() {
  const [sourceApiKey, setSourceApiKey] = useState('');
  const [destApiKey, setDestApiKey] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    
    const isPollingStatus = jobStatus === 'PENDING' || jobStatus === 'RUNNING' || jobStatus === 'EXECUTING';

    if (jobId && isPollingStatus) {
      interval = setInterval(async () => {
        try {
          const response = await axios.get(`${API_BASE_URL}/jobs/${jobId}/status`);
          setJobStatus(response.data.status);
        } catch (err: any) {
          setError(err.message || 'Error polling job status');
        }
      }, 2000);
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [jobId, jobStatus]);

  const startDiscovery = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setJobId(null);
    setJobStatus(null);
    
    try {
      const response = await axios.post(`${API_BASE_URL}/jobs`, {
        source_api_key: sourceApiKey,
        dest_api_key: destApiKey
      });
      setJobId(response.data.job_id);
      setJobStatus(response.data.status);
    } catch (err: any) {
      setError(err.message || 'Error starting discovery job');
    }
  };

  const startMigrationExecution = async () => {
    if (!jobId) return;
    setError(null);
    try {
      const response = await axios.post(`${API_BASE_URL}/jobs/${jobId}/execute`);
      setJobStatus(response.data.status);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Error starting execution');
    }
  };

  const downloadReport = async () => {
    if (!jobId) return;
    
    try {
      const response = await axios.get(`${API_BASE_URL}/jobs/${jobId}/report`, {
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `migration_report_${jobId}.md`);
      document.body.appendChild(link);
      link.click();
      if(link.parentNode) link.parentNode.removeChild(link);
    } catch (err: any) {
       setError(err.message || 'Error downloading report');
    }
  };

  return (
    <div className="App">
      <h1>Monday.com Migration Portal</h1>
      <p>Discover and assess your monday.com migration scope.</p>

      {!jobId && (
        <form onSubmit={startDiscovery} className="discovery-form">
          <div className="form-group">
            <label htmlFor="sourceKey">Source API Key (Read-Only required):</label>
            <input 
              id="sourceKey"
              type="password" 
              value={sourceApiKey} 
              onChange={(e) => setSourceApiKey(e.target.value)} 
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="destKey">Destination API Key (Write required, for later):</label>
            <input 
              id="destKey"
              type="password" 
              value={destApiKey} 
              onChange={(e) => setDestApiKey(e.target.value)} 
            />
          </div>
          <button type="submit" disabled={!sourceApiKey}>Start Discovery Job</button>
        </form>
      )}

      {error && <div className="error-message">Error: {error}</div>}

      {jobId && (
        <div className="job-status">
          <h2>Job Tracking</h2>
          <p>Job ID: {jobId}</p>
          <p>Status: <strong>{jobStatus}</strong></p>
          
          {(jobStatus === 'PENDING' || jobStatus === 'RUNNING') && (
            <div className="spinner">Discovery in progress...</div>
          )}

          {jobStatus === 'EXECUTING' && (
            <div className="spinner">Migration execution in progress... check GCP logs for real-time Cloud Tasks telemetry.</div>
          )}

          {jobStatus === 'COMPLETED' && (
            <div>
              <p className="success">Discovery completed successfully!</p>
              <div className="action-buttons">
                <button onClick={downloadReport} className="download-btn">
                  Download Discovery Report
                </button>
                <button onClick={startMigrationExecution} className="execute-btn" style={{backgroundColor: '#e63946', color: 'white', marginLeft: '10px'}}>
                  Confirm & Execute Migration
                </button>
              </div>
              <button onClick={() => setJobId(null)} className="reset-btn" style={{marginTop: '20px'}}>
                Start New Job
              </button>
            </div>
          )}

          {jobStatus === 'MIGRATION_COMPLETED' && (
            <div>
              <p className="success">Migration completed successfully!</p>
              <button onClick={() => setJobId(null)} className="reset-btn">
                Start New Job
              </button>
            </div>
          )}
          
          {jobStatus === 'FAILED' && (
             <button onClick={() => setJobId(null)} className="reset-btn">
                Try Again
             </button>
          )}
        </div>
      )}
    </div>
  );
}

export default App;
