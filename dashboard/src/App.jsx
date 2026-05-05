
import { useState } from 'react';
import './index.css';
import { useCallSocket } from './hooks/useCallSocket';
import LiveTerminal from './components/LiveTerminal';
import AnalyticsOverview from './components/AnalyticsOverview';
import GrievanceInbox from './components/GrievanceInbox';
import { BarChart2, Inbox, PhoneCall, Bug } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState('overview');
  const [debugMode, setDebugMode] = useState(false);

  const socketProps = useCallSocket();

  // Automatically switch to Live Terminal if a real call comes in
  if (socketProps.state !== 'INIT' && activeTab !== 'live' && !debugMode && socketProps.connected) {
      // Small timeout to prevent render cycle issues
      setTimeout(() => setActiveTab('live'), 10);
  }

  return (
    <div className="h-screen flex bg-[#030304] overflow-hidden font-sans">
      
      {/* ── Sidebar Navigation ── */}
      <nav className="w-20 flex-none bg-black/80 border-r border-white/5 flex flex-col items-center py-6 gap-8 z-30">
        <div className="w-10 h-10 rounded-xl bg-indigo-500/20 border border-indigo-500/40 flex items-center justify-center mb-4 shadow-[0_0_15px_rgba(99,102,241,0.2)]">
          <div className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse" />
        </div>
        
        <NavButton icon={<BarChart2 />} active={activeTab === 'overview'} onClick={() => setActiveTab('overview')} label="Overview" />
        <NavButton icon={<Inbox />} active={activeTab === 'inbox'} onClick={() => setActiveTab('inbox')} label="Inbox" />
        <NavButton icon={<PhoneCall />} active={activeTab === 'live'} onClick={() => setActiveTab('live')} label="Live Call" pulse={socketProps.state !== 'INIT'} />

        <div className="mt-auto pt-8 border-t border-white/5 w-full flex justify-center">
          <button 
            onClick={() => setDebugMode(!debugMode)}
            title="Toggle Debug / Demo Mode"
            className={`p-3 rounded-xl transition-all ${debugMode ? 'bg-amber-500/20 text-amber-400 border-amber-500/30 border shadow-inner' : 'text-white/30 hover:text-white/60 hover:bg-white/5'}`}
          >
            <Bug className="w-5 h-5" />
          </button>
        </div>
      </nav>

      {/* ── Main Content Area ── */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="flex-none h-16 flex items-center justify-between px-8 bg-black/60 border-b border-white/5 backdrop-blur-xl z-20">
          <div>
            <h1 className="text-xs font-black tracking-[0.3em] text-white/90 uppercase">
              Samvaad <span className="text-indigo-400">1092</span>
            </h1>
            <p className="text-[8px] text-white/30 font-bold tracking-widest uppercase">Civic Grievance Management System</p>
          </div>
          
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-3 px-4 py-2 rounded-full bg-white/[0.02] border border-white/5 shadow-inner">
               <span className="text-[10px] font-black tracking-widest text-white/40 uppercase">{socketProps.state}</span>
               <div className={`w-1.5 h-1.5 rounded-full ${socketProps.connected ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : 'bg-red-500'}`} />
               <span className={`text-[10px] font-black tracking-widest ${socketProps.connected ? 'text-emerald-400' : 'text-red-400'} uppercase`}>
                 {socketProps.connected ? 'Gateway Active' : 'Disconnected'}
               </span>
            </div>
          </div>
        </header>

        {activeTab === 'overview' && <AnalyticsOverview />}
        {activeTab === 'inbox' && <GrievanceInbox />}
        {activeTab === 'live' && <LiveTerminal {...socketProps} debugMode={debugMode} />}
      </div>
    </div>
  );
}

function NavButton({ icon, active, onClick, label, pulse }) {
  return (
    <button 
      onClick={onClick}
      title={label}
      className={`relative p-3 rounded-xl transition-all duration-300 group ${
        active 
          ? 'bg-indigo-500/20 text-indigo-400 shadow-[inset_0_0_12px_rgba(99,102,241,0.2)]' 
          : 'text-white/40 hover:text-white/80 hover:bg-white/5'
      }`}
    >
      {icon}
      {pulse && (
        <span className="absolute top-2 right-2 flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
        </span>
      )}
    </button>
  );
}
