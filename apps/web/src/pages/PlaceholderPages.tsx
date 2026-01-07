import {
  Database,
  Activity,
  Cpu,
  BrainCircuit,
  LayoutDashboard,
  Zap,
  BookOpen,
  Settings,
} from "lucide-react";

interface PlaceholderPageProps {
  title: string;
  description: string;
  icon: React.ElementType;
  iconColor: string;
}

function PlaceholderPage({ title, description, icon: Icon, iconColor }: PlaceholderPageProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full">
      <div className={`p-4 rounded-xl bg-slate-800/50 mb-6`}>
        <Icon className={`w-12 h-12 ${iconColor}`} />
      </div>
      <h1 className="text-2xl font-semibold text-white mb-2">{title}</h1>
      <p className="text-slate-400 text-center max-w-md">{description}</p>
      <div className="mt-8 px-4 py-2 bg-slate-800 rounded-lg text-sm text-slate-500">
        Coming soon...
      </div>
    </div>
  );
}

export function InventoryPage() {
  return (
    <PlaceholderPage
      title="Data Inventory"
      description="Browse, preview, and manage your datasets. Upload new data sources and configure refresh schedules."
      icon={Database}
      iconColor="text-cyan-400"
    />
  );
}

export function ExperimentsPage() {
  return (
    <PlaceholderPage
      title="Experiment Studio"
      description="Design and run expression experiments. Test signal combinations and analyze performance."
      icon={Activity}
      iconColor="text-indigo-400"
    />
  );
}

export function CatalogPage() {
  return (
    <PlaceholderPage
      title="Definition Hub"
      description="Browse and manage pipeline definitions, operators, and transformers. Register new plugins."
      icon={Cpu}
      iconColor="text-violet-400"
    />
  );
}

export function MLOpsPage() {
  return (
    <PlaceholderPage
      title="MLOps Center"
      description="Manage ML model lifecycle. Monitor training jobs, deployments, and model performance."
      icon={BrainCircuit}
      iconColor="text-orange-400"
    />
  );
}

export function MonitorPage() {
  return (
    <PlaceholderPage
      title="Live Monitor"
      description="Real-time monitoring of signals, positions, and system health. Configure alerts and dashboards."
      icon={LayoutDashboard}
      iconColor="text-emerald-400"
    />
  );
}

export function RegimePage() {
  return (
    <PlaceholderPage
      title="Regime Intel"
      description="Analyze market regime states and transitions. View historical regime classifications."
      icon={Zap}
      iconColor="text-amber-400"
    />
  );
}

export function DocsPage() {
  return (
    <PlaceholderPage
      title="Documentation"
      description="API reference, SDK guides, and platform documentation."
      icon={BookOpen}
      iconColor="text-rose-400"
    />
  );
}

export function AdminPage() {
  return (
    <PlaceholderPage
      title="Administration"
      description="Manage users, teams, permissions, and platform settings."
      icon={Settings}
      iconColor="text-slate-400"
    />
  );
}
