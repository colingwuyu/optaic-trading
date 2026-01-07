import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  GitBranch,
  PlayCircle,
  Database,
  Activity,
  Cpu,
  BrainCircuit,
  LayoutDashboard,
  Zap,
  BookOpen,
  Settings,
  User,
  Bell,
  ChevronLeft,
  ChevronRight,
  Home,
} from "lucide-react";
import { cn } from "../../lib/utils";

interface NavItem {
  path: string;
  label: string;
  icon: React.ElementType;
  color: string;
}

const navigationItems: NavItem[] = [
  { path: "/app", label: "Home", icon: Home, color: "text-slate-400" },
  {
    path: "/app/signals",
    label: "Signal Hub",
    icon: GitBranch,
    color: "text-blue-400",
  },
  {
    path: "/app/backtest",
    label: "Backtests",
    icon: PlayCircle,
    color: "text-purple-400",
  },
  {
    path: "/app/inventory",
    label: "Data Inventory",
    icon: Database,
    color: "text-cyan-400",
  },
  {
    path: "/app/experiments",
    label: "Experiments",
    icon: Activity,
    color: "text-indigo-400",
  },
  {
    path: "/app/catalog",
    label: "Definitions",
    icon: Cpu,
    color: "text-violet-400",
  },
  {
    path: "/app/mlops",
    label: "MLOps",
    icon: BrainCircuit,
    color: "text-orange-400",
  },
  {
    path: "/app/monitor",
    label: "Monitor",
    icon: LayoutDashboard,
    color: "text-emerald-400",
  },
  {
    path: "/app/regime",
    label: "Regime Intel",
    icon: Zap,
    color: "text-amber-400",
  },
  {
    path: "/app/docs",
    label: "Documentation",
    icon: BookOpen,
    color: "text-rose-400",
  },
];

interface SidebarProps {
  onToggleAssistant?: () => void;
  isAssistantOpen?: boolean;
}

export function Sidebar({
  onToggleAssistant,
  isAssistantOpen,
}: SidebarProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const location = useLocation();

  return (
    <aside
      className={cn(
        "flex flex-col h-full bg-slate-900 border-r border-slate-800 transition-all duration-200",
        isExpanded ? "w-64" : "w-14"
      )}
    >
      {/* Header */}
      <div className="flex items-center h-14 px-2 border-b border-slate-800">
        {isExpanded ? (
          <div className="flex items-center justify-between w-full px-2">
            <span className="text-lg font-semibold text-white">OptAIC</span>
            <button
              onClick={() => setIsExpanded(false)}
              className="p-1 hover:bg-slate-800 rounded"
            >
              <ChevronLeft className="w-4 h-4 text-slate-400" />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setIsExpanded(true)}
            className="w-full flex justify-center p-2 hover:bg-slate-800 rounded"
          >
            <ChevronRight className="w-4 h-4 text-slate-400" />
          </button>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 overflow-y-auto">
        <ul className="space-y-1 px-2">
          {navigationItems.map((item) => {
            const Icon = item.icon;
            const isActive =
              item.path === "/app"
                ? location.pathname === "/app"
                : location.pathname.startsWith(item.path);

            return (
              <li key={item.path}>
                <NavLink
                  to={item.path}
                  className={cn(
                    "flex items-center gap-3 px-2 py-2 rounded-lg transition-colors",
                    isActive
                      ? "bg-slate-800 text-white"
                      : "text-slate-400 hover:bg-slate-800/50 hover:text-white"
                  )}
                >
                  <Icon
                    className={cn("w-5 h-5 flex-shrink-0", item.color)}
                  />
                  {isExpanded && (
                    <span className="text-sm truncate">{item.label}</span>
                  )}
                </NavLink>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Footer Controls */}
      <div className="py-4 px-2 border-t border-slate-800 space-y-1">
        <button
          onClick={onToggleAssistant}
          className={cn(
            "flex items-center gap-3 w-full px-2 py-2 rounded-lg transition-colors",
            isAssistantOpen
              ? "bg-indigo-600 text-white"
              : "text-slate-400 hover:bg-slate-800/50 hover:text-white"
          )}
        >
          <Bell className="w-5 h-5 flex-shrink-0" />
          {isExpanded && <span className="text-sm">Notifications</span>}
        </button>

        <button className="flex items-center gap-3 w-full px-2 py-2 text-slate-400 hover:bg-slate-800/50 hover:text-white rounded-lg transition-colors">
          <Settings className="w-5 h-5 flex-shrink-0" />
          {isExpanded && <span className="text-sm">Settings</span>}
        </button>

        <button className="flex items-center gap-3 w-full px-2 py-2 text-slate-400 hover:bg-slate-800/50 hover:text-white rounded-lg transition-colors">
          <User className="w-5 h-5 flex-shrink-0" />
          {isExpanded && <span className="text-sm">Profile</span>}
        </button>
      </div>
    </aside>
  );
}
