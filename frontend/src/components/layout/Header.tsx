export type AppPage = 'pipeline' | 'audit'

interface HeaderProps {
  page: AppPage
  onPageChange: (p: AppPage) => void
}

export function Header({ page, onPageChange }: HeaderProps) {
  return (
    <header className="flex items-center justify-between px-6 py-3 border-b border-[var(--color-border)] bg-[var(--color-surface)]">
      <div className="flex items-center gap-3">
        <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center text-xs font-bold">
          R
        </div>
        <span className="font-semibold text-white tracking-tight">RAG Ingestion Engine</span>
        <span className="text-xs text-slate-500 ml-1">v2.0</span>
      </div>

      <div className="flex items-center gap-2 rounded-lg border border-fuchsia-500/30 bg-fuchsia-500/10 px-3 py-1.5">
        <span className="text-sm font-semibold text-fuchsia-300">Mode D</span>
        <span className="text-xs text-fuchsia-400/80">Agent (auto-routes)</span>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={() => onPageChange(page === 'audit' ? 'pipeline' : 'audit')}
          className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all border ${
            page === 'audit'
              ? 'bg-indigo-600 text-white border-indigo-500'
              : 'text-slate-400 hover:text-white border-slate-700 hover:border-slate-500'
          }`}
        >
          Audit Log
        </button>
        <span className="text-xs text-slate-500">FastAPI · Qdrant</span>
      </div>
    </header>
  )
}
