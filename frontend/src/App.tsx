import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

// In production, we use relative paths to hit the NGINX proxy.
// In local development, we hit the FastAPI server directly on port 8000.
const API_BASE_URL = import.meta.env.PROD ? '/api/v1' : 'http://localhost:8000/api/v1';

const CapabilityMatrix = () => (
  <div className="capability-matrix">
    <h3>Migration Capability Matrix</h3>
    <p>What can and cannot be migrated automatically:</p>
    <div className="matrix-section">
      <h4>Fully Migratable</h4>
      <ul>
        <li>Workspaces & Boards (Core structure)</li>
        <li>Groups & Items</li>
        <li>Native Columns (Text, numbers, status, date, people, dropdown, checkbox, timeline)</li>
        <li>Subitems</li>
        <li>Docs & Articles</li>
      </ul>
    </div>
    <div className="matrix-section">
      <h4>Partially Migratable (w/ Caveats)</h4>
      <ul>
        <li>Updates / Comments (Author/Timestamp replaced with API user/now)</li>
        <li>Files / Attachments (Heavy on API quotas)</li>
        <li>Formula Columns (String copied, but may break if dependencies missing)</li>
      </ul>
    </div>
    <div className="matrix-section">
      <h4>Manual Only</h4>
      <ul>
        <li>Automations / Integration Recipes</li>
        <li>Dashboards (Cross-board widgets)</li>
        <li>Permissions & Custom Views</li>
        <li>User Identity (Exact profile recreation)</li>
      </ul>
    </div>
  </div>
);

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
        } catch (err) {
          if (axios.isAxiosError(err)) {
            setError(err.response?.data?.detail || err.message || 'Error occurred');
          } else if (err instanceof Error) {
            setError(err.message);
          } else {
            setError('An unknown error occurred');
          }
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
        source_api_key: sourceApiKey
      });
      setJobId(response.data.job_id);
      setJobStatus(response.data.status);
    } catch (err) {
      if (axios.isAxiosError(err)) {
        setError(err.response?.data?.detail || err.message || 'Error starting discovery job');
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Error starting discovery job');
      }
    }
  };

  const startMigrationExecution = async () => {
    if (!jobId) return;
    if (!destApiKey) {
      setError('Destination API Key is required to execute the migration.');
      return;
    }
    setError(null);
    try {
      const response = await axios.post(`${API_BASE_URL}/jobs/${jobId}/execute`, {
        dest_api_key: destApiKey
      });
      setJobStatus(response.data.status);
    } catch (err) {
      if (axios.isAxiosError(err)) {
        setError(err.response?.data?.detail || err.message || 'Error starting execution');
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Error starting execution');
      }
    }
  };

  const cancelJob = async () => {
    if (!jobId) return;
    try {
      const response = await axios.post(`${API_BASE_URL}/jobs/${jobId}/cancel`);
      setJobStatus(response.data.status);
    } catch (err) {
      if (axios.isAxiosError(err)) {
        setError(err.response?.data?.detail || err.message || 'Error cancelling job');
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Error cancelling job');
      }
    }
  };

  const deleteJob = async () => {
    if (!jobId) return;
    try {
      await axios.delete(`${API_BASE_URL}/jobs/${jobId}`);
      setJobId(null);
      setJobStatus(null);
      setSourceApiKey('');
      setDestApiKey('');
    } catch (err) {
      if (axios.isAxiosError(err)) {
        setError(err.response?.data?.detail || err.message || 'Error deleting job data');
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Error deleting job data');
      }
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
    } catch (err) {
       if (axios.isAxiosError(err)) {
         setError(err.response?.data?.detail || err.message || 'Error downloading report');
       } else if (err instanceof Error) {
         setError(err.message);
       } else {
         setError('Error downloading report');
       }
    }
  };

  return (
    <div className="App">
      <h1>Monday.com Migration Portal</h1>
      <p>Discover and assess your monday.com migration scope.</p>

      {!jobId && (
        <form onSubmit={startDiscovery} className="discovery-form">
          <div className="form-group">
            <label htmlFor="sourceKey">Source API Key (read-only required):</label>
            <input 
              id="sourceKey"
              type="password" 
              value={sourceApiKey} 
              onChange={(e) => setSourceApiKey(e.target.value)} 
              required
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
          
          {(jobStatus === 'PENDING' || jobStatus === 'RUNNING' || jobStatus === 'EXECUTING') && (
            <div className="active-job-actions">
               {jobStatus === 'EXECUTING' ? (
                 <div className="spinner">Migration execution in progress... check GCP logs for real-time Cloud Tasks telemetry.</div>
               ) : (
                 <div className="spinner">Discovery in progress...</div>
               )}
               <button onClick={cancelJob} className="danger-btn">Cancel Job</button>
            </div>
          )}

          {jobStatus === 'COMPLETED' && (
            <div className="execution-panel">
              <p className="success">Discovery completed successfully!</p>
              
              <button onClick={downloadReport} className="download-btn">
                Download Discovery Report
              </button>

              <div className="execution-form">
                <hr />
                <h3>Ready to Migrate?</h3>
                <div className="form-group">
                  <label htmlFor="destKey">Destination API Key (Write required):</label>
                  <input 
                    id="destKey"
                    type="password" 
                    value={destApiKey} 
                    onChange={(e) => setDestApiKey(e.target.value)} 
                    placeholder="Enter your destination API key"
                  />
                </div>
                <button 
                  onClick={startMigrationExecution} 
                  className="execute-btn" 
                  disabled={!destApiKey}
                >
                  Confirm & Execute Migration
                </button>
              </div>
            </div>
          )}

          {jobStatus === 'MIGRATION_COMPLETED' && (
            <div>
              <p className="success">Migration completed successfully!</p>
            </div>
          )}

          {(jobStatus === 'FAILED' || jobStatus === 'CANCELLED' || jobStatus === 'COMPLETED' || jobStatus === 'MIGRATION_COMPLETED') && (
             <div className="terminal-actions">
               <button onClick={deleteJob} className="danger-btn">Delete All Job Data</button>
             </div>
          )}
        </div>
      )}

      {(jobStatus === 'RUNNING' || jobStatus === 'COMPLETED') && (
        <CapabilityMatrix />
      )}
    </div>
  );
}

export default App;
