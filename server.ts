import express from 'express';
import path from 'path';
import { exec } from 'child_process';
import { promisify } from 'util';
import fs from 'fs';
import { createServer as createViteServer } from 'vite';

const execAsync = promisify(exec);
const PORT = 3000;
const ENV_PATH = 'export PATH="/root/.local/bin:$PATH" && ';

async function startServer() {
  const app = express();
  app.use(express.json());

  // API Routes
  app.get('/api/repo-info', async (req, res) => {
    try {
      const readme = fs.existsSync('README.md') ? fs.readFileSync('README.md', 'utf-8') : '';
      const pyproject = fs.existsSync('pyproject.toml') ? fs.readFileSync('pyproject.toml', 'utf-8') : '';
      res.json({
        name: 'Acivar-Digital/tools-test-kit',
        language: 'Python 3.11+',
        packageManager: 'uv',
        pyproject,
        readme,
        status: 'active'
      });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post('/api/run-pytest', async (req, res) => {
    const { target = 'tests/examples' } = req.body;
    try {
      const { stdout, stderr } = await execAsync(`${ENV_PATH} uv run pytest ${target} -v`, { cwd: process.cwd() });
      res.json({ success: true, output: stdout || stderr });
    } catch (err: any) {
      res.json({ success: false, output: err.stdout || err.stderr || err.message });
    }
  });

  app.post('/api/run-hygiene', async (req, res) => {
    try {
      const { stdout, stderr } = await execAsync(`${ENV_PATH} uv run python hygiene/scanners/run_all.py --scripts`, { cwd: process.cwd() });
      res.json({ success: true, output: stdout || stderr });
    } catch (err: any) {
      res.json({ success: false, output: err.stdout || err.stderr || err.message });
    }
  });

  app.post('/api/run-scrubber', async (req, res) => {
    const { legacyToken = 'baziforecaster', cleanToken = 'my-repo' } = req.body;
    try {
      const { stdout, stderr } = await execAsync(`python3 tools/scrub_paths.py "${legacyToken}" "${cleanToken}"`, { cwd: process.cwd() });
      res.json({ success: true, output: stdout || stderr });
    } catch (err: any) {
      res.json({ success: false, output: err.stdout || err.stderr || err.message });
    }
  });

  app.post('/api/codebase-search', async (req, res) => {
    const { query = 'def ' } = req.body;
    try {
      const { stdout, stderr } = await execAsync(`python3 tools/grep_codebase.py "${query}"`, { cwd: process.cwd() });
      res.json({ success: true, output: stdout || stderr });
    } catch (err: any) {
      res.json({ success: false, output: err.stdout || err.stderr || err.message });
    }
  });

  app.get('/api/file-tree', async (req, res) => {
    try {
      const { stdout } = await execAsync(`python3 tools/list_files.py .`, { cwd: process.cwd() });
      res.json({ success: true, files: JSON.parse(stdout) });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post('/api/read-file', (req, res) => {
    const { filePath } = req.body;
    const resolvedPath = path.resolve(process.cwd(), filePath);
    if (!resolvedPath.startsWith(process.cwd())) {
      return res.status(403).json({ error: 'Access denied' });
    }
    if (fs.existsSync(resolvedPath)) {
      const content = fs.readFileSync(resolvedPath, 'utf-8');
      res.json({ success: true, content });
    } else {
      res.status(404).json({ error: 'File not found' });
    }
  });

  // Vite Middleware for Frontend Serving
  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Python Quality Engineering Server running on http://0.0.0.0:${PORT}`);
  });
}

startServer();
