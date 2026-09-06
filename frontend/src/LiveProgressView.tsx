import React, { useState, useEffect } from 'react';

interface InventoryItem {
  object_id: string;
  name: string;
  object_type: string;
  migration_status?: 'pending' | 'processing' | 'success' | 'error';
  dest_id?: string;
  error_message?: string;
}

interface LiveProgressViewProps {
  jobId: string;
}

const API_BASE_URL = import.meta.env.PROD ? '/api/v1' : 'http://localhost:8000/api/v1';

export const LiveProgressView: React.FC<LiveProgressViewProps> = ({ jobId }) => {
  const [inventory, setInventory] = useState<Record<string, InventoryItem>>({});
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting');

  useEffect(() => {
    let sse: EventSource;

    const connect = () => {
      setConnectionStatus('connecting');
      sse = new EventSource(`${API_BASE_URL}/jobs/${jobId}/inventory/stream`);

      sse.onopen = () => {
        setConnectionStatus('connected');
      };

      sse.onmessage = (event) => {
        try {
          const updatedDocs: InventoryItem[] = JSON.parse(event.data);
          setInventory((prev) => {
            const next = { ...prev };
            updatedDocs.forEach((doc) => {
              next[doc.object_id] = { ...next[doc.object_id], ...doc };
            });
            return next;
          });
        } catch (err) {
          console.error('Failed to parse SSE data', err);
        }
      };

      sse.onerror = () => {
        setConnectionStatus('disconnected');
        sse.close();
        // Simple reconnect logic
        setTimeout(connect, 3000);
      };
    };

    connect();

    return () => {
      if (sse) {
        sse.close();
      }
    };
  }, [jobId]);

  // Convert the dictionary back to an array for rendering
  const items = Object.values(inventory);
  
  // Optional: Sort items so processing/errors float to top, or sort by name
  items.sort((a, b) => {
      // Sort priority: processing > error > pending > success
      const score = (status?: string) => {
          if (status === 'processing') return 0;
          if (status === 'error') return 1;
          if (status === 'pending' || !status) return 2;
          return 3; // success
      };
      
      const scoreA = score(a.migration_status);
      const scoreB = score(b.migration_status);
      
      if (scoreA !== scoreB) return scoreA - scoreB;
      return a.object_type.localeCompare(b.object_type);
  });

  return (
    <div className="live-progress-container">
      <h3>Live Migration Progress</h3>
      
      <div className={`connection-badge ${connectionStatus}`}>
        {connectionStatus === 'connecting' && '🔌 Connecting to stream...'}
        {connectionStatus === 'connected' && '🟢 Live Updates Active'}
        {connectionStatus === 'disconnected' && '🔴 Stream disconnected. Retrying...'}
      </div>

      <div className="table-wrapper">
        <table className="progress-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Name</th>
              <th>Status</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={4} className="empty-state">Waiting for items to begin processing...</td>
              </tr>
            ) : (
              items.map((item) => (
                <tr key={item.object_id} className={`status-row ${item.migration_status || 'pending'}`}>
                  <td className="type-cell">{item.object_type}</td>
                  <td className="name-cell">{item.name}</td>
                  <td className="status-cell">
                    {item.migration_status === 'processing' && <span className="badge badge-processing">⚙️ Processing</span>}
                    {item.migration_status === 'success' && <span className="badge badge-success">✅ Success</span>}
                    {item.migration_status === 'error' && <span className="badge badge-error">❌ Error</span>}
                    {(!item.migration_status || item.migration_status === 'pending') && <span className="badge badge-pending">⏳ Pending</span>}
                  </td>
                  <td className="details-cell">
                    {item.dest_id && <span className="dest-id">ID: {item.dest_id}</span>}
                    {item.error_message && <span className="error-text">{item.error_message}</span>}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
