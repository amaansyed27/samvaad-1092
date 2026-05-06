import { useState, useEffect } from 'react';
import { CheckCircle, Clock, Search, MapPin, ChevronDown, ChevronUp, AlertCircle, Info, ShieldAlert } from 'lucide-react';

export default function GrievanceInbox() {
  const [grievances, setGrievances] = useState([]);
  const [search, setSearch] = useState('');
  const [expandedId, setExpandedId] = useState(null);

  const fetchGrievances = () => {
    fetch('http://localhost:8000/api/grievances')
      .then(r => r.json())
      .then(d => setGrievances(d.records))
      .catch(console.error);
  };

  useEffect(() => {
    fetchGrievances();
  }, []);

  const handleResolve = (e, id) => {
    e.stopPropagation(); // prevent expanding row
    fetch(`http://localhost:8000/api/grievances/${id}/resolve`, { method: 'POST' })
      .then(() => fetchGrievances());
  };

  const toggleRow = (id) => {
    setExpandedId(expandedId === id ? null : id);
  };

  const filtered = grievances.filter(g => 
    g.department_assigned?.toLowerCase().includes(search.toLowerCase()) || 
    g.emergency_type?.toLowerCase().includes(search.toLowerCase()) ||
    g.location_hint?.toLowerCase().includes(search.toLowerCase()) ||
    g.raw_transcript?.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="flex-1 p-8 overflow-y-auto bg-[#030304] custom-scrollbar text-white">
      <div className="flex items-center justify-between mb-8">
        <h2 className="text-xl font-bold tracking-widest uppercase text-white/80">Civic Inbox</h2>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
          <input 
            type="text" 
            placeholder="SEARCH BY DEPT, LOCATION OR ISSUE..." 
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="pl-10 pr-4 py-2 bg-white/[0.03] border border-white/10 rounded-md text-[10px] font-bold tracking-widest outline-none focus:border-indigo-500 w-80 transition-colors"
          />
        </div>
      </div>

      <div className="bg-white/[0.01] border border-white/5 rounded-xl overflow-hidden shadow-2xl">
        {/* Table Header */}
        <div className="grid grid-cols-12 gap-4 px-6 py-4 bg-black/40 border-b border-white/5 text-[9px] font-black tracking-widest text-white/30 uppercase">
          <div className="col-span-1">Ticket ID</div>
          <div className="col-span-2">Department</div>
          <div className="col-span-3">Location</div>
          <div className="col-span-2">Issue Type</div>
          <div className="col-span-1">Priority</div>
          <div className="col-span-2">Status</div>
          <div className="col-span-1 text-right">Actions</div>
        </div>

        {/* Table Body */}
        <div className="divide-y divide-white/5">
          {filtered.map(g => {
            const isExpanded = expandedId === g.call_id;
            
            return (
              <div key={g.call_id} className={`transition-colors duration-200 ${isExpanded ? 'bg-white/[0.03]' : 'hover:bg-white/[0.02]'}`}>
                {/* Main Row */}
                <div 
                  className="grid grid-cols-12 gap-4 px-6 py-4 items-center cursor-pointer group"
                  onClick={() => toggleRow(g.call_id)}
                >
                  <div className="col-span-1 flex items-center gap-2">
                    {isExpanded ? <ChevronUp className="w-3 h-3 text-indigo-400" /> : <ChevronDown className="w-3 h-3 text-white/20 group-hover:text-white/50" />}
                    <span className="text-[10px] font-mono text-white/50">{g.call_id.substring(0, 6)}</span>
                  </div>
                  
                  <div className="col-span-2">
                    <span className="px-2 py-1 rounded bg-indigo-500/10 text-indigo-400 text-[9px] font-black tracking-widest border border-indigo-500/20">
                      {g.department_assigned}
                    </span>
                  </div>
                  
                  <div className="col-span-3 pr-4">
                    <div className="flex items-center gap-1.5 text-white/70">
                      <MapPin className="w-3 h-3 text-white/30 flex-none" />
                      <span className="text-xs truncate font-medium" title={g.location_hint || "Location pending"}>
                        {g.location_hint || "Location pending..."}
                      </span>
                    </div>
                  </div>
                  
                  <div className="col-span-2 flex flex-col">
                    <span className="text-xs font-bold text-white/80 truncate">{g.emergency_type}</span>
                    <span className="text-[9px] text-white/40 uppercase mt-0.5">Lang: {g.language}</span>
                  </div>
                  
                  <div className="col-span-1">
                    <span className={`text-[10px] font-black tracking-widest uppercase ${
                      g.priority === 'CRITICAL' ? 'text-red-400' : 
                      g.priority === 'HIGH' ? 'text-orange-400' : 
                      g.priority === 'MEDIUM' ? 'text-yellow-400' : 'text-white/40'
                    }`}>
                      {g.priority}
                    </span>
                  </div>
                  
                  <div className="col-span-2 flex items-center gap-2">
                    {g.resolution_status === 'RESOLVED' ? (
                      <span className="flex items-center gap-1.5 text-[10px] font-black tracking-widest text-emerald-400">
                        <CheckCircle className="w-3 h-3" /> RESOLVED
                      </span>
                    ) : (
                      <span className="flex items-center gap-1.5 text-[10px] font-black tracking-widest text-amber-400">
                        <Clock className="w-3 h-3" /> {g.resolution_status}
                      </span>
                    )}
                  </div>
                  
                  <div className="col-span-1 flex justify-end">
                    {g.resolution_status !== 'RESOLVED' && (
                      <button 
                        onClick={(e) => handleResolve(e, g.call_id)}
                        className="px-3 py-1.5 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/30 rounded text-[9px] font-black tracking-widest uppercase transition-all shadow-inner"
                      >
                        Resolve
                      </button>
                    )}
                  </div>
                </div>

                {/* Expanded "Quick View" Data Panel */}
                {isExpanded && (
                  <div className="px-6 py-6 bg-black/20 border-t border-white/5 animate-slide-up">
                    <div className="grid grid-cols-2 gap-8">
                      
                      {/* Left Column: The Transcript */}
                      <div className="space-y-4">
                        <div className="flex items-center gap-2 mb-3">
                          <span className="text-[10px] font-black tracking-[0.2em] text-white/30 uppercase">Call Transcript</span>
                          <div className="h-px flex-1 bg-white/5" />
                        </div>
                        <div className="p-4 rounded-lg bg-white/[0.02] border border-white/5 font-medium text-sm leading-relaxed text-white/80 relative">
                          <div className="absolute top-4 left-4 text-2xl opacity-10">"</div>
                          <p className="pl-6 relative z-10">{g.raw_transcript || "Transcript unavailable."}</p>
                        </div>
                        
                        <div className="flex gap-4">
                          <div className="flex-1 p-3 rounded-lg bg-white/[0.01] border border-white/5">
                            <span className="block text-[8px] font-black tracking-widest uppercase text-white/30 mb-1">Caller Sentiment</span>
                            <span className="text-xs font-bold text-white/70 capitalize">{g.sentiment}</span>
                          </div>
                          <div className="flex-1 p-3 rounded-lg bg-white/[0.01] border border-white/5">
                            <span className="block text-[8px] font-black tracking-widest uppercase text-white/30 mb-1">PII Entities Scrubbed</span>
                            <span className="text-xs font-bold text-indigo-400">{g.pii_entities_count} PII Redacted</span>
                          </div>
                        </div>
                      </div>

                      {/* Right Column: AI Analysis Deep Dive */}
                      <div className="space-y-4">
                        <div className="flex items-center gap-2 mb-3">
                          <span className="text-[10px] font-black tracking-[0.2em] text-white/30 uppercase">AI Semantic Analysis</span>
                          <div className="h-px flex-1 bg-white/5" />
                        </div>
                        
                        {/* Key Details */}
                        <div className="p-4 rounded-lg bg-indigo-500/5 border border-indigo-500/10">
                          <span className="flex items-center gap-1.5 text-[9px] font-black tracking-widest uppercase text-indigo-400 mb-3">
                            <Info className="w-3 h-3" /> Extracted Key Details
                          </span>
                          {g.key_details && g.key_details.length > 0 ? (
                            <ul className="space-y-2">
                              {g.key_details.map((detail, idx) => (
                                <li key={idx} className="flex gap-2 text-xs text-indigo-100/70 font-medium">
                                  <span className="text-indigo-400/50 mt-0.5">▪</span> {detail}
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <p className="text-xs text-white/30 italic">No key details extracted.</p>
                          )}
                        </div>

                        {/* Cultural Context */}
                        <div className="p-4 rounded-lg bg-purple-500/5 border border-purple-500/10">
                           <span className="flex items-center gap-1.5 text-[9px] font-black tracking-widest uppercase text-purple-400 mb-2">
                            <ShieldAlert className="w-3 h-3" /> Cultural Context & Idioms
                          </span>
                          <p className="text-xs text-purple-100/70 font-medium leading-relaxed">
                            {g.cultural_context || "No specific dialect or cultural nuance detected."}
                          </p>
                        </div>

                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          
          {filtered.length === 0 && (
            <div className="p-16 flex flex-col items-center justify-center text-white/30">
              <AlertCircle className="w-8 h-8 mb-4 opacity-50" />
              <p className="text-xs font-bold tracking-widest uppercase">No civic grievances found.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
