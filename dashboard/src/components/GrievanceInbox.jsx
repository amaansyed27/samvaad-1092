
import { useState, useEffect } from 'react';
import { CheckCircle, Clock, Search, MapPin } from 'lucide-react';

export default function GrievanceInbox() {
  const [grievances, setGrievances] = useState([]);
  const [search, setSearch] = useState('');

  const fetchGrievances = () => {
    fetch('http://localhost:8000/api/grievances')
      .then(r => r.json())
      .then(d => setGrievances(d.records))
      .catch(console.error);
  };

  useEffect(() => {
    fetchGrievances();
  }, []);

  const handleResolve = (id) => {
    fetch(`http://localhost:8000/api/grievances/${id}/resolve`, { method: 'POST' })
      .then(() => fetchGrievances());
  };

  const filtered = grievances.filter(g => 
    g.department_assigned?.toLowerCase().includes(search.toLowerCase()) || 
    g.emergency_type?.toLowerCase().includes(search.toLowerCase()) ||
    g.restated_summary?.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="flex-1 p-8 overflow-y-auto bg-[#030304] custom-scrollbar text-white">
      <div className="flex items-center justify-between mb-8">
        <h2 className="text-xl font-bold tracking-widest uppercase text-white/80">Civic Inbox</h2>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
          <input 
            type="text" 
            placeholder="SEARCH BY DEPT OR ISSUE..." 
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="pl-10 pr-4 py-2 bg-white/[0.03] border border-white/10 rounded-md text-[10px] font-bold tracking-widest outline-none focus:border-indigo-500 w-64"
          />
        </div>
      </div>

      <div className="space-y-4">
        {filtered.map(g => (
          <div key={g.call_id} className="p-5 bg-white/[0.02] border border-white/5 rounded-xl shadow-md flex items-start justify-between group hover:bg-white/[0.04] transition-colors">
            <div className="flex flex-col gap-2 max-w-2xl">
              <div className="flex items-center gap-3">
                <span className="px-2.5 py-1 rounded bg-indigo-500/10 text-indigo-400 text-[9px] font-black tracking-widest border border-indigo-500/20">
                  {g.department_assigned}
                </span>
                <span className={`px-2.5 py-1 rounded text-[9px] font-black tracking-widest border ${
                  g.priority === 'CRITICAL' ? 'bg-red-500/10 text-red-400 border-red-500/20' : 
                  g.priority === 'HIGH' ? 'bg-orange-500/10 text-orange-400 border-orange-500/20' : 
                  'bg-white/5 text-white/40 border-white/10'
                }`}>
                  PRIORITY: {g.priority}
                </span>
                <span className="text-[10px] text-white/30 font-mono">{g.call_id}</span>
              </div>
              <p className="text-sm font-medium text-white/90 leading-relaxed mt-1">
                {g.restated_summary || "No summary captured."}
              </p>
              <div className="flex items-center gap-4 mt-2">
                <div className="flex items-center gap-1.5 text-white/40">
                  <MapPin className="w-3 h-3" />
                  <span className="text-[9px] uppercase font-bold tracking-widest">{g.language}</span>
                </div>
                <div className="flex items-center gap-1.5 text-white/40">
                  <span className="text-[9px] uppercase font-bold tracking-widest">
                    Sentiment: <span className="text-white/70">{g.sentiment}</span>
                  </span>
                </div>
              </div>
            </div>

            <div className="flex flex-col items-end gap-3">
              <div className="flex items-center gap-2">
                {g.resolution_status === 'RESOLVED' ? (
                  <span className="flex items-center gap-1.5 text-[10px] font-black tracking-widest text-emerald-400">
                    <CheckCircle className="w-4 h-4" /> RESOLVED
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 text-[10px] font-black tracking-widest text-amber-400">
                    <Clock className="w-4 h-4" /> PENDING
                  </span>
                )}
              </div>
              {g.resolution_status !== 'RESOLVED' && (
                <button 
                  onClick={() => handleResolve(g.call_id)}
                  className="px-4 py-2 mt-2 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/30 rounded text-[9px] font-black tracking-widest uppercase transition-all shadow-inner"
                >
                  Mark Resolved
                </button>
              )}
            </div>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="p-12 text-center text-white/30 text-[10px] font-bold tracking-widest uppercase">
            No grievances found.
          </div>
        )}
      </div>
    </div>
  );
}
