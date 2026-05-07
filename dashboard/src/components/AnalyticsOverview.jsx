
import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { Activity, CheckCircle, Clock, AlertTriangle, BrainCircuit, RefreshCw } from 'lucide-react';

export default function AnalyticsOverview() {
  const [data, setData] = useState(null);
  const [mlStatus, setMlStatus] = useState(null);
  const [isRetraining, setIsRetraining] = useState(false);

  const fetchAnalytics = () => {
    fetch('/api/analytics/overview')
      .then(r => r.json())
      .then(setData)
      .catch(console.error);
      
    fetch('/api/ml/status')
      .then(r => r.json())
      .then(setMlStatus)
      .catch(console.error);
  };

  useEffect(() => {
    fetchAnalytics();
    // Set an interval to refresh ML status
    const interval = setInterval(fetchAnalytics, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleRetrain = async () => {
    setIsRetraining(true);
    try {
      const res = await fetch('/api/ml/retrain', { method: 'POST' });
      const result = await res.json();
      if (result.success) {
        // Short timeout for UX
        setTimeout(() => {
          fetchAnalytics();
          setIsRetraining(false);
        }, 1000);
      }
    } catch (e) {
      console.error(e);
      setIsRetraining(false);
    }
  };

  if (!data) return <div className="p-8 text-white/50 text-sm tracking-widest uppercase">Loading Analytics...</div>;

  const COLORS = ['#818cf8', '#2dd4a0', '#f5a524', '#ef4444', '#a78bfa', '#f472b6'];

  return (
    <div className="flex-1 p-8 overflow-y-auto bg-[#030304] custom-scrollbar text-white">
      <div className="flex justify-between items-end mb-8">
        <h2 className="text-xl font-bold tracking-widest uppercase text-white/80">Civic Operations Overview</h2>
        
        {/* ML Health Card */}
        <div className="flex items-center gap-4 p-4 rounded-xl bg-white/[0.02] border border-white/5 shadow-lg">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${mlStatus?.pending_corrections > 0 ? 'bg-amber-500/20 text-amber-400' : 'bg-emerald-500/20 text-emerald-400'}`}>
              <BrainCircuit className="w-5 h-5" />
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-black tracking-widest uppercase text-white/40">Model Health</span>
              <span className="text-xs font-bold text-white/90">
                {mlStatus?.pending_corrections || 0} Pending Edge Cases
              </span>
            </div>
          </div>
          
          <button 
            onClick={handleRetrain}
            disabled={isRetraining || mlStatus?.pending_corrections === 0}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${
              isRetraining 
                ? 'bg-indigo-500/50 text-white cursor-not-allowed' 
                : mlStatus?.pending_corrections > 0
                  ? 'bg-indigo-500/20 text-indigo-400 hover:bg-indigo-500/30 border border-indigo-500/30'
                  : 'bg-white/5 text-white/20 cursor-not-allowed border border-white/5'
            }`}
          >
            <RefreshCw className={`w-3 h-3 ${isRetraining ? 'animate-spin' : ''}`} />
            {isRetraining ? 'Retraining...' : 'Deploy Active Learning'}
          </button>
        </div>
      </div>
      
      <div className="grid grid-cols-4 gap-6 mb-8">
        <StatCard title="Total Grievances" value={data.total_calls} icon={<Activity className="text-indigo-400" />} />
        <StatCard title="Resolved Issues" value={data.resolved_calls} icon={<CheckCircle className="text-emerald-400" />} />
        <StatCard title="Resolution Rate" value={`${data.resolution_rate}%`} icon={<Clock className="text-amber-400" />} />
        <StatCard title="Active Escalations" value={data.total_calls - data.resolved_calls} icon={<AlertTriangle className="text-red-400" />} />
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Bar Chart: Depts */}
        <div className="p-6 bg-white/[0.02] border border-white/5 rounded-xl shadow-lg">
          <h3 className="text-[10px] font-black tracking-[0.2em] text-white/40 uppercase mb-6">Grievances by Department</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.departments}>
                <XAxis dataKey="name" stroke="rgba(255,255,255,0.2)" fontSize={10} tickLine={false} axisLine={false} />
                <YAxis stroke="rgba(255,255,255,0.2)" fontSize={10} tickLine={false} axisLine={false} />
                <Tooltip cursor={{ fill: 'rgba(255,255,255,0.05)' }} contentStyle={{ background: '#09090b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }} />
                <Bar dataKey="count" fill="#818cf8" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Pie Chart: Statuses */}
        <div className="p-6 bg-white/[0.02] border border-white/5 rounded-xl shadow-lg flex flex-col items-center">
          <h3 className="text-[10px] font-black tracking-[0.2em] text-white/40 uppercase mb-2 self-start w-full">Resolution Status</h3>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={data.statuses} dataKey="count" nameKey="name" cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={5}>
                  {data.statuses.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ background: '#09090b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="flex gap-4 mt-4">
            {data.statuses.map((s, i) => (
              <div key={s.name} className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
                <span className="text-[10px] text-white/60 uppercase font-bold tracking-widest">{s.name} ({s.count})</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({ title, value, icon }) {
  return (
    <div className="p-6 bg-white/[0.02] border border-white/5 rounded-xl shadow-lg flex items-center justify-between">
      <div>
        <h4 className="text-[10px] font-black tracking-[0.1em] text-white/30 uppercase mb-1">{title}</h4>
        <span className="text-3xl font-light text-white/90">{value}</span>
      </div>
      <div className="p-4 bg-white/[0.02] rounded-full border border-white/5 shadow-inner">
        {icon}
      </div>
    </div>
  );
}
