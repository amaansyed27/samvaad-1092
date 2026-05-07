import { useState, useEffect } from 'react';
import { CheckCircle, Clock, Search, MapPin, ChevronDown, ChevronUp, AlertCircle, Info, ShieldAlert, ChevronsUpDown } from 'lucide-react';

function MemoryField({ label, value, wide = false }) {
  const display = value === true ? 'Yes' : value === false ? 'No' : value || 'Not captured';
  return (
    <div className={wide ? 'col-span-2' : ''}>
      <span className="block text-[8px] font-black tracking-widest uppercase text-white/30 mb-1">{label}</span>
      <span className="text-white/75 font-semibold break-words">{display}</span>
    </div>
  );
}

export default function GrievanceInbox() {
  const [grievances, setGrievances] = useState([]);
  const [search, setSearch] = useState('');
  const [expandedId, setExpandedId] = useState(null);
  const [sortField, setSortField] = useState('date');
  const [sortDirection, setSortDirection] = useState('desc');

  const fetchGrievances = () => {
    fetch('/api/grievances')
      .then(r => r.json())
      .then(d => setGrievances(d.records))
      .catch(console.error);
  };

  useEffect(() => {
    fetchGrievances();
  }, []);

  const handleResolve = (e, id) => {
    e.stopPropagation(); // prevent expanding row
    fetch(`/api/grievances/${id}/resolve`, { method: 'POST' })
      .then(() => fetchGrievances());
  };

  const toggleRow = (id) => {
    setExpandedId(expandedId === id ? null : id);
  };

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection(field === 'date' || field === 'priority' || field === 'status' ? 'desc' : 'asc');
    }
  };

  const filtered = grievances.filter(g => 
    g.department_assigned?.toLowerCase().includes(search.toLowerCase()) || 
    g.emergency_type?.toLowerCase().includes(search.toLowerCase()) ||
    g.location_hint?.toLowerCase().includes(search.toLowerCase()) ||
    g.raw_transcript?.toLowerCase().includes(search.toLowerCase())
  );

  const priorityWeight = { 'CRITICAL': 4, 'HIGH': 3, 'MEDIUM': 2, 'LOW': 1 };
  const statusWeight = { 'PENDING': 3, 'ESCALATED': 2, 'RESOLVED': 1 };

  const sorted = [...filtered].sort((a, b) => {
    let comparison = 0;
    if (sortField === 'date') {
      comparison = new Date(a.completed_at || 0).getTime() - new Date(b.completed_at || 0).getTime();
    } else if (sortField === 'priority') {
      comparison = (priorityWeight[a.priority] || 0) - (priorityWeight[b.priority] || 0);
    } else if (sortField === 'status') {
      comparison = (statusWeight[a.resolution_status] || 0) - (statusWeight[b.resolution_status] || 0);
    } else if (sortField === 'department') {
      comparison = (a.department_assigned || '').localeCompare(b.department_assigned || '');
    }
    return sortDirection === 'asc' ? comparison : -comparison;
  });

  const SortIcon = ({ field }) => {
    if (sortField !== field) return <ChevronsUpDown className="w-3 h-3 opacity-30" />;
    return sortDirection === 'asc' ? <ChevronUp className="w-3 h-3 text-indigo-400" /> : <ChevronDown className="w-3 h-3 text-indigo-400" />;
  };

  const asObject = (value, fallback = {}) => {
    if (!value) return fallback;
    if (typeof value === 'string') {
      try { return JSON.parse(value); } catch (_) { return fallback; }
    }
    return value;
  };

  const asArray = (value) => {
    const parsed = asObject(value, []);
    return Array.isArray(parsed) ? parsed : [];
  };

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
        <div className="grid grid-cols-12 gap-4 px-6 py-4 bg-black/40 border-b border-white/5 text-[9px] font-black tracking-widest text-white/30 uppercase select-none">
          <div className="col-span-1 flex items-center gap-1 cursor-pointer hover:text-white/50 transition-colors" onClick={() => handleSort('date')}>
            Ticket ID <SortIcon field="date" />
          </div>
          <div className="col-span-2 flex items-center gap-1 cursor-pointer hover:text-white/50 transition-colors" onClick={() => handleSort('department')}>
            Department <SortIcon field="department" />
          </div>
          <div className="col-span-3">Location</div>
          <div className="col-span-2">Issue Type</div>
          <div className="col-span-1 flex items-center gap-1 cursor-pointer hover:text-white/50 transition-colors" onClick={() => handleSort('priority')}>
            Priority <SortIcon field="priority" />
          </div>
          <div className="col-span-2 flex items-center gap-1 cursor-pointer hover:text-white/50 transition-colors" onClick={() => handleSort('status')}>
            Status <SortIcon field="status" />
          </div>
          <div className="col-span-1 text-right">Actions</div>
        </div>

        {/* Table Body */}
        <div className="divide-y divide-white/5">
          {sorted.map(g => {
            const isExpanded = expandedId === g.call_id;
            const memory = asObject(g.conversation_memory);
            const conversation = asArray(g.conversation_transcript);
            
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

                        <div className="p-4 rounded-lg bg-white/[0.02] border border-white/5">
                          <span className="block text-[9px] font-black tracking-widest uppercase text-white/30 mb-3">Conversation Turn Log</span>
                          {conversation.length > 0 ? (
                            <div className="space-y-2 max-h-72 overflow-y-auto pr-1 custom-scrollbar">
                              {conversation.map((turn, idx) => (
                                <div key={`${turn.timestamp || idx}-${idx}`} className="grid grid-cols-[76px_1fr] gap-3 text-xs">
                                  <span className={`font-black uppercase tracking-widest ${turn.role === 'assistant' ? 'text-indigo-300' : 'text-emerald-300'}`}>
                                    {turn.role || 'turn'}
                                  </span>
                                  <span className="text-white/70 leading-relaxed">{turn.text}</span>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="text-xs text-white/30 italic">Detailed conversation log unavailable for older calls.</p>
                          )}
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
                        <div className="p-4 rounded-lg bg-emerald-500/5 border border-emerald-500/10">
                          <span className="flex items-center gap-1.5 text-[9px] font-black tracking-widest uppercase text-emerald-400 mb-3">
                            <Info className="w-3 h-3" /> Ticket Intake Memory
                          </span>
                          <div className="grid grid-cols-2 gap-3 text-xs">
                            <MemoryField label="Request Type" value={memory.request_type} />
                            <MemoryField label="Issue" value={memory.issue || g.emergency_type} />
                            <MemoryField label="Department" value={memory.department || g.department_assigned} />
                            <MemoryField label="Line Department" value={memory.line_department} />
                            <MemoryField label="Service/Scheme" value={memory.service_or_scheme} />
                            <MemoryField label="Application/Ref" value={memory.application_or_reference || memory.previous_complaint} />
                            <MemoryField label="Area" value={memory.area || g.location_hint} />
                            <MemoryField label="Landmark" value={memory.landmark} />
                            <MemoryField label="Time" value={memory.started_at_or_time} />
                            <MemoryField label="Frequency" value={memory.frequency} />
                            <MemoryField label="Office Visited" value={memory.office_visited} />
                            <MemoryField label="Documents/Photo" value={memory.documents_available} />
                            <MemoryField label="Tried Before" value={memory.caller_tried} wide />
                            <MemoryField label="Authority Contacted" value={memory.authority_contacted} />
                            <MemoryField label="Referral/Helpline" value={memory.emergency_referral ? `Emergency: ${memory.specialized_helpline || 'operator'}` : memory.specialized_helpline} />
                            <MemoryField label="Status Lookup" value={memory.status_lookup} wide />
                            <MemoryField label="Learning" value={g.learning_feedback_type || (g.agent_edited ? 'agent_edit' : g.caller_confirmed ? 'verified' : '')} />
                          </div>
                        </div>

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
