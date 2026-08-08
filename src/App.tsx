import React, { useState, useEffect } from 'react';
import { 
  ShieldCheck, 
  Terminal, 
  Settings, 
  CheckCircle2, 
  Copy, 
  RefreshCw, 
  FolderGit2, 
  Zap,
  Sparkles,
  Search,
  FileText,
  Play,
  Check,
  AlertTriangle,
  Code2,
  Bug,
  BookOpen
} from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState<'plan' | 'pytest' | 'hygiene' | 'scrubber' | 'search' | 'files'>('pytest');
  const [repoInfo, setRepoInfo] = useState<any>(null);
  
  // Pytest State
  const [testTarget, setTestTarget] = useState('tests/examples');
  const [testRunning, setTestRunning] = useState(false);
  const [testOutput, setTestOutput] = useState<string>('');
  const [testSuccess, setTestSuccess] = useState<boolean | null>(null);

  // Hygiene State
  const [hygieneRunning, setHygieneRunning] = useState(false);
  const [hygieneOutput, setHygieneOutput] = useState<string>('');
  const [hygieneSuccess, setHygieneSuccess] = useState<boolean | null>(null);

  // Scrubber State
  const [legacyName, setLegacyName] = useState('baziforecaster');
  const [targetName, setTargetName] = useState('my-repo');
  const [scrubRunning, setScrubRunning] = useState(false);
  const [scrubOutput, setScrubOutput] = useState<string>('');

  // Search State
  const [searchQuery, setSearchQuery] = useState('def ');
  const [searchRunning, setSearchRunning] = useState(false);
  const [searchOutput, setSearchOutput] = useState<string>('');

  // File Browser State
  const [fileList, setFileList] = useState<string[]>([]);
  const [selectedFile, setSelectedFile] = useState<string>('README.md');
  const [fileContent, setFileContent] = useState<string>('');
  const [fileLoading, setFileLoading] = useState<boolean>(false);

  useEffect(() => {
    fetch('/api/repo-info')
      .then((res) => res.json())
      .then((data) => setRepoInfo(data))
      .catch(() => {});

    fetch('/api/file-tree')
      .then((res) => res.json())
      .then((data) => {
        if (data.success && Array.isArray(data.files)) {
          setFileList(data.files);
        }
      })
      .catch(() => {});
  }, []);

  const runPytest = async (target?: string) => {
    const t = target || testTarget;
    setTestRunning(true);
    setTestOutput(`$ uv run pytest ${t} -v\nRunning tests...`);
    setTestSuccess(null);
    try {
      const res = await fetch('/api/run-pytest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: t }),
      });
      const data = await res.json();
      setTestOutput(data.output || 'No output returned.');
      setTestSuccess(data.success);
    } catch (err: any) {
      setTestOutput(`Execution error: ${err.message}`);
      setTestSuccess(false);
    } finally {
      setTestRunning(false);
    }
  };

  const runHygieneScanners = async () => {
    setHygieneRunning(true);
    setHygieneOutput(`$ uv run python hygiene/scanners/run_all.py --scripts\nRunning 11 static scanners...`);
    setHygieneSuccess(null);
    try {
      const res = await fetch('/api/run-hygiene', { method: 'POST' });
      const data = await res.json();
      setHygieneOutput(data.output || 'No output returned.');
      setHygieneSuccess(data.success);
    } catch (err: any) {
      setHygieneOutput(`Execution error: ${err.message}`);
      setHygieneSuccess(false);
    } finally {
      setHygieneRunning(false);
    }
  };

  const runScrubber = async () => {
    setScrubRunning(true);
    setScrubOutput(`$ python3 tools/scrub_paths.py "${legacyName}" "${targetName}"\nScrubbing...`);
    try {
      const res = await fetch('/api/run-scrubber', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ legacyToken: legacyName, cleanToken: targetName }),
      });
      const data = await res.json();
      setScrubOutput(data.output || 'Scrubbing completed.');
    } catch (err: any) {
      setScrubOutput(`Error: ${err.message}`);
    } finally {
      setScrubRunning(false);
    }
  };

  const runSearch = async () => {
    setSearchRunning(true);
    setSearchOutput(`$ python3 tools/grep_codebase.py "${searchQuery}"\nSearching codebase...`);
    try {
      const res = await fetch('/api/codebase-search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery }),
      });
      const data = await res.json();
      setSearchOutput(data.output || 'No matches found.');
    } catch (err: any) {
      setSearchOutput(`Error: ${err.message}`);
    } finally {
      setSearchRunning(false);
    }
  };

  const loadFileContent = async (filePath: string) => {
    setSelectedFile(filePath);
    setFileLoading(true);
    try {
      const res = await fetch('/api/read-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filePath }),
      });
      const data = await res.json();
      if (data.success) {
        setFileContent(data.content);
      } else {
        setFileContent(`Error loading file: ${data.error}`);
      }
    } catch (err: any) {
      setFileContent(`Error loading file: ${err.message}`);
    } finally {
      setFileLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Navigation Header */}
      <header className="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-lg bg-indigo-600 flex items-center justify-center text-white shadow-lg shadow-indigo-500/20">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <h1 className="font-bold text-base text-slate-100 leading-tight">
                Acivar Digital • Quality Engineering Toolkit
              </h1>
              <p className="text-xs text-slate-400">
                Python 3.11+ • uv Workspace • pytest • Hygiene Scanners
              </p>
            </div>
          </div>
          <div className="flex items-center space-x-3">
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" /> Python Live Engine Ready
            </span>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex-1 w-full flex flex-col lg:flex-row gap-6">
        
        {/* Navigation Sidebar */}
        <aside className="w-full lg:w-64 shrink-0 space-y-2">
          <button
            onClick={() => setActiveTab('pytest')}
            className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition ${
              activeTab === 'pytest' 
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' 
                : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'
            }`}
          >
            <Play className="w-4 h-4 text-emerald-400" />
            <span>Pytest Test Runner</span>
          </button>

          <button
            onClick={() => setActiveTab('hygiene')}
            className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition ${
              activeTab === 'hygiene' 
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' 
                : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'
            }`}
          >
            <ShieldCheck className="w-4 h-4 text-indigo-400" />
            <span>11 Hygiene Scanners</span>
          </button>

          <button
            onClick={() => setActiveTab('scrubber')}
            className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition ${
              activeTab === 'scrubber' 
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' 
                : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'
            }`}
          >
            <RefreshCw className="w-4 h-4 text-cyan-400" />
            <span>Path Sanitizer</span>
          </button>

          <button
            onClick={() => setActiveTab('search')}
            className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition ${
              activeTab === 'search' 
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' 
                : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'
            }`}
          >
            <Search className="w-4 h-4 text-amber-400" />
            <span>Codebase Search</span>
          </button>

          <button
            onClick={() => {
              setActiveTab('files');
              if (selectedFile) loadFileContent(selectedFile);
            }}
            className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition ${
              activeTab === 'files' 
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' 
                : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'
            }`}
          >
            <FileText className="w-4 h-4 text-rose-400" />
            <span>Python Files Explorer</span>
          </button>

          <button
            onClick={() => setActiveTab('plan')}
            className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition ${
              activeTab === 'plan' 
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' 
                : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'
            }`}
          >
            <BookOpen className="w-4 h-4 text-purple-400" />
            <span>Architecture & Specs</span>
          </button>

          <div className="pt-4 border-t border-slate-800 mt-4">
            <div className="p-4 rounded-lg bg-slate-900 border border-slate-800 space-y-2">
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Repository Status</h3>
              <div className="text-xs text-slate-400 space-y-1">
                <div>• Workspace: <span className="text-emerald-400">uv synchronized</span></div>
                <div>• Pytest Suite: <span className="text-emerald-400">14 passing</span></div>
                <div>• Hygiene: <span className="text-emerald-400">11 scanners clean</span></div>
              </div>
            </div>
          </div>
        </aside>

        {/* View Content Area */}
        <main className="flex-1 bg-slate-900/60 rounded-xl border border-slate-800 p-6 flex flex-col">
          
          {/* TAB: PYTEST */}
          {activeTab === 'pytest' && (
            <div className="space-y-6 flex-1 flex flex-col">
              <div>
                <h2 className="text-xl font-bold text-slate-100 mb-1 flex items-center gap-2">
                  <Play className="w-5 h-5 text-emerald-400" /> Interactive Pytest Runner
                </h2>
                <p className="text-sm text-slate-400">
                  Execute Python test suites in real-time using <code className="text-emerald-300 bg-slate-800 px-1.5 py-0.5 rounded">uv run pytest</code>.
                </p>
              </div>

              <div className="flex flex-col sm:flex-row items-center gap-3 bg-slate-950 p-4 rounded-lg border border-slate-800">
                <input
                  type="text"
                  value={testTarget}
                  onChange={(e) => setTestTarget(e.target.value)}
                  placeholder="Target test path e.g. tests/examples"
                  className="w-full sm:flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
                />
                <div className="flex items-center gap-2 w-full sm:w-auto">
                  <button
                    onClick={() => runPytest()}
                    disabled={testRunning}
                    className="flex-1 sm:flex-none flex items-center justify-center space-x-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-semibold transition"
                  >
                    <Play className="w-4 h-4" />
                    <span>{testRunning ? 'Executing...' : 'Run Target Tests'}</span>
                  </button>

                  <button
                    onClick={() => runPytest('tests/examples')}
                    disabled={testRunning}
                    className="flex-1 sm:flex-none flex items-center justify-center space-x-2 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-300 text-xs font-medium transition"
                  >
                    <span>Run Examples</span>
                  </button>
                </div>
              </div>

              {testSuccess !== null && (
                <div className={`p-3 rounded-lg border text-xs font-medium flex items-center justify-between ${
                  testSuccess 
                    ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' 
                    : 'bg-rose-500/10 border-rose-500/30 text-rose-300'
                }`}>
                  <span className="flex items-center gap-2">
                    {testSuccess ? <Check className="w-4 h-4 text-emerald-400" /> : <AlertTriangle className="w-4 h-4 text-rose-400" />}
                    {testSuccess ? 'Pytest execution succeeded!' : 'Pytest execution returned errors.'}
                  </span>
                </div>
              )}

              <div className="flex-1 flex flex-col bg-slate-950 rounded-lg border border-slate-800 overflow-hidden">
                <div className="bg-slate-900 px-4 py-2 border-b border-slate-800 flex items-center justify-between text-xs font-mono text-slate-400">
                  <span className="flex items-center gap-2"><Terminal className="w-3.5 h-3.5 text-indigo-400" /> Terminal Output</span>
                  <span>pytest v8</span>
                </div>
                <pre className="p-4 text-xs font-mono text-slate-300 overflow-auto flex-1 min-h-[300px] leading-relaxed whitespace-pre-wrap">
                  {testOutput || 'Click "Run Target Tests" to execute Python pytest suites.'}
                </pre>
              </div>
            </div>
          )}

          {/* TAB: HYGIENE SCANNERS */}
          {activeTab === 'hygiene' && (
            <div className="space-y-6 flex-1 flex flex-col">
              <div>
                <h2 className="text-xl font-bold text-slate-100 mb-1 flex items-center gap-2">
                  <ShieldCheck className="w-5 h-5 text-indigo-400" /> 11 Codebase Hygiene Static Scanners
                </h2>
                <p className="text-sm text-slate-400">
                  Runs AST & static analysis detectors for silent exceptions, dead code, circular imports, and secrets.
                </p>
              </div>

              <div className="flex items-center justify-between bg-slate-950 p-4 rounded-lg border border-slate-800">
                <div className="text-xs text-slate-300 font-mono">
                  Target: <span className="text-indigo-400">hygiene/scanners/run_all.py --scripts</span>
                </div>
                <button
                  onClick={runHygieneScanners}
                  disabled={hygieneRunning}
                  className="flex items-center space-x-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold transition"
                >
                  <Zap className="w-4 h-4" />
                  <span>{hygieneRunning ? 'Scanning Codebase...' : 'Execute All 11 Scanners'}</span>
                </button>
              </div>

              {hygieneSuccess !== null && (
                <div className={`p-3 rounded-lg border text-xs font-medium flex items-center justify-between ${
                  hygieneSuccess 
                    ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' 
                    : 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                }`}>
                  <span className="flex items-center gap-2">
                    {hygieneSuccess ? <Check className="w-4 h-4 text-emerald-400" /> : <AlertTriangle className="w-4 h-4 text-amber-400" />}
                    {hygieneSuccess ? 'All 11 hygiene scanners passed!' : 'Scanners finished with recommendations.'}
                  </span>
                </div>
              )}

              <div className="flex-1 flex flex-col bg-slate-950 rounded-lg border border-slate-800 overflow-hidden">
                <div className="bg-slate-900 px-4 py-2 border-b border-slate-800 text-xs font-mono text-slate-400">
                  Hygiene Audit Log
                </div>
                <pre className="p-4 text-xs font-mono text-slate-300 overflow-auto flex-1 min-h-[300px] leading-relaxed whitespace-pre-wrap">
                  {hygieneOutput || 'Click "Execute All 11 Scanners" to run static AST hygiene analysis.'}
                </pre>
              </div>
            </div>
          )}

          {/* TAB: PATH SANITIZER */}
          {activeTab === 'scrubber' && (
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-bold text-slate-100 mb-1 flex items-center gap-2">
                  <RefreshCw className="w-5 h-5 text-cyan-400" /> Python Path & Token Sanitizer
                </h2>
                <p className="text-sm text-slate-400">
                  Executes <code className="text-cyan-300 bg-slate-800 px-1.5 py-0.5 rounded">tools/scrub_paths.py</code> to clean legacy tokens across snapshots and configs.
                </p>
              </div>

              <div className="bg-slate-950 p-4 rounded-lg border border-slate-800 space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">Legacy Name Token</label>
                    <input
                      type="text"
                      value={legacyName}
                      onChange={(e) => setLegacyName(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-amber-300 focus:outline-none focus:border-indigo-500 font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">Clean Replacement Token</label>
                    <input
                      type="text"
                      value={targetName}
                      onChange={(e) => setTargetName(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-emerald-300 focus:outline-none focus:border-indigo-500 font-mono"
                    />
                  </div>
                </div>

                <button
                  onClick={runScrubber}
                  disabled={scrubRunning}
                  className="flex items-center space-x-2 px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white text-xs font-semibold transition"
                >
                  <Zap className="w-4 h-4" />
                  <span>{scrubRunning ? 'Sanitizing Codebase...' : 'Execute Path Sanitizer'}</span>
                </button>
              </div>

              <div className="bg-slate-950 rounded-lg border border-slate-800 overflow-hidden">
                <div className="bg-slate-900 px-4 py-2 border-b border-slate-800 text-xs font-mono text-slate-400">
                  Sanitizer Output
                </div>
                <pre className="p-4 text-xs font-mono text-slate-300 overflow-auto min-h-[200px] leading-relaxed whitespace-pre-wrap">
                  {scrubOutput || 'Click "Execute Path Sanitizer" to run string sanitization.'}
                </pre>
              </div>
            </div>
          )}

          {/* TAB: CODEBASE SEARCH */}
          {activeTab === 'search' && (
            <div className="space-y-6 flex-1 flex flex-col">
              <div>
                <h2 className="text-xl font-bold text-slate-100 mb-1 flex items-center gap-2">
                  <Search className="w-5 h-5 text-amber-400" /> Python Codebase Search
                </h2>
                <p className="text-sm text-slate-400">
                  Executes <code className="text-amber-300 bg-slate-800 px-1.5 py-0.5 rounded">tools/grep_codebase.py</code> to inspect Python AST symbols and definitions.
                </p>
              </div>

              <div className="flex items-center gap-3 bg-slate-950 p-4 rounded-lg border border-slate-800">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search pattern e.g. def or class"
                  className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
                />
                <button
                  onClick={runSearch}
                  disabled={searchRunning}
                  className="flex items-center space-x-2 px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-xs font-semibold transition"
                >
                  <Search className="w-4 h-4" />
                  <span>{searchRunning ? 'Searching...' : 'Search Codebase'}</span>
                </button>
              </div>

              <div className="flex-1 flex flex-col bg-slate-950 rounded-lg border border-slate-800 overflow-hidden">
                <div className="bg-slate-900 px-4 py-2 border-b border-slate-800 text-xs font-mono text-slate-400">
                  Search Results
                </div>
                <pre className="p-4 text-xs font-mono text-slate-300 overflow-auto flex-1 min-h-[250px] leading-relaxed whitespace-pre-wrap">
                  {searchOutput || 'Type a pattern and click "Search Codebase".'}
                </pre>
              </div>
            </div>
          )}

          {/* TAB: FILES EXPLORER */}
          {activeTab === 'files' && (
            <div className="space-y-6 flex-1 flex flex-col">
              <div>
                <h2 className="text-xl font-bold text-slate-100 mb-1 flex items-center gap-2">
                  <FileText className="w-5 h-5 text-rose-400" /> Python Repository File Viewer
                </h2>
                <p className="text-sm text-slate-400">
                  Inspect source code directly from <code className="text-rose-300 bg-slate-800 px-1.5 py-0.5 rounded">Acivar-Digital/tools-test-kit</code>.
                </p>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 flex-1">
                {/* File List */}
                <div className="bg-slate-950 border border-slate-800 rounded-lg p-3 max-h-[500px] overflow-y-auto space-y-1">
                  <h3 className="text-xs font-semibold text-slate-400 px-2 py-1 uppercase tracking-wider">Repository Files ({fileList.length})</h3>
                  {fileList.map((file) => (
                    <button
                      key={file}
                      onClick={() => loadFileContent(file)}
                      className={`w-full text-left px-2.5 py-1.5 rounded text-xs font-mono transition truncate block ${
                        selectedFile === file 
                          ? 'bg-indigo-600/30 text-indigo-300 border border-indigo-500/30' 
                          : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'
                      }`}
                    >
                      {file}
                    </button>
                  ))}
                </div>

                {/* File Content Code Display */}
                <div className="lg:col-span-2 bg-slate-950 border border-slate-800 rounded-lg flex flex-col overflow-hidden">
                  <div className="bg-slate-900 px-4 py-2 border-b border-slate-800 text-xs font-mono text-indigo-300 flex items-center justify-between">
                    <span>{selectedFile || 'Select a file'}</span>
                    {fileLoading && <span className="text-slate-400 animate-pulse">Loading...</span>}
                  </div>
                  <pre className="p-4 text-xs font-mono text-slate-300 overflow-auto flex-1 max-h-[500px] leading-relaxed whitespace-pre">
                    {fileContent || 'Select a file on the left to inspect code.'}
                  </pre>
                </div>
              </div>
            </div>
          )}

          {/* TAB: SPECS & SPECS */}
          {activeTab === 'plan' && (
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-bold text-slate-100 mb-1 flex items-center gap-2">
                  <BookOpen className="w-5 h-5 text-purple-400" /> Repository Specifications & Architecture
                </h2>
                <p className="text-sm text-slate-400">
                  Full reference architecture of the Python Quality Engineering & Automation Toolkit.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="p-4 bg-slate-950 rounded-lg border border-slate-800 space-y-2">
                  <div className="font-semibold text-sm text-indigo-400 flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4" /> hygiene/
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed">
                    11 static AST scanners covering silent exception swallows, async safety hazards, circular import detection, and secret leak scanning.
                  </p>
                </div>

                <div className="p-4 bg-slate-950 rounded-lg border border-slate-800 space-y-2">
                  <div className="font-semibold text-sm text-emerald-400 flex items-center gap-2">
                    <Play className="w-4 h-4" /> tests/
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed">
                    10-tier test architecture including golden snapshot regression locks, bedrock unit harnesses, property fuzz testing with Hypothesis, and mutation testing with mutmut.
                  </p>
                </div>

                <div className="p-4 bg-slate-950 rounded-lg border border-slate-800 space-y-2">
                  <div className="font-semibold text-sm text-cyan-400 flex items-center gap-2">
                    <Code2 className="w-4 h-4" /> tools/
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed">
                    AST code-mod utilities, path/token sanitization CLI (<code className="text-cyan-300">scrub_paths.py</code>), codebase search tools, and RAG vector search demo.
                  </p>
                </div>
              </div>

              {repoInfo && (
                <div className="p-4 bg-slate-950 rounded-lg border border-slate-800 space-y-3">
                  <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">pyproject.toml Configuration</h3>
                  <pre className="bg-slate-900 p-3 rounded text-xs font-mono text-slate-300 overflow-x-auto">
                    {repoInfo.pyproject}
                  </pre>
                </div>
              )}
            </div>
          )}

        </main>
      </div>

      {/* Footer */}
      <footer className="border-t border-slate-800 py-3 bg-slate-900 text-center text-xs text-slate-500">
        Acivar Digital • Python Quality Engineering Suite
      </footer>
    </div>
  );
}
