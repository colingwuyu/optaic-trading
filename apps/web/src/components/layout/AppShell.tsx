import { useState } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { cn } from "../../lib/utils";

export function AppShell() {
  const [isAssistantOpen, setIsAssistantOpen] = useState(false);

  return (
    <div className="flex h-screen bg-slate-950 text-white overflow-hidden">
      {/* Sidebar */}
      <Sidebar
        onToggleAssistant={() => setIsAssistantOpen(!isAssistantOpen)}
        isAssistantOpen={isAssistantOpen}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Page Content */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>

        {/* Status Bar */}
        <footer className="h-6 px-4 flex items-center justify-between bg-slate-900 border-t border-slate-800 text-xs text-slate-500">
          <span>OptAIC Platform v0.1.0</span>
          <span>Connected</span>
        </footer>
      </div>

      {/* Assistant Panel (Right) */}
      <aside
        className={cn(
          "flex-shrink-0 border-l border-slate-800 bg-slate-900 transition-all duration-200 overflow-hidden",
          isAssistantOpen ? "w-80" : "w-0"
        )}
      >
        {isAssistantOpen && (
          <div className="h-full flex flex-col">
            <div className="h-14 px-4 flex items-center justify-between border-b border-slate-800">
              <span className="font-semibold">Notifications</span>
              <button
                onClick={() => setIsAssistantOpen(false)}
                className="p-1 hover:bg-slate-800 rounded text-slate-400"
              >
                &times;
              </button>
            </div>
            <div className="flex-1 p-4 overflow-y-auto">
              <p className="text-slate-500 text-sm text-center">
                No new notifications
              </p>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
